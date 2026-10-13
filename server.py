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
import queue
import re
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
from history import History  # noqa: E402
import models  # noqa: E402
from report import compose, deliver, smtp_from_env  # noqa: E402

PAGES = {"/": "index.html", "/index.html": "index.html", "/bot": "bot.html", "/verlauf": "history.html",
         "/settings": "settings.html", "/chronik": "chronik.html", "/pikachu": "pikachu.html"}
# The drawings of the devices, from BrickEmuPy (CC0)
SHELLS = ("p1.svg", "angel.svg", "morino.svg", "umino.svg", "mothra.svg", "genjin.svg",
          "tamaotch.svg", "digimon.svg", "digimon2.svg", "digimon3.svg", "yasashii.svg", "p1w.svg", "pikachu.svg",
          "p2.svg")
MAX_UPLOAD = 4 << 20
PUBLIC_VIEWERS = 60     # the page for everyone: pictures being watched at a time,
PUBLIC_RATE = 8         # pictures a second for each,
PUBLIC_RATE_GAMEBOY = 4 # (of the Game Boy game, about 8 KB each)
PUBLIC_LONGEST = 3600   # and seconds until a viewer has to connect anew
# the address the page for everyone is reached at, without a slash at the end
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
PUBLIC_WAKE = 60        # seconds between two looks whether a screen saver hides the pet
MAX_NAME = 24
COLORS = ("yellow", "red", "blue", "green", "pink", "teal", "purple", "white")   # of the shell
SMTP_SECURITY = ("starttls", "ssl", "none")
DIGEST_FRESH = 12 * 3600    # a report older than this is from the day before
DUEL_WAIT = 600             # seconds a step of a fight between two pets may take
DUEL_REST = 90              # and the last one, which nothing waits for
DIGEST_WAIT = 10            # seconds given to the pets to say how their day has been
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
        self.lives = []
        self.version = 0
        self.alive = False
        self.error = None
        self.process = None
        self.conn = None
        self.sending = threading.Lock()
        self.on_report = None       # takes (pet, report) for the gathered mail
        self.on_history = None      # takes (pet, events) for the history
        self.duel = queue.Queue()   # what the pet has found in a step of a fight
        self.fighting = threading.Lock()

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
                    if msg[4] is not None:
                        self.lives = msg[4]
                    self.version += 1
                elif msg[0] == "error":
                    self.error = msg[1]
                elif msg[0] == "report" and self.on_report:
                    self.on_report(self, msg[1])
                elif msg[0] == "history" and self.on_history:
                    self.on_history(self, msg[1])
                elif msg[0] == "duel":
                    self.duel.put(msg[1])
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
                "modelName": self.model.name, "game": self.model.game, "alive": self.alive,
                "error": self.error}


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
        # The gathered mail: the reports handed in so far (pet id -> report, its picture as
        # hex) and the day the last one went out
        self.digest_path = os.path.join(data_dir, "digest.json")
        self.digest_lock = threading.Lock()
        self.reports = {}
        self.digest_day = ""
        try:
            with open(self.digest_path) as f:
                saved = json.load(f)
            self.reports, self.digest_day = saved["reports"], saved["day"]
        except (FileNotFoundError, ValueError, KeyError):
            pass
        os.makedirs(data_dir, exist_ok=True)
        self.history = History(os.path.join(data_dir, "history.sqlite"))
        self.find_roms()
        self.load_pets()

    def take_history(self, pet, events):
        try:
            self.history.write(pet.id, pet.name, pet.model.id, events)
        except Exception as err:        # the history must never stop a pet
            print("Verlauf: %s" % err, flush=True)

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
            pet.on_report, pet.on_history = self.take_report, self.take_history
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
        pet.on_report, pet.on_history = self.take_report, self.take_history
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
                    smtp[key] = int(data[key]) if key == "port" else bool(data[key]) \
                        if key == "digest" else str(data[key]).strip()
            if smtp["security"] not in SMTP_SECURITY or not 0 < smtp["port"] < 65536:
                raise Refused("Port oder Verschlüsselung ist ungültig.")
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", smtp["digest_at"]):
                raise Refused("Die Uhrzeit der Sammel-Mail ist ungültig (Stunde:Minute).")
            self.smtp = smtp
            write_json(self.settings_path, {"smtp": smtp}, 0o600)
            for pet in self.pets.values():
                pet.send("set_smtp", smtp)

    # -- a fight between two Digimon ----------------------------------------------

    def fighter(self, pet_id):
        """A pet that can fight now, or Refused with the reason."""
        pet = self.pet(pet_id)
        snap = pet.snapshot or {}
        st = snap.get("status") or {}
        if pet.model.game != "digimon":
            raise Refused("%s ist kein Digimon." % pet.name)
        if not pet.alive or pet.error or not snap:
            raise Refused("%s läuft gerade nicht." % pet.name)
        if snap.get("paused"):
            raise Refused("%s ist pausiert." % pet.name)
        if st.get("dead") or st.get("stage") not in pet.model.growth.FIGHTERS:
            raise Refused("%s kann noch nicht kämpfen (erst ab der dritten Stufe)." % pet.name)
        if st.get("asleep"):
            raise Refused("%s schläft." % pet.name)
        return pet

    def duel(self, host_id, guest_id):
        """Start a fight: the host calls and works out who wins, the guest takes its word.
        The pets are in processes of their own, so the words are carried in three steps."""
        if str(host_id) == str(guest_id):
            raise Refused("Zum Kämpfen braucht es zwei.")
        host, guest = self.fighter(host_id), self.fighter(guest_id)
        if not host.fighting.acquire(blocking=False):
            raise Refused("%s kämpft gerade." % host.name)
        if not guest.fighting.acquire(blocking=False):
            host.fighting.release()
            raise Refused("%s kämpft gerade." % guest.name)

        def ask(pet, *msg):
            while not pet.duel.empty():     # what a fight broken off has left behind
                pet.duel.get_nowait()
            pet.send(*msg)
            try:
                return pet.duel.get(timeout=DUEL_WAIT)
            except queue.Empty:
                return None

        def run():
            try:
                host.send("note", "Kampf gegen %s: beginnt" % guest.name)
                guest.send("note", "Kampf gegen %s: beginnt" % host.name)
                about = ask(guest, "duel_word")
                if about is None:
                    for pet, other in ((host, guest), (guest, host)):
                        pet.send("note", "Kampf gegen %s: %s meldet sich nicht" % (other.name, guest.name))
                    return
                words = ask(host, "duel_host", about, guest.name)
                if not words:
                    guest.send("note", "Kampf gegen %s: nicht zustande gekommen" % host.name)
                    return
                guest.send("duel_guest", words[0], words[1], host.name)
                time.sleep(DUEL_REST)       # the guest shows its fight
            finally:
                host.fighting.release()
                guest.fighting.release()

        threading.Thread(target=run, daemon=True).start()

    # -- the gathered mail ---------------------------------------------------

    def reporting(self):
        """The pets a gathered mail is waiting for. (The Game Boy game has no day to report
        and never falls asleep: the mail would wait for it until the latest hour.)"""
        return [p for p in list(self.pets.values())
                if p.alive and not p.error and p.model.game != "gameboy"]

    def save_digest(self):
        write_json(self.digest_path, {"reports": self.reports, "day": self.digest_day})

    def take_report(self, pet, report):
        """A pet hands in its report. When the last one of the day has come, the mail goes out."""
        report = dict(report, picture=report["picture"].hex() if report.get("picture") else None)
        with self.digest_lock:
            self.reports[pet.id] = report
            self.save_digest()
            fresh = time.time() - DIGEST_FRESH
            if self.digest_day != time.strftime("%Y-%m-%d") and all(
                    self.reports.get(p.id, {"at": 0})["at"] >= fresh for p in self.reporting()):
                self.send_digest()

    def send_digest(self, trial=False):
        """Call with digest_lock. One mail with all the reports handed in. A trial (the
        button on the settings page) leaves the day's mail still to come."""
        if trial:
            kept = {id: r for id, r in self.reports.items() if not r.get("late")}
            try:
                self.digest_day, day = "", self.digest_day
                return self.send_digest()
            finally:
                self.reports, self.digest_day = kept, day
                self.save_digest()
        self.digest_day = time.strftime("%Y-%m-%d")
        pets = [p for p in list(self.pets.values()) if p.id in self.reports]
        sections = [dict(self.reports[p.id], picture=bytes.fromhex(self.reports[p.id]["picture"])
                         if self.reports[p.id].get("picture") else None) for p in pets]
        self.reports = {}
        self.save_digest()
        if not sections:
            return
        smtp = self.smtp

        def done(error):
            for pet in pets:
                pet.send("note", "Sammel-Mail fehlgeschlagen: %s" % error if error
                         else "Sammel-Mail mit %d Berichten gesendet an %s" % (len(pets), smtp["mail_to"]))

        sender = smtp["mail_from"] or smtp["user"] or smtp["mail_to"]
        deliver(smtp, compose(sections, sender, smtp["mail_to"]), done)

    def digest_now(self, wait=DIGEST_WAIT, trial=False):
        """The gathered mail with what there is: pets that have not reported today (still
        awake, or their report is from last night) say how their day has been so far."""
        fresh = time.time() - DIGEST_FRESH
        with self.digest_lock:
            late = [p for p in self.reporting() if self.reports.get(p.id, {"at": 0})["at"] < fresh]
        for pet in late:
            pet.send("report_now")
        until = time.time() + wait
        while time.time() < until:
            time.sleep(0.2)
            with self.digest_lock:
                if all(self.reports.get(p.id, {"at": 0})["at"] >= fresh for p in late):
                    break
        with self.digest_lock:
            self.send_digest(trial)

    def digest_clock(self):
        """At the time of day set, the gathered mail goes out if it has not yet."""
        while True:
            time.sleep(20)
            smtp = self.smtp
            if not (smtp.get("digest") and smtp["host"] and smtp["mail_to"]):
                continue
            if self.digest_day != time.strftime("%Y-%m-%d") \
                    and time.strftime("%H:%M") >= smtp["digest_at"]:
                try:
                    self.digest_now()
                except Exception as e:      # the clock must go on
                    print("Sammel-Mail: %s" % e, file=sys.stderr)

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
        if not any(name == "Cache-Control" for name, _ in headers):
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
        elif url.path.startswith("/shells/") and url.path[8:] in SHELLS:
            # The tabs show them too: the browser keeps them and only asks whether they changed
            path = os.path.join(HERE, "web", "shells", url.path[8:])
            info = os.stat(path)
            keep = [("Cache-Control", "no-cache"), ("ETag", '"%x-%x"' % (info.st_mtime_ns, info.st_size))]
            if self.headers.get("If-None-Match") == keep[1][1]:
                return self.send_body(304, b"", "image/svg+xml", keep)
            with open(path, "rb") as f:
                self.send_body(200, f.read(), "image/svg+xml", keep)
        elif url.path == "/sprites.js":
            with open(os.path.join(HERE, "web", "sprites.js"), "rb") as f:
                self.send_body(200, f.read(), "text/javascript; charset=utf-8")
        elif url.path in ("/favicon.png", "/favicon-dark.png"):
            with open(os.path.join(HERE, "web", url.path[1:]), "rb") as f:
                self.send_body(200, f.read(), "image/png")
        elif url.path == "/api/history/picture":
            png = self.app.history.picture(int(query.get("id", ["0"])[0] or 0), bool(query.get("album")))
            if png is None:
                return self.send_body(404, b"not found", "text/plain")
            self.send_body(200, png, "image/png", [("Cache-Control", "max-age=31536000, immutable")])
        elif url.path == "/api/history":
            # everything the history page shows; the log of one tab on request
            pet = query.get("pet", [None])[0]
            if query.get("log"):
                before = query.get("before", [None])[0]
                self.send_json({"log": self.app.history.log(pet, int(before) if before else None)})
            else:
                self.send_json({"lives": self.app.history.lives(pet, 500), "seen": self.app.history.seen(),
                                "album": self.app.history.album(pet),
                                "models": {m.id: m.name for m in models.MODELS},
                                "tabs": [p.describe() for p in self.app.pets.values()]})
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
        seen, log_seen, lives_seen = -1, -1, -1
        pet.send("wake")                    # the tab was opened
        looked = time.monotonic()
        try:
            while pet.alive and pet.id in self.app.pets:
                if pet.model.game == "gameboy" and time.monotonic() - looked > 5:
                    looked = time.monotonic()
                    pet.send("watched")     # it only runs while its page is open
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
                    log, lives = pet.log, pet.lives
                if msg["logId"] != log_seen:
                    log_seen = msg["logId"]
                    msg["log"] = log
                if msg["livesId"] != lives_seen:
                    lives_seen = msg["livesId"]
                    msg["lives"] = lives
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
            elif self.path == "/api/spar":
                app.pet(data["pet"]).send("spar")
            elif self.path == "/api/duel":
                app.duel(data["pet"], data["other"])
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
                                          data.get("restart"), data.get("shuffle"), data.get("flip"),
                                          data.get("keep"), data.get("pace"))
            elif self.path == "/api/place":
                goal = data.get("goal")
                if data.get("what") not in ("show", "egg", "goal") or data.get("slot", 0) not in range(3) \
                        or goal not in (None, -1) + tuple(app.pet(data["pet"]).model.growth.GOALS):
                    raise ValueError
                app.pet(data["pet"]).send("place", data["what"], data.get("slot", 0), goal)
            elif self.path == "/api/reset":
                app.pet(data["pet"]).send("reset")
            elif self.path == "/api/test-mail":
                if data.get("all") and app.smtp.get("digest"):
                    if not (app.smtp["host"] and app.smtp["mail_to"]):
                        raise Refused("Mailserver und Empfänger fehlen noch.")
                    threading.Thread(target=app.digest_now, kwargs={"trial": True}, daemon=True).start()
                else:
                    app.pet(data["pet"]).send("test_mail")
            else:
                return self.send_body(404, b"not found", "text/plain")
        except Refused as e:
            return self.send_json({"error": str(e)}, 400)
        except (KeyError, ValueError, TypeError, AttributeError):
            return self.send_json({"error": "Ungültige Anfrage."}, 400)
        self.send_json(reply)


