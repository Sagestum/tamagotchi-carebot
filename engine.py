"""One pet: the emulator loop and its Care-Bot, running in a process of its own.

TamaLIB keeps the whole machine in global variables, so a process can hold
only one Tamagotchi. server.py starts one of these per pet and talks to it
through a pipe: commands go in, pictures of the state come out.
"""
import base64
import collections
import json
import os
import signal
import threading
import time

import models
from carebot import CareBot
from report import DailyReport
from tama import BTN_A, BTN_B, BTN_C, BTN_TAP, LCD_H, LCD_W, TICK_HZ, Tama

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libtama.so")

CHUNK = 1024                    # ticks per emulation slice (1/32 s)
FRAME = 1 / 30                  # seconds between screen updates
SPEEDS = (1, 2, 5, 20, 0)       # 0 = as fast as possible
MIN_HOLD = int(0.1 * TICK_HZ)   # shortest button press the ROM reliably sees
HANDS_OFF = 60                  # real seconds the bot waits after the user's last input
BUTTONS = {"A": BTN_A, "B": BTN_B, "C": BTN_C, "T": BTN_TAP}
COMMANDS = ("button", "icon", "configure", "reset", "test_mail", "set_smtp")


class Engine:
    def __init__(self, rom_path, state_path, smtp, model, name, emit):
        self.state_path = state_path
        self.model = model
        self.emit = emit        # called with (snapshot, sound, log or None) when the picture changes
        self.lock = threading.Lock()
        self.tama = Tama(rom_path, LIB)
        self.log = collections.deque(maxlen=60)
        self.log_id = 0
        self.log_sent = -1
        self.report = DailyReport(self.add_log, smtp, name)
        self.bot = CareBot(self.tama, self.add_log, model=model)
        self.slices = 0
        self.bot_enabled = True
        self.hands_off = None   # time.monotonic() until which the user has the buttons
        self.speed = 1
        self.paused = False
        self.pressed = {}       # btn -> tick of the press
        self.release = {}       # btn -> tick at which to let go
        self.sound = []
        self.snapshot = None
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
        if data.get("rom", models.P1.id) != self.model.id:
            # Another ROM would wake up in the middle of this pet's memory
            raise SystemExit("%s gehört zu einer anderen ROM (%s, geladen ist %s). "
                             "Mit --state einen eigenen Spielstand angeben."
                             % (self.state_path, data.get("rom", models.P1.id), self.model.id))
        if not self.tama.load(base64.b64decode(data["cpu"])):
            raise SystemExit("%s is not a usable state file" % self.state_path)
        self.bot_enabled = data.get("bot", True)
        self.bot.discipline = data.get("discipline", True)
        self.bot.goal = data.get("goal") if data.get("goal") in self.model.growth.GOALS else None
        self.bot.generation = data.get("generation", 1)
        self.speed = data.get("speed", 1) if data.get("speed", 1) in SPEEDS else 1
        self.report.from_dict(data.get("report", {}))
        self.add_log("Spielstand geladen")

    def save_state(self):
        with self.lock:
            data = {
                "rom": self.model.id,
                "cpu": base64.b64encode(self.tama.save()).decode(),
                "bot": self.bot_enabled,
                "discipline": self.bot.discipline,
                "goal": self.bot.goal,
                "generation": self.bot.generation,
                "speed": self.speed,
                "report": self.report.to_dict(),
            }
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.state_path)

    # -- commands from the web UI -----------------------------------------

    def take_over(self):
        """The user is at the buttons: the bot lets go and waits (call with the lock)."""
        self.bot.stop()
        if self.bot_enabled and self.model.care:
            self.hands_off = time.monotonic() + HANDS_OFF

    def button(self, name, down):
        btn = BUTTONS[name]
        with self.lock:
            self.take_over()
            now = self.tama.ticks
            if down:
                self.tama.button(btn, True)
                self.pressed[btn] = now
                self.release.pop(btn, None)
            elif btn in self.pressed:
                self.release[btn] = max(now, self.pressed[btn] + MIN_HOLD)

    def icon(self, index):
        with self.lock:
            self.take_over()
            self.bot.request(index)

    def configure(self, bot=None, discipline=None, speed=None, paused=None, goal=False):
        with self.lock:
            if bot is not None and bool(bot) != self.bot_enabled:
                self.bot_enabled = bool(bot)
                self.hands_off = None
                self.bot.stop()
                self.add_log("Care-Bot an" if self.bot_enabled else "Care-Bot aus")
            if discipline is not None:
                self.bot.discipline = bool(discipline)
            if (goal is None or goal in self.model.growth.GOALS) and goal != self.bot.goal:
                self.bot.goal = goal
                self.bot.generation = 1         # a programme over generations starts anew
                self.add_log("Ziel: " + (self.model.names[goal] if goal else "keins"))
            if speed in SPEEDS:
                self.speed = speed
                self.bot.realtime = speed == 1
            if paused is not None:
                self.paused = bool(paused)

    def reset(self):
        with self.lock:
            self.bot.stop()
            self.bot.clock_set_at = None
            self.bot.gone = False
            self.bot.generation = 1
            self.tama.reset()
            self.report.reset_counters()
            self.report.asleep = False
            self.add_log("Neues Ei")

    def set_smtp(self, smtp):
        with self.lock:
            self.report.configure(smtp)

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
        if self.hands_off is not None and time.monotonic() >= self.hands_off \
                and not self.pressed:
            self.hands_off = None
            self.bot.resume()
        if self.bot.manual or (self.bot_enabled and self.hands_off is None):
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
            "model": self.model.id,
            "care": self.model.care,
            "goals": self.model.goals,
            "tap": self.model.tap,
            "unit": self.model.unit,
            "menu": self.model.icons,
            "lcd": "".join(rows),
            "icons": sum(1 << i for i, v in enumerate(icons) if v),
            "status": status,
            "growth": self.bot.growth(status),
            "bot": self.bot_enabled,
            "handsOff": self.hands_off is not None,
            "discipline": self.bot.discipline,
            "goal": self.bot.goal,
            "goalName": self.model.names.get(self.bot.goal),
            "speed": self.speed,
            "paused": self.paused,
            "logId": self.log_id,
        }
        if sound or snap != self.snapshot:
            self.snapshot = snap
            log = None
            if self.log_id != self.log_sent:
                self.log_sent = self.log_id
                log = [[when, text] for _, when, text in self.log]
            self.emit(snap, sound, log)

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


def run(conn, rom_path, state_path, smtp, model_id, name):
    """The life of a worker process. Ends when told to stop or when the server is gone."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)    # Ctrl+C reaches us too: the server decides

    def emit(snap, sound, log):
        try:
            conn.send(("snap", snap, sound, log))
        except (BrokenPipeError, OSError):
            engine.running = False

    try:
        engine = Engine(rom_path, state_path, smtp, models.BY_ID[model_id], name, emit)
    except (SystemExit, OSError, RuntimeError, ValueError, KeyError) as e:
        conn.send(("error", str(e)))
        return
    signal.signal(signal.SIGTERM, lambda *_: setattr(engine, "running", False))

    def commands():
        while True:
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                break
            if msg[0] not in COMMANDS:      # "stop"
                break
            try:
                getattr(engine, msg[0])(*msg[1:])
            except (KeyError, ValueError, TypeError):
                pass                        # a malformed request from the web
        engine.running = False

    threading.Thread(target=commands, daemon=True).start()
    engine.loop()
    engine.save_state()
