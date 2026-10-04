#!/usr/bin/env python3
"""Tamagotchi P1 in the browser: emulator loop, Care-Bot and a small web server.

    python3 server.py            # then open http://127.0.0.1:8137

The pet lives in this process: it keeps running while no browser is open and
its state is saved to tama_state.json (every minute and on exit).

The ROM is not part of this project. Without one the server only shows the
settings page, which asks for the file.
"""
import argparse
import base64
import collections
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libtama.so")
if not os.path.exists(LIB):
    subprocess.check_call(["make", "-C", HERE])

import growth  # noqa: E402
from carebot import CareBot  # noqa: E402
from report import DailyReport, smtp_from_env  # noqa: E402
from tama import BTN_A, BTN_B, BTN_C, LCD_H, LCD_W, TICK_HZ, Tama  # noqa: E402

CHUNK = 1024                    # ticks per emulation slice (1/32 s)
FRAME = 1 / 30                  # seconds between screen updates
SPEEDS = (1, 2, 5, 20, 0)       # 0 = as fast as possible
MIN_HOLD = int(0.1 * TICK_HZ)   # shortest button press the ROM reliably sees
BUTTONS = {"A": BTN_A, "B": BTN_B, "C": BTN_C}
PAGES = {"/": "index.html", "/index.html": "index.html", "/bot": "bot.html",
         "/settings": "settings.html"}

# tama.b of the MAME set "tama": the ROM all RAM addresses here were found in
ROM_SIZE = 12288
ROM_SHA1 = "4b4979cf92dc9d2fb6d7295a38f209f3da144f72"
ROM_CRC32 = "5c864cb1"
MAX_UPLOAD = 4 << 20
SMTP_SECURITY = ("starttls", "ssl", "none")


class Refused(Exception):
    """A request that cannot be carried out; the message is shown in the UI."""


def rom_hashes(data):
    return {"size": len(data), "sha1": hashlib.sha1(data).hexdigest(),
            "crc32": "%08x" % zlib.crc32(data)}


def unpack_rom(data):
    """The ROM itself, also when it comes inside MAME's tama.zip."""
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.file_size == ROM_SIZE:
                        rom = z.read(info)
                        if hashlib.sha1(rom).hexdigest() == ROM_SHA1:
                            return rom
        except zipfile.BadZipFile:
            pass
        raise Refused("In der ZIP-Datei ist keine passende tama.b.")
    return data


class App:
    """Settings, the ROM and, once there is a ROM, the running pet."""

    def __init__(self, rom_paths, state_path):
        self.rom_paths = rom_paths      # looked up in this order; uploads go to the first
        self.state_path = state_path
        self.settings_path = os.path.join(os.path.dirname(state_path), "settings.json")
        self.lock = threading.Lock()
        self.engine = None
        self.rom = None                 # hashes of the ROM in use
        self.smtp = smtp_from_env()     # the environment gives the defaults
        try:
            with open(self.settings_path) as f:
                self.smtp.update(json.load(f).get("smtp", {}))
        except FileNotFoundError:
            pass
        self.start()

    def start(self):
        """Bring the pet to life if there is a ROM."""
        for path in self.rom_paths:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    self.rom = dict(rom_hashes(f.read()), path=path)
                self.engine = Engine(path, self.state_path, self.smtp)
                threading.Thread(target=self.engine.loop, daemon=True).start()
                return

    def settings(self):
        smtp = dict(self.smtp, password=bool(self.smtp["password"]))    # never sent back
        return {"rom": self.rom,
                "expected": {"size": ROM_SIZE, "sha1": ROM_SHA1, "crc32": ROM_CRC32},
                "smtp": smtp}

    def set_smtp(self, data):
        with self.lock:
            smtp = dict(self.smtp)
            for key in smtp:
                if key in data:
                    smtp[key] = int(data[key]) if key == "port" else str(data[key]).strip()
            if smtp["security"] not in SMTP_SECURITY or not 0 < smtp["port"] < 65536:
                raise Refused("Port oder Verschlüsselung ist ungültig.")
            self.smtp = smtp
            tmp = self.settings_path + ".tmp"
            with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                json.dump({"smtp": smtp}, f)
            os.replace(tmp, self.settings_path)
            if self.engine:
                with self.engine.lock:
                    self.engine.report.configure(smtp)

    def set_rom(self, data=None, path=None):
        with self.lock:
            if self.engine:
                raise Refused("Es ist schon eine ROM vorhanden.")
            if path is not None:
                try:
                    if os.path.getsize(path) > MAX_UPLOAD:
                        raise Refused("Die Datei ist zu groß für eine Tamagotchi-ROM.")
                    with open(path, "rb") as f:
                        data = f.read()
                except OSError:
                    raise Refused("Die Datei lässt sich auf dem Server nicht lesen.")
            data = unpack_rom(data)
            got = rom_hashes(data)
            if got["sha1"] != ROM_SHA1:
                if path is not None:    # say nothing about other files on the server
                    raise Refused("Die Datei dort ist nicht die erwartete ROM.")
                raise Refused("Das ist nicht die erwartete ROM (%d Bytes, SHA-1 %s)."
                              % (got["size"], got["sha1"]))
            target = self.rom_paths[0]
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(data)
            self.start()

    def stop(self):
        if self.engine:
            self.engine.running = False
            self.engine.save_state()


