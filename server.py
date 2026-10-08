#!/usr/bin/env python3
"""Tamagotchis in the browser: any number of pets, each with its Care-Bot.

    python3 server.py            # then open http://127.0.0.1:8137

Every pet runs in a process of its own (engine.py) and keeps running while
no browser is open. This process starts them, serves the web pages and
passes button presses and pictures along. States are saved every minute
and on exit.

The ROMs are not part of this project. Without one the server only shows
the settings page, which asks for the file.
"""
import argparse
import io
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libtama.so")
if not os.path.exists(LIB):
    subprocess.check_call(["make", "-C", HERE])

import engine  # noqa: E402
import models  # noqa: E402
from report import smtp_from_env  # noqa: E402

PAGES = {"/": "index.html", "/index.html": "index.html", "/bot": "bot.html",
         "/settings": "settings.html"}
MAX_UPLOAD = 4 << 20
MAX_NAME = 24
COLORS = ("yellow", "red", "blue", "green", "pink", "teal", "purple", "white")   # of the shell
SMTP_SECURITY = ("starttls", "ssl", "none")
SPAWN = multiprocessing.get_context("spawn")    # a clean process, not a copy of our threads


class Refused(Exception):
    """A request that cannot be carried out; the message is shown in the UI."""


def unpack_rom(data):
    """The ROM itself, also when it comes inside a MAME set like tama.zip."""
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.file_size in [m.size for m in models.MODELS]:
                        rom = z.read(info)
                        if models.identify(rom):
                            return rom
        except zipfile.BadZipFile:
            pass
        raise Refused("In der ZIP-Datei ist keine passende ROM.")
    return data


def write_json(path, data, mode=0o644):
    tmp = path + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


class Pet:
    """One pet as the server sees it: its worker process and the latest picture."""

    def __init__(self, id, name, model, state_path, color=COLORS[0]):
        self.id = id
        self.name = name
        self.color = color if color in COLORS else COLORS[0]
        self.model = model
        self.state_path = state_path
        self.changed = threading.Condition()
        self.snapshot = None
        self.sounds = []
        self.log = []
        self.version = 0
        self.alive = False
        self.error = None
        self.process = None
        self.conn = None
        self.sending = threading.Lock()

    def start(self, rom_path, smtp):
        self.conn, theirs = SPAWN.Pipe()
        self.process = SPAWN.Process(
            target=engine.run, daemon=True,
            args=(theirs, rom_path, self.state_path, smtp, self.model.id, self.name))
        self.process.start()
        theirs.close()
        self.alive = True
        threading.Thread(target=self.listen, daemon=True).start()

    def listen(self):
        while True:
            try:
                msg = self.conn.recv()
            except (EOFError, OSError):
                break
            with self.changed:
                if msg[0] == "snap":
                    self.snapshot, self.sounds = msg[1], msg[2]
                    if msg[3] is not None:
                        self.log = msg[3]
                    self.version += 1
                elif msg[0] == "error":
                    self.error = msg[1]
                self.changed.notify_all()
        with self.changed:
            self.alive = False
            self.changed.notify_all()

    def send(self, *msg):
        with self.sending:
            try:
                self.conn.send(msg)
            except (BrokenPipeError, OSError, AttributeError):
                pass

    def stop(self):
        """Ask the worker to save and leave, and wait for it."""
        if self.process:
            self.send("stop")
            self.process.join(10)
            if self.process.is_alive():
                self.process.terminate()

    def describe(self):
        return {"id": self.id, "name": self.name, "color": self.color, "model": self.model.id,
                "modelName": self.model.name, "alive": self.alive, "error": self.error}