class PublicHandler(BaseHTTPRequestHandler):
    """The page for everyone, on a port of its own: the pets to look at, and nothing else.
    It knows no command at all. What it hands out is the picture, what the pet is and the
    lives it has had; not the log (it names the mail address) and no settings."""
    app = None
    protocol_version = "HTTP/1.1"
    viewers = 0
    counting = threading.Lock()
    FILES = {"/": ("public.html", "text/html; charset=utf-8"),
             "/shellart.js": ("shellart.js", "text/javascript; charset=utf-8"),
             "/sprites.js": ("sprites.js", "text/javascript; charset=utf-8"),
             "/vorschau.png": ("vorschau.png", "image/png"),
             "/favicon.png": ("favicon.png", "image/png"),
             "/favicon-dark.png": ("favicon-dark.png", "image/png")}
    STATUS = ("stage", "name", "dead", "asleep", "leaving", "hunger", "happy", "weight", "clock",
              "steps", "moodName", "mood", "saver")
    PLACE = ("slot", "shown", "egg", "stage", "name", "petName", "stageName", "age", "hunger", "happy",
             "weight", "asleep", "sick", "dead")

    def log_message(self, fmt, *args):
        pass

    def send_body(self, code, body, ctype, headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; img-src 'self' data:")
        if not any(name == "Cache-Control" for name, _ in headers):
            self.send_header("Cache-Control", "no-cache")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def refuse(self):
        self.send_body(405, b"read only", "text/plain", [("Allow", "GET, HEAD")])

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = refuse

    def do_HEAD(self):
        self.do_GET()

    def shown(self):
        return [p for p in list(self.app.pets.values()) if p.alive and not p.error]

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path in self.FILES:
            name, ctype = self.FILES[url.path]
            with open(os.path.join(HERE, "web", name), "rb") as f:
                body = f.read()
            if url.path == "/":
                # where the page lives, for search engines and for the preview of a shared link
                body = body.replace(b"__PUBLIC_URL__", PUBLIC_URL.encode())
            self.send_body(200, body, ctype)
        elif url.path == "/robots.txt":
            lines = ["User-agent: *", "Allow: /", "Disallow: /watch", "Disallow: /pets"]
            if PUBLIC_URL:
                lines += ["", "Sitemap: %s/sitemap.xml" % PUBLIC_URL]
            self.send_body(200, "\n".join(lines).encode() + b"\n", "text/plain; charset=utf-8")
        elif url.path == "/sitemap.xml" and PUBLIC_URL:
            self.send_body(200, ('<?xml version="1.0" encoding="UTF-8"?>\n'
                                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                 "<url><loc>%s/</loc></url></urlset>\n" % PUBLIC_URL).encode(),
                           "application/xml")
        elif url.path.startswith("/shells/") and url.path[8:] in SHELLS:
            with open(os.path.join(HERE, "web", "shells", url.path[8:]), "rb") as f:
                self.send_body(200, f.read(), "image/svg+xml", [("Cache-Control", "max-age=3600")])
        elif url.path == "/pets":
            pets = [{"id": p.id, "name": p.name, "model": p.model.id, "modelName": p.model.name,
                     "wiki": models.WIKI.get(p.model.id)} for p in self.shown()]
            self.send_body(200, json.dumps(pets).encode(), "application/json")
        elif url.path == "/picture":
            # a picture from the history (the Game Boy game's characters, as they looked)
            try:
                png = self.app.history.picture(int(query.get("id", ["0"])[0]))
            except ValueError:
                png = None
            if png is None:
                return self.send_body(404, b"not found", "text/plain")
            self.send_body(200, png, "image/png", [("Cache-Control", "max-age=31536000, immutable")])
        elif url.path == "/watch" and self.command == "GET":
            pet = self.app.pets.get(query.get("pet", [""])[0])
            if pet is None or pet not in self.shown():
                return self.send_body(404, b"not found", "text/plain")
            self.watch(pet)
        else:
            self.send_body(404, b"not found", "text/plain")

    def told(self, pet):
        """What the page for everyone gets to know about a pet."""
        snap = pet.snapshot or {}
        status = snap.get("status") or {}
        told = {"model": pet.model.id, "lcd": snap.get("lcd", ""), "icons": snap.get("icons", 0),
                "unit": snap.get("unit"), "goalName": snap.get("goalName"),
                "status": {key: status.get(key) for key in self.STATUS}}
        if snap.get("pets"):            # the Game Boy game: up to three pets, each with its goal
            names = pet.model.names
            told["pets"] = [dict({key: p.get(key) for key in self.PLACE},
                                 goalName=names.get(p.get("goal")),
                                 forecast=[names.get(n) for n in p.get("forecast") or []])
                            for p in snap["pets"] if p.get("stage") or p.get("egg")]
            told["eggs"] = snap.get("eggs")
        return told

    def lives(self, pet):
        """The lives to show. Those of the Game Boy game come from the history, where each of
        its three places is kept; the chronicle of the tab follows the first place only."""
        if pet.model.game != "gameboy":
            return pet.lives
        now = time.time()
        return [{"began": life["began"], "ended": life["ended"], "end": life["ending"],
                 "name": life["name"],
                 "stages": [[s["character"], s["name"], s["id"] if s["picture"] else None] for s in life["stages"]],
                 "days": round(((life["ended"] or now) - life["began"]) / 86400, 1)}
                for life in reversed(self.app.history.lives(pet.id, 60)) if life["began"]]

    def watch(self, pet):
        """The picture of one pet as it changes, PUBLIC_RATE times a second at most."""
        cls = PublicHandler
        with cls.counting:
            if cls.viewers >= PUBLIC_VIEWERS:
                return self.send_body(503, b"too many viewers", "text/plain", [("Retry-After", "60")])
            cls.viewers += 1
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.connection.settimeout(30)
            sent, lives_sent, quiet, began = None, None, 0.0, time.monotonic()
            looked_up, lives_now = -1000.0, None
            # the Game Boy's picture is forty times the size of a Tamagotchi's and always moving
            rate = PUBLIC_RATE_GAMEBOY if pet.model.game == "gameboy" else PUBLIC_RATE
            woke = 0.0
            while pet.alive and pet.id in self.app.pets and time.monotonic() - began < PUBLIC_LONGEST:
                if time.monotonic() - woke > PUBLIC_WAKE:
                    # A screen saver (the Morino has one) is taken away for the one who looks.
                    # That is all a viewer can cause: the pet does it only when there is one.
                    woke = time.monotonic()
                    pet.send("wake")
                msg = self.told(pet)
                if time.monotonic() - looked_up > 20:       # (the history is not asked every time)
                    looked_up, lives_now = time.monotonic(), self.lives(pet)
                lives = lives_now
                if msg != sent or lives != lives_sent:
                    out = dict(msg)
                    if lives != lives_sent:
                        out["lives"] = lives
                    sent, lives_sent, quiet = msg, lives, 0.0
                    self.wfile.write(b"data: " + json.dumps(out).encode() + b"\n\n")
                    self.wfile.flush()
                elif quiet >= 15:
                    quiet = 0.0
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                time.sleep(1 / rate)
                quiet += 1 / rate
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            with cls.counting:
                cls.viewers -= 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (0.0.0.0 for the whole network)")
    ap.add_argument("--port", type=int, default=8137)
    ap.add_argument("--public-port", type=int, default=int(os.environ.get("PUBLIC_PORT", 0)),
                    help="auf diesem Port zusätzlich die Seite für alle: nur ansehen (aus: 0)")
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
    threading.Thread(target=app.digest_clock, daemon=True).start()
    ThreadingHTTPServer.daemon_threads = True
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    if args.public_port:
        PublicHandler.app = app
        public = ThreadingHTTPServer((args.host, args.public_port), PublicHandler)
        threading.Thread(target=public.serve_forever, daemon=True).start()
        print("Die Seite für alle (nur ansehen) auf http://%s:%d" % (args.host, args.public_port),
              flush=True)
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