class Engine:
    def __init__(self, rom_path, state_path, smtp):
        self.state_path = state_path
        self.lock = threading.Lock()
        self.changed = threading.Condition()
        self.tama = Tama(rom_path, LIB)
        self.log = collections.deque(maxlen=60)
        self.log_id = 0
        self.report = DailyReport(self.add_log, smtp)
        self.bot = CareBot(self.tama, self.add_log)
        self.slices = 0
        self.bot_enabled = True
        self.speed = 1
        self.paused = False
        self.pressed = {}       # btn -> tick of the press
        self.release = {}       # btn -> tick at which to let go
        self.sound = []
        self.sounds = []
        self.snapshot = None
        self.version = 0
        self.running = True
        self.load_state()
        self.bot.realtime = self.speed == 1

    def add_log(self, msg):
        self.log_id += 1
        self.log.append((self.log_id, time.strftime("%d.%m. %H:%M"), msg))
        self.report.count(msg)

    # -- persistence -------------------------------------------------------

    def load_state(self):
        try:
            with open(self.state_path) as f:
                data = json.load(f)
        except FileNotFoundError:
            self.add_log("Neues Ei")
            return
        if not self.tama.load(base64.b64decode(data["cpu"])):
            raise SystemExit("%s is not a usable state file" % self.state_path)
        self.bot_enabled = data.get("bot", True)
        self.bot.discipline = data.get("discipline", True)
        self.bot.goal = data.get("goal") if data.get("goal") in growth.GOALS else None
        self.speed = data.get("speed", 1) if data.get("speed", 1) in SPEEDS else 1
        self.report.from_dict(data.get("report", {}))
        self.add_log("Spielstand geladen")

    def save_state(self):
        with self.lock:
            data = {
                "cpu": base64.b64encode(self.tama.save()).decode(),
                "bot": self.bot_enabled,
                "discipline": self.bot.discipline,
                "goal": self.bot.goal,
                "speed": self.speed,
                "report": self.report.to_dict(),
            }
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.state_path)

    # -- commands from the web UI -----------------------------------------

    def button(self, name, down):
        btn = BUTTONS[name]
        with self.lock:
            now = self.tama.ticks
            if down:
                self.tama.button(btn, True)
                self.pressed[btn] = now
                self.release.pop(btn, None)
            elif btn in self.pressed:
                self.release[btn] = max(now, self.pressed[btn] + MIN_HOLD)

    def configure(self, bot=None, discipline=None, speed=None, paused=None, goal=False):
        with self.lock:
            if bot is not None and bool(bot) != self.bot_enabled:
                self.bot_enabled = bool(bot)
                self.bot.stop()
                self.add_log("Care-Bot an" if self.bot_enabled else "Care-Bot aus")
            if discipline is not None:
                self.bot.discipline = bool(discipline)
            if (goal is None or goal in growth.GOALS) and goal != self.bot.goal:
                self.bot.goal = goal
                self.add_log("Ziel: " + (growth.NAMES[goal] if goal else "keins"))
            if speed in SPEEDS:
                self.speed = speed
                self.bot.realtime = speed == 1
            if paused is not None:
                self.paused = bool(paused)

    def reset(self):
        with self.lock:
            self.bot.stop()
            self.bot.clock_set_at = None
            self.tama.reset()
            self.report.reset_counters()
            self.report.asleep = False
            self.add_log("Neues Ei")

    def test_mail(self):
        with self.lock:
            if not self.report.enabled:
                self.add_log("Tagesbericht nicht eingerichtet (Mailserver und Empfänger fehlen)")
            else:
                self.report.send(self.bot.status())

    # -- emulation loop ----------------------------------------------------

    def slice(self):
        tama = self.tama
        tama.run(CHUNK)
        now = tama.ticks
        for btn, at in list(self.release.items()):
            if now >= at:
                tama.button(btn, False)
                del self.release[btn]
                del self.pressed[btn]
        if self.bot_enabled:
            self.bot.step()
        self.slices += 1
        if self.slices % 32 == 0:   # once per emulated second
            self.report.observe(self.bot.status(), *tama.frame(), now)

    def publish(self):
        tama = self.tama
        pixels, icons = tama.frame()
        rows = []
        for y in range(LCD_H):
            bits = 0
            for x in range(LCD_W):
                if pixels[y * LCD_W + x]:
                    bits |= 1 << (LCD_W - 1 - x)
            rows.append("%08x" % bits)
        now = tama.ticks
        self.sound.extend(tama.drain_sound())
        # [milliseconds before "now", frequency in Hz]; only meaningful in real time
        sound = [[round((now - tick) * 1000 / TICK_HZ), freq / 10]
                 for tick, freq in self.sound] if self.speed == 1 else []
        self.sound = []
        status = self.bot.status()
        snap = {
            "lcd": "".join(rows),
            "icons": sum(1 << i for i, v in enumerate(icons) if v),
            "status": status,
            "growth": self.bot.growth(status),
            "bot": self.bot_enabled,
            "discipline": self.bot.discipline,
            "goal": self.bot.goal,
            "speed": self.speed,
            "paused": self.paused,
            "logId": self.log_id,
        }
        with self.changed:
            if sound or snap != self.snapshot:
                self.snapshot = snap
                self.sounds = sound
                self.version += 1
                self.changed.notify_all()

    def loop(self):
        last = time.monotonic()
        owed = 0.0              # emulated ticks we still have to run
        saved = time.monotonic()
        while self.running:
            start = time.monotonic()
            dt = min(start - last, 0.25)    # do not replay a suspended laptop
            last = start
            with self.lock:
                if not self.paused:
                    if self.speed == 0:
                        while time.monotonic() - start < FRAME * 0.8:
                            self.slice()
                    else:
                        owed += dt * TICK_HZ * self.speed
                        while owed >= CHUNK:
                            self.slice()
                            owed -= CHUNK
                self.publish()
            if start - saved > 60:
                saved = start
                self.save_state()
            time.sleep(max(0.0, FRAME - (time.monotonic() - start)))


