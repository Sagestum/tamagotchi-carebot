#!/usr/bin/env python3
"""Tamagotchi P1 in the browser: emulator loop, Care-Bot and a small web server.

    python3 server.py            # then open http://127.0.0.1:8137

The pet lives in this process: it keeps running while no browser is open and
its state is saved to tama_state.json (every minute and on exit).
"""
import argparse
import base64
import collections
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libtama.so")
if not os.path.exists(LIB):
    subprocess.check_call(["make", "-C", HERE])

import growth  # noqa: E402
from carebot import CareBot  # noqa: E402
from report import DailyReport  # noqa: E402
from tama import BTN_A, BTN_B, BTN_C, LCD_H, LCD_W, TICK_HZ, Tama  # noqa: E402

CHUNK = 1024                    # ticks per emulation slice (1/32 s)
FRAME = 1 / 30                  # seconds between screen updates
SPEEDS = (1, 2, 5, 20, 0)       # 0 = as fast as possible
MIN_HOLD = int(0.1 * TICK_HZ)   # shortest button press the ROM reliably sees
BUTTONS = {"A": BTN_A, "B": BTN_B, "C": BTN_C}
PAGES = {"/": "index.html", "/index.html": "index.html", "/bot": "bot.html"}


class Engine:
    def __init__(self, rom_path, state_path):
        self.state_path = state_path
        self.lock = threading.Lock()
        self.changed = threading.Condition()
        self.tama = Tama(rom_path, LIB)
        self.log = collections.deque(maxlen=60)
        self.log_id = 0
        self.report = DailyReport(self.add_log)
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
                self.add_log("Tagesbericht nicht eingerichtet (SMTP_HOST und MAIL_TO fehlen)")
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
    engine = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def send_body(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in PAGES:
            with open(os.path.join(HERE, "web", PAGES[self.path]), "rb") as f:
                self.send_body(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/events":
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
            data = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/button":
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
        except (KeyError, ValueError, TypeError):
            return self.send_body(400, b"bad request", "text/plain")
        self.send_body(200, b"{}", "application/json")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (0.0.0.0 for the whole network)")
    ap.add_argument("--port", type=int, default=8137)
    ap.add_argument("--rom", default=os.path.join(HERE, "tama", "tama.b"))
    ap.add_argument("--state", default=os.path.join(HERE, "tama_state.json"))
    args = ap.parse_args()

    engine = Engine(args.rom, args.state)
    Handler.engine = engine
    ThreadingHTTPServer.daemon_threads = True
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    threading.Thread(target=engine.loop, daemon=True).start()
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    print("Tamagotchi läuft auf http://%s:%d  (Strg+C beendet und speichert)"
          % (args.host, args.port), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.running = False
        engine.save_state()
        print("\nSpielstand gespeichert in", args.state)


if __name__ == "__main__":
    sys.exit(main())
