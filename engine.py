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
from carebot_mothra import MothraBot
from carebot_umino import UminoBot
from report import DailyReport
from tama import BTN_A, BTN_B, BTN_C, BTN_TAP, LCD_H, LCD_W, TICK_HZ, Tama

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libtama.so")

CHUNK = 1024                    # ticks per emulation slice (1/32 s)
FRAME = 1 / 30                  # seconds between screen updates
SPEEDS = (1, 2, 5, 20, 0)       # 0 = as fast as possible
MIN_HOLD = int(0.1 * TICK_HZ)   # shortest button press the ROM reliably sees
HANDS_OFF = 60                  # real seconds the bot waits after the user's last input
GONE_AFTER = 60                 # emulated seconds without a character until a life counts as over
LIVES_KEPT = 300                # the chronicle forgets what is older
STATS = ("hunger", "happy", "poop", "cleaned", "sick")     # counted for every life
BUTTONS = {"A": BTN_A, "B": BTN_B, "C": BTN_C, "T": BTN_TAP}
COMMANDS = ("button", "icon", "configure", "reset", "test_mail", "set_smtp")


class Engine:
    def __init__(self, rom_path, state_path, smtp, model, name, emit):
        self.state_path = state_path
        self.model = model
        # called with (snapshot, sound, log or None, chronicle or None) when the picture changes
        self.emit = emit
        self.lock = threading.Lock()
        self.tama = Tama(rom_path, LIB)
        self.log = collections.deque(maxlen=60)
        self.log_id = 0
        self.log_sent = -1
        self.report = DailyReport(self.add_log, smtp, name)
        self.tama.icon_pins = model.icon_pins
        bot = {"ocean": UminoBot, "mothra": MothraBot}.get(model.game, CareBot)
        self.bot = bot(self.tama, self.add_log, model=model)
        self.bot.reborn = self.reborn
        self.slices = 0
        # The chronicle: every life this shell has seen, the present one last.
        # {"began", "ended": real time or None, "seconds": emulated ones lived,
        #  "stages": [[character, name]], "end": how it ended,
        #  "stats": hearts filled, droppings, flushes and illnesses on the way}
        self.lives = []
        self.lives_id = 0       # goes up whenever the chronicle reads differently
        self.lives_sent = -1
        self.egg_for = 0        # emulated seconds without a character
        self.leaving = False    # it was taking its leave when last seen
        self.cared = None       # (hunger, happy, poop, sick) when last seen
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
        self.bot.restart = data.get("restart", False)
        self.bot.goal = data.get("goal") if data.get("goal") in self.model.growth.GOALS else None
        self.bot.generation = data.get("generation", 1)
        self.bot.recall(data.get("memo"))
        self.speed = data.get("speed", 1) if data.get("speed", 1) in SPEEDS else 1
        self.report.from_dict(data.get("report", {}))
        self.lives = data.get("lives", [])
        self.add_log("Spielstand geladen")

    def save_state(self):
        with self.lock:
            data = {
                "rom": self.model.id,
                "cpu": base64.b64encode(self.tama.save()).decode(),
                "bot": self.bot_enabled,
                "discipline": self.bot.discipline,
                "restart": self.bot.restart,
                "goal": self.bot.goal,
                "generation": self.bot.generation,
                "memo": self.bot.memo(),
                "speed": self.speed,
                "report": self.report.to_dict(),
                "lives": self.lives,
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

    def configure(self, bot=None, discipline=None, speed=None, paused=None, goal=False,
                  restart=None):
        with self.lock:
            if bot is not None and bool(bot) != self.bot_enabled:
                self.bot_enabled = bool(bot)
                self.hands_off = None
                self.bot.stop()
                self.add_log("Care-Bot an" if self.bot_enabled else "Care-Bot aus")
            if discipline is not None:
                self.bot.discipline = bool(discipline)
            if restart is not None:
                self.bot.restart = bool(restart)
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
            self.end_life("neu begonnen")
            self.bot.stop()
            self.bot.clock_set_at = None
            self.bot.gone = False
            self.bot.generation = 1
            self.tama.reset()
            self.reborn()
            self.add_log("Neues Ei")

    def reborn(self):
        """A new life has begun: the day's counters belong to the one before."""
        self.end_life("neu begonnen")
        self.report.reset_counters()
        self.report.asleep = False

    # -- chronicle ---------------------------------------------------------

    def end_life(self, how):
        if self.lives and self.lives[-1]["ended"] is None:
            self.lives[-1]["ended"] = time.time()
            self.lives[-1]["end"] = "verabschiedet" if self.leaving and how != "gestorben" else how
            self.lives_id += 1
        self.leaving = False
        self.cared = None

    def chronicle(self, status):
        """Called once per emulated second: note what the pet is and whether it still is."""
        stage = status["stage"]
        life = self.lives[-1] if self.lives and self.lives[-1]["ended"] is None else None
        if status["dead"]:
            self.end_life("gestorben")
            return
        if stage == 0:
            # No character: an egg, or the next generation is on its way. (A Morino reads 0
            # for a moment while something is after it, so wait a little.)
            self.egg_for += 1
            self.cared = None
            if life and self.egg_for == GONE_AFTER:
                self.end_life("neu begonnen")
            return
        self.egg_for = 0
        self.leaving = status["leaving"]
        if life is None:
            life = {"began": time.time(), "ended": None, "seconds": 0, "stages": [], "end": None,
                    "stats": dict.fromkeys(STATS, 0)}
            self.lives.append(life)
            del self.lives[:-LIVES_KEPT]
            self.lives_id += 1
        life["seconds"] += 1
        if life["seconds"] % 8640 == 0:     # the days are told in tenths
            self.lives_id += 1
        if not life["stages"] or life["stages"][-1][0] != stage:
            life["stages"].append([stage, self.model.names.get(stage, "Stufe %d" % stage)])
            self.lives_id += 1
        # What it took to get here; a life from before these were counted has no "stats"
        now = (status["hunger"], status["happy"], status["poop"], bool(status["sick"]))
        stats, before = life.get("stats"), self.cared
        self.cared = now
        if stats is None or before is None or now == before:
            return
        stats["hunger"] += max(0, now[0] - before[0])
        stats["happy"] += max(0, now[1] - before[1])
        stats["poop"] += max(0, now[2] - before[2])
        stats["cleaned"] += now[2] < before[2]
        stats["sick"] += now[3] and not before[3]
        self.lives_id += 1

    def lives_told(self):
        """The chronicle for the web UI."""
        return [{"began": life["began"], "ended": life["ended"], "end": life["end"],
                 "days": round(life["seconds"] / 86400, 1),
                 "stages": life["stages"], "stats": life.get("stats")} for life in self.lives]

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
            status = self.bot.status()
            self.chronicle(status)
            self.report.observe(status, *tama.frame(), now)

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
            "restart": self.bot.restart,
            "goal": self.bot.goal,
            "goalName": self.model.names.get(self.bot.goal),
            "speed": self.speed,
            "paused": self.paused,
            "logId": self.log_id,
            "livesId": self.lives_id,
            "cycle": [len(self.lives), bool(self.lives) and self.lives[-1]["ended"] is None],
        }
        if sound or snap != self.snapshot:
            self.snapshot = snap
            log = None
            if self.log_id != self.log_sent:
                self.log_sent = self.log_id
                log = [[when, text] for _, when, text in self.log]
            lives = None
            if self.lives_id != self.lives_sent:
                self.lives_sent = self.lives_id
                lives = self.lives_told()
            self.emit(snap, sound, log, lives)

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

    def emit(snap, sound, log, lives):
        try:
            conn.send(("snap", snap, sound, log, lives))
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