class Handler(BaseHTTPRequestHandler):
    app = None
    protocol_version = "HTTP/1.1"

    @property
    def engine(self):
        return self.app.engine

    def log_message(self, fmt, *args):
        pass

    def send_body(self, code, body, ctype, headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, code=200):
        self.send_body(code, json.dumps(data).encode(), "application/json")

    def do_GET(self):
        if self.path == "/api/settings":
            self.send_json(self.app.settings())
        elif self.path in PAGES:
            if not self.engine and self.path != "/settings":    # no ROM yet: ask for it
                return self.send_body(302, b"", "text/plain", [("Location", "/settings")])
            with open(os.path.join(HERE, "web", PAGES[self.path]), "rb") as f:
                self.send_body(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/events" and self.engine:
            self.stream()
        else:
            self.send_body(404, b"not found", "text/plain")

    def stream(self):
        eng = self.engine
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        seen, log_seen = -1, -1
        try:
            while eng.running:
                with eng.changed:
                    if eng.version == seen and not eng.changed.wait(timeout=15):
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    seen = eng.version
                    msg = dict(eng.snapshot)
                    msg["sound"] = eng.sounds
                if msg["logId"] != log_seen:
                    log_seen = msg["logId"]
                    msg["log"] = [[when, text] for _, when, text in list(eng.log)]
                self.wfile.write(b"data: " + json.dumps(msg).encode() + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        # Only our own page may send commands (no cross-site requests)
        # (behind a reverse proxy the public name may arrive as X-Forwarded-Host)
        origin = self.headers.get("Origin")
        hosts = (self.headers.get("Host"), self.headers.get("X-Forwarded-Host"))
        if origin and origin.split("://", 1)[-1] not in hosts:
            return self.send_body(403, b"forbidden", "text/plain")
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_UPLOAD:
                raise Refused("Die Datei ist zu groß für eine Tamagotchi-ROM.")
            body = self.rfile.read(length)
            is_json = self.headers.get("Content-Type", "").startswith("application/json")
            if self.path == "/api/rom" and not is_json:
                self.app.set_rom(data=body)     # the file itself
                return self.send_json({})
            data = json.loads(body or b"{}")
            if self.path == "/api/rom":
                self.app.set_rom(path=str(data["path"]))
            elif self.path == "/api/settings":
                self.app.set_smtp(data["smtp"])
            elif not self.engine:
                raise Refused("Es fehlt noch die ROM.")
            elif self.path == "/api/button":
                self.engine.button(data["btn"], bool(data["down"]))
            elif self.path == "/api/config":
                self.engine.configure(data.get("bot"), data.get("discipline"),
                                      data.get("speed"), data.get("paused"),
                                      data.get("goal", False))
            elif self.path == "/api/reset":
                self.engine.reset()
            elif self.path == "/api/test-mail":
                self.engine.test_mail()
            else:
                return self.send_body(404, b"not found", "text/plain")
        except Refused as e:
            return self.send_json({"error": str(e)}, 400)
        except (KeyError, ValueError, TypeError, AttributeError):
            return self.send_json({"error": "Ungültige Anfrage."}, 400)
        self.send_json({})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (0.0.0.0 for the whole network)")
    ap.add_argument("--port", type=int, default=8137)
    ap.add_argument("--rom", help="ROM file (default: tama.b next to the state file, "
                                  "else tama/tama.b; asked for in the browser if missing)")
    ap.add_argument("--state", default=os.path.join(HERE, "tama_state.json"))
    args = ap.parse_args()

    state = os.path.abspath(args.state)
    roms = [args.rom] if args.rom else [os.path.join(os.path.dirname(state), "tama.b"),
                                        os.path.join(HERE, "tama", "tama.b")]
    app = Handler.app = App(roms, state)
    ThreadingHTTPServer.daemon_threads = True
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    print("Tamagotchi läuft auf http://%s:%d  (Strg+C beendet und speichert)"
          % (args.host, args.port), flush=True)
    if not app.engine:
        print("Es fehlt noch die ROM: bitte im Browser angeben.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        if app.engine:
            print("\nSpielstand gespeichert in", state)


if __name__ == "__main__":
    sys.exit(main())