class App:
    """Settings, the ROMs and the pets."""

    def __init__(self, data_dir, first_state, rom_args):
        self.data_dir = data_dir
        self.first_state = first_state      # where a single pet used to keep its state
        self.rom_args = rom_args
        self.settings_path = os.path.join(data_dir, "settings.json")
        self.pets_path = os.path.join(data_dir, "pets.json")
        self.lock = threading.Lock()
        self.pets = {}                      # id -> Pet, in the order of the tabs
        self.next_id = 1
        self.roms = {}                      # model id -> path
        self.smtp = smtp_from_env()         # the environment gives the defaults
        try:
            with open(self.settings_path) as f:
                self.smtp.update(json.load(f).get("smtp", {}))
        except FileNotFoundError:
            pass
        self.find_roms()
        self.load_pets()

    # -- ROMs --------------------------------------------------------------

    def find_roms(self):
        """Look where ROMs may lie; the first file found for a model is used."""
        places = list(self.rom_args) + [os.path.join(self.data_dir, "tama.b"),
                                        os.path.join(HERE, "tama", "tama.b"),
                                        os.path.join(self.data_dir, "roms")]
        for place in places:
            if os.path.isdir(place):
                files = sorted(os.path.join(root, name)
                               for root, _, names in os.walk(place) for name in names)
            else:
                files = [place]
            for path in files:
                try:
                    if os.path.getsize(path) not in [m.size for m in models.MODELS]:
                        continue
                    with open(path, "rb") as f:
                        model = models.identify(f.read())
                except OSError:
                    continue
                if model and model.id not in self.roms:
                    self.roms[model.id] = os.path.abspath(path)

    def set_rom(self, data=None, path=None):
        with self.lock:
            if path is not None:
                try:
                    if os.path.getsize(path) > MAX_UPLOAD:
                        raise Refused("Die Datei ist zu groß für eine Tamagotchi-ROM.")
                    with open(path, "rb") as f:
                        data = f.read()
                except OSError:
                    raise Refused("Die Datei lässt sich auf dem Server nicht lesen.")
            data = unpack_rom(data)
            model = models.identify(data)
            if not model:
                if path is not None:    # say nothing about other files on the server
                    raise Refused("Die Datei dort ist keine der erwarteten ROMs.")
                got = models.hashes(data)
                raise Refused("Das ist keine der erwarteten ROMs (%d Bytes, SHA-1 %s)."
                              % (got["size"], got["sha1"]))
            if model.id in self.roms:
                raise Refused("Die ROM des %s ist schon vorhanden." % model.name)
            target = os.path.join(self.data_dir, "roms", model.id + ".bin")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(data)
            self.roms[model.id] = target
            if not self.pets:           # the first ROM: there is a pet right away
                self.add_pet(model, model.name)
            return model

    # -- pets --------------------------------------------------------------

    def load_pets(self):
        try:
            with open(self.pets_path) as f:
                saved = json.load(f)
        except FileNotFoundError:
            saved = self.first_pet()
        self.next_id = saved["next"]
        for entry in saved["pets"]:
            model = models.BY_ID.get(entry["model"])
            if not model:
                continue
            pet = Pet(entry["id"], entry["name"], model,
                      os.path.join(self.data_dir, entry["state"]), entry.get("color"))
            self.pets[pet.id] = pet
            if model.id in self.roms:
                pet.start(self.roms[model.id], self.smtp)
            else:
                pet.error = "Die ROM des %s fehlt." % model.name

    def first_pet(self):
        """Before there were tabs there was one pet: it becomes the first tab."""
        model = None
        try:
            with open(self.first_state) as f:
                model = models.BY_ID.get(json.load(f).get("rom", models.P1.id))
        except FileNotFoundError:
            model = next((m for m in models.MODELS if m.id in self.roms), None)
        if not model:
            return {"next": 1, "pets": []}
        return {"next": 2, "pets": [{"id": "1", "name": model.name, "model": model.id,
                                     "state": os.path.relpath(self.first_state, self.data_dir)}]}

    def save_pets(self):
        write_json(self.pets_path, {"next": self.next_id, "pets": [
            {"id": p.id, "name": p.name, "color": p.color, "model": p.model.id,
             "state": os.path.relpath(p.state_path, self.data_dir)}
            for p in self.pets.values()]})

    def add_pet(self, model, name, color=None):
        """Call with the lock."""
        if color not in COLORS:     # one that tells it apart from the others
            used = [p.color for p in self.pets.values()]
            color = min(COLORS, key=lambda c: (used.count(c), COLORS.index(c)))
        pet = Pet(str(self.next_id), name, model,
                  os.path.join(self.data_dir, "pets", "%d.json" % self.next_id), color)
        self.next_id += 1
        self.pets[pet.id] = pet
        self.save_pets()
        pet.start(self.roms[model.id], self.smtp)
        return pet

    def create_pet(self, model_id, name, color=None):
        with self.lock:
            model = models.BY_ID.get(model_id)
            if not model:
                raise Refused("Dieses Modell gibt es nicht.")
            if model.id not in self.roms:
                raise Refused("Die ROM des %s fehlt noch (unter „Optionen“ angeben)." % model.name)
            name = " ".join(str(name).split())[:MAX_NAME] or model.name
            return self.add_pet(model, name, color)

    def paint_pet(self, pet_id, color):
        with self.lock:
            if color not in COLORS:
                raise Refused("Diese Farbe gibt es nicht.")
            self.pet(pet_id).color = color
            self.save_pets()

    def remove_pet(self, pet_id):
        """Stops the pet and puts its state aside (deleted/), it is not destroyed."""
        with self.lock:
            pet = self.pets.pop(pet_id, None)
            if not pet:
                raise Refused("Dieses Tier gibt es nicht.")
            self.save_pets()
        pet.stop()
        if os.path.exists(pet.state_path):
            aside = os.path.join(self.data_dir, "deleted")
            os.makedirs(aside, exist_ok=True)
            os.replace(pet.state_path, os.path.join(
                aside, "%s-%s.json" % (pet.id, time.strftime("%Y%m%d-%H%M%S"))))

    def pet(self, pet_id):
        pet = self.pets.get(str(pet_id))
        if not pet:
            raise Refused("Dieses Tier gibt es nicht.")
        return pet

    def overview(self):
        return {"pets": [p.describe() for p in list(self.pets.values())],
                "models": [dict(m.describe(), rom=m.id in self.roms) for m in models.MODELS],
                "colors": COLORS}

    # -- settings ----------------------------------------------------------

    def settings(self):
        smtp = dict(self.smtp, password=bool(self.smtp["password"]))    # never sent back
        return {"roms": [dict(m.describe(), path=self.roms.get(m.id)) for m in models.MODELS],
                "pets": len(self.pets), "smtp": smtp}

    def set_smtp(self, data):
        with self.lock:
            smtp = dict(self.smtp)
            for key in smtp:
                if key in data:
                    smtp[key] = int(data[key]) if key == "port" else str(data[key]).strip()
            if smtp["security"] not in SMTP_SECURITY or not 0 < smtp["port"] < 65536:
                raise Refused("Port oder Verschlüsselung ist ungültig.")
            self.smtp = smtp
            write_json(self.settings_path, {"smtp": smtp}, 0o600)
            for pet in self.pets.values():
                pet.send("set_smtp", smtp)

    def stop(self):
        pets = list(self.pets.values())
        for pet in pets:
            pet.send("stop")
        for pet in pets:
            pet.stop()


class Handler(BaseHTTPRequestHandler):
    app = None
    protocol_version = "HTTP/1.1"

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
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path == "/api/settings":
            self.send_json(self.app.settings())
        elif url.path == "/api/pets":
            self.send_json(self.app.overview())
        elif url.path in PAGES:
            if not self.app.pets and url.path != "/settings":   # nothing to show yet
                return self.send_body(302, b"", "text/plain", [("Location", "/settings")])
            with open(os.path.join(HERE, "web", PAGES[url.path]), "rb") as f:
                self.send_body(200, f.read(), "text/html; charset=utf-8")
        elif url.path in ("/favicon.png", "/favicon-dark.png"):
            with open(os.path.join(HERE, "web", url.path[1:]), "rb") as f:
                self.send_body(200, f.read(), "image/png")
        elif url.path == "/events" and query.get("pet", [""])[0] in self.app.pets:
            self.stream(self.app.pets[query["pet"][0]])
        else:
            self.send_body(404, b"not found", "text/plain")

    def stream(self, pet):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        seen, log_seen = -1, -1
        try:
            while pet.alive and pet.id in self.app.pets:
                with pet.changed:
                    if pet.version == seen and not pet.changed.wait(timeout=15):
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    if pet.snapshot is None or pet.version == seen:
                        continue
                    seen = pet.version
                    msg = dict(pet.snapshot)
                    msg["sound"] = pet.sounds
                    log = pet.log
                if msg["logId"] != log_seen:
                    log_seen = msg["logId"]
                    msg["log"] = log
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
        app = self.app
        reply = {}
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_UPLOAD:
                raise Refused("Die Datei ist zu groß für eine Tamagotchi-ROM.")
            body = self.rfile.read(length)
            is_json = self.headers.get("Content-Type", "").startswith("application/json")
            if self.path == "/api/rom" and not is_json:
                reply = {"model": app.set_rom(data=body).name}     # the file itself
                return self.send_json(reply)
            data = json.loads(body or b"{}")
            if self.path == "/api/rom":
                reply = {"model": app.set_rom(path=str(data["path"])).name}
            elif self.path == "/api/settings":
                app.set_smtp(data["smtp"])
            elif self.path == "/api/pets":
                reply = app.create_pet(data["model"], data.get("name", ""),
                                       data.get("color")).describe()
            elif self.path == "/api/pets/color":
                app.paint_pet(str(data["pet"]), data["color"])
            elif self.path == "/api/pets/remove":
                app.remove_pet(str(data["pet"]))
            elif self.path == "/api/button":
                if data["btn"] not in engine.BUTTONS:
                    raise ValueError
                app.pet(data["pet"]).send("button", data["btn"], bool(data["down"]))
            elif self.path == "/api/icon":
                if data["icon"] not in range(7):    # the eighth is the pet calling, not a menu entry
                    raise Refused("Dieses Icon lässt sich nicht anwählen.")
                app.pet(data["pet"]).send("icon", data["icon"])
            elif self.path == "/api/config":
                goal = data.get("goal", False)
                if goal not in (False, None) \
                        and goal not in app.pet(data["pet"]).model.growth.GOALS:
                    raise ValueError
                app.pet(data["pet"]).send("configure", data.get("bot"), data.get("discipline"),
                                          data.get("speed"), data.get("paused"), goal,
                                          data.get("restart"))
            elif self.path == "/api/reset":
                app.pet(data["pet"]).send("reset")
            elif self.path == "/api/test-mail":
                app.pet(data["pet"]).send("test_mail")
            else:
                return self.send_body(404, b"not found", "text/plain")
        except Refused as e:
            return self.send_json({"error": str(e)}, 400)
        except (KeyError, ValueError, TypeError, AttributeError):
            return self.send_json({"error": "Ungültige Anfrage."}, 400)
        self.send_json(reply)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (0.0.0.0 for the whole network)")
    ap.add_argument("--port", type=int, default=8137)
    ap.add_argument("--rom", action="append", default=[],
                    help="a ROM file or a folder with ROMs, may be given several times "
                         "(also looked for: tama.b and roms/ next to the states, tama/tama.b; "
                         "asked for in the browser if there is none)")
    ap.add_argument("--state", default=os.path.join(HERE, "tama_state.json"),
                    help="state file of the first pet; pets.json, settings.json and the "
                         "states of further pets (pets/) are kept in the same folder")
    args = ap.parse_args()

    state = os.path.abspath(args.state)
    app = Handler.app = App(os.path.dirname(state), state, args.rom)
    ThreadingHTTPServer.daemon_threads = True
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    print("Tamagotchi läuft auf http://%s:%d  (Strg+C beendet und speichert)"
          % (args.host, args.port), flush=True)
    if not app.pets:
        print("Es fehlt noch die ROM: bitte im Browser angeben.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        if app.pets:
            print("\nSpielstände gespeichert in", app.data_dir)


if __name__ == "__main__":
    sys.exit(main())
