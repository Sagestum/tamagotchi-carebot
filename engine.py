"""One pet: the emulator loop and its Care-Bot, running in a process of its own.

TamaLIB keeps the whole machine in global variables, so a process can hold
only one Tamagotchi. server.py starts one of these per pet and talks to it
through a pipe: commands go in, pictures of the state come out.
"""
import base64
import collections
import json
import uuid
import os
import signal
import random
import threading
import time

import models
from carebot import CareBot
from carebot_mothra import MothraBot
from carebot_gameboy import GameBoyBot
from carebot_pikachu import PikachuBot
from carebot_digimon import DigimonBot
from carebot_plain import PlainBot
from carebot_yasashii import YasashiiBot
from carebot_tamaotch import TamaotchBot
from carebot_umino import UminoBot
from report import DailyReport
from pika import Pika
from gameboy import GameBoy
from tama import BTN_A, BTN_B, BTN_C, BTN_TAP, LCD_H, LCD_W, TICK_HZ, Tama

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "libtama.so")

CHUNK = 1024                    # ticks per emulation slice (1/32 s)
FRAME = 1 / 30                  # seconds between screen updates
SPEEDS = (1, 2, 5, 20, 0)       # 0 = as fast as possible
MIN_HOLD = int(0.1 * TICK_HZ)   # shortest button press the ROM reliably sees
STUCK = 30                      # emulated seconds after which a key that is still down is let go
HANDS_OFF = 60                  # real seconds the bot waits after the user's last input
SHOT_AFTER = 20                 # emulated seconds a character is given before its picture is taken
GONE_AFTER = 60                 # emulated seconds without a character until a life counts as over
LIVES_KEPT = 300                # the chronicle forgets what is older
STATS = ("hunger", "happy", "poop", "cleaned", "sick")     # counted for every life
# K, H, S, F: the inputs K10 to K13, the Yasashii's buttons for cleaning, the heart, play and food
BUTTONS = {"A": BTN_A, "B": BTN_B, "C": BTN_C, "T": BTN_TAP, "K": 4, "H": 5, "S": 6, "F": 7,
           # the Pocket Pikachu's control pad and its two small keys (T is its pendulum)
           "up": 8, "down": 9, "left": 10, "right": 11, "start": 12, "select": 13}
FLIP = 12       # hours: the clock of a pet whose day and night change places
WATCHED_FOR = 30                # real seconds the Game Boy stays on after the last look at it
COMMANDS = ("button", "icon", "configure", "reset", "test_mail", "set_smtp", "spar", "wake", "watched",
            "report_now", "note", "duel_word", "duel_host", "duel_guest", "place")


class Engine:
    def __init__(self, rom_path, state_path, smtp, model, name, emit):
        self.state_path = state_path
        self.model = model
        # called with (snapshot, sound, log or None, chronicle or None) when the picture changes
        self.emit = emit
        self.lock = threading.Lock()
        self.tama = {"pikachu": Pika, "gameboy": GameBoy}.get(model.game, Tama)(rom_path, LIB)
        self.log = collections.deque(maxlen=60)
        self.log_id = 0
        self.log_sent = -1
        self.report = DailyReport(self.add_log, smtp, name)
        self.report.unit = model.unit
        self.tama.icon_pins = model.icon_pins
        self.tama.lcd = model.lcd
        bot = {"ocean": UminoBot, "mothra": MothraBot, "tamaotch": TamaotchBot,
               "digimon": DigimonBot, "yasashii": YasashiiBot,
               "pikachu": PikachuBot, "gameboy": GameBoyBot}.get(model.game, CareBot)
        self.bot = bot(self.tama, self.add_log, model=model)
        self.bot.reborn = self.begun_again
        self.report.rows = getattr(self.bot, "report_rows", None)
        self.flip = False       # day and night change places, from the next egg on
        # The Game Boy without its bot: left alone the pet in the game would starve, an hour
        # of its day takes two minutes. So it then only runs while someone has its page open
        # (the server says so), and stands still else.
        self.watched_until = 0.0
        self.tell = lambda *msg: None       # sends a message to the server (set by the worker)
        self.shuffle = False    # a life the bot begins itself gets another goal, drawn by lot
        self.slices = 0
        # The chronicle: every life this shell has seen, the present one last.
        # {"began", "ended": real time or None, "seconds": emulated ones lived,
        #  "stages": [[character, name]], "end": how it ended,
        #  "stats": hearts filled, droppings, flushes and illnesses on the way}
        self.lives = []
        self.lives_id = 0       # goes up whenever the chronicle reads differently
        self.lives_sent = -1
        self.outbox = []        # for the history: what the server is to write down
        self.tracks = {}        # place -> the life there that the history knows of
        self.album_seen = []    # Game Boy: the entries of the game's album already told
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
        self.outbox.append(("log", time.time(), msg))

    # -- history -----------------------------------------------------------
    # What goes into the history for good (history.py): the log, and of every place the life
    # that is lived there. The server writes it; here it is only told, a second's worth at a
    # time (outbox).

    def track(self, place, st, goal):
        """Called once per emulated second with what a place holds: note where a life
        begins, what it becomes and where it ends."""
        life = self.tracks.setdefault(str(place), {"key": None, "stage": 0, "gone": 0, "left": False})
        now, stage = time.time(), st["stage"]
        if st["dead"]:
            self.finish(place, "gestorben")
            return
        if stage == 0:
            life["gone"] += 1
            if life["gone"] == GONE_AFTER:
                self.finish(place, "verabschiedet" if life["left"] else "neu begonnen")
            return
        life["gone"], life["left"] = 0, bool(st.get("leaving"))
        label = [st.get("petName") or None, goal]
        if life["key"] is not None and life["stage"] == stage:
            if life.get("label") != label:      # named, or given another goal, meanwhile
                life["label"] = label
                self.outbox.append(("label", life["key"], label[0], goal))
            return
        life["label"] = label
        if life["key"] is None:
            life["key"] = uuid.uuid4().hex
            self.outbox.append(("begin", life["key"], now, place, st.get("petName") or None, goal))
        life["stage"], life["since"], life["shot"] = stage, self.tama.seconds, False
        data = {k: st[k] for k in ("hunger", "happy", "weight", "age", "mistakes", "missed", "training",
                                   "fear", "mine", "iq", "body", "deed") if st.get(k) is not None}
        self.outbox.append(("stage", life["key"], now, stage, self.model.names.get(stage, "Stufe %d" % stage),
                            st.get("petName") or None, goal, data))

    def finish(self, place, how):
        life = self.tracks.get(str(place))
        if life and life["key"] is not None:
            self.outbox.append(("end", life["key"], time.time(), how))
            life["key"], life["stage"] = None, 0

    def track_all(self, status):
        names = self.model.names
        if hasattr(self.bot, "pets"):       # the Game Boy: three places, each with its goal
            for place in range(3):
                self.track(place, self.bot.status(place), names.get(self.bot.goals[place]))
                # a picture of each character for the history, once it can be seen at ease
                life = self.tracks[str(place)]
                if life["key"] is not None and not life.get("shot") and self.bot.in_view(place) \
                        and self.tama.seconds - life.get("since", 0) >= SHOT_AFTER:
                    packed = self.tama.packed()
                    if packed:
                        life["shot"] = True
                        self.outbox.append(("picture", life["key"], life["stage"], packed))
            # and what the game remembers by itself: a new entry of its album is told once
            album = [[a["place"], a["name"], a["character"], a["age"], a["weight"]] for a in self.bot.album()]
            if album != self.album_seen:
                fresh = [a for a in self.bot.album()
                         if [a["place"], a["name"], a["character"], a["age"], a["weight"]] not in self.album_seen]
                # with a picture of the game's own page of it; while the bot holds a key that
                # has to wait for the next look
                if not fresh or self.bot.held is None:
                    self.album_seen = album
                    if fresh:
                        self.outbox.append(("album", time.time(), fresh, self.bot.memory_picture()))
        else:
            self.track(0, status, names.get(self.bot.goal))

    # -- persistence -------------------------------------------------------

    def load_state(self):
        try:
            with open(self.state_path) as f:
                data = json.load(f)
        except FileNotFoundError:
            self.add_log("Eingeschaltet" if self.model.game == "gameboy" else "Neues Ei")
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
        self.shuffle = data.get("shuffle", False)
        self.flip = data.get("flip", False)
        self.bot.shift = FLIP if data.get("flipped") else 0
        self.bot.goal = data.get("goal") if data.get("goal") in self.model.growth.GOALS else None
        self.bot.generation = data.get("generation", 1)
        self.bot.recall(data.get("memo"))
        self.speed = data.get("speed", 1) if data.get("speed", 1) in SPEEDS else 1
        self.report.from_dict(data.get("report", {}))
        self.lives = data.get("lives", [])
        self.tracks = data.get("tracks", {})
        self.album_seen = data.get("album", [])
        if not data.get("history"):
            # A state from before the history: hand over what the chronicle holds. The life
            # that is still going on is taken up where it stands.
            self.outbox.append(("old", [life for life in self.lives if life["ended"] is not None]))
            if self.lives and self.lives[-1]["ended"] is None and self.lives[-1]["stages"]:
                life, key = self.lives[-1], uuid.uuid4().hex
                self.outbox.append(("begin", key, life["began"], 0, None, None))
                for stage, name in life["stages"]:
                    self.outbox.append(("stage", key, None, stage, name, None, None, None))
                self.tracks = {"0": {"key": key, "stage": life["stages"][-1][0], "gone": 0, "left": False}}
        self.add_log("Spielstand geladen")

    def save_state(self):
        with self.lock:
            data = {
                "rom": self.model.id,
                "cpu": base64.b64encode(self.tama.save()).decode(),
                "bot": self.bot_enabled,
                "discipline": self.bot.discipline,
                "restart": self.bot.restart,
                "shuffle": self.shuffle,
                "flip": self.flip,
                "flipped": self.bot.shift != 0,
                "goal": self.bot.goal,
                "generation": self.bot.generation,
                "memo": self.bot.memo(),
                "speed": self.speed,
                "report": self.report.to_dict(),
                "lives": self.lives,
                "tracks": self.tracks,
                "album": self.album_seen,
                "history": True,        # the lives from before the history have been handed over
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
            self.watched_until = time.monotonic() + WATCHED_FOR
            self.take_over()
            now = self.tama.ticks
            if btn == BTN_TAP and self.model.rattle:
                # A sensor for knocks and noise: it takes a rattle, not a single tap
                if down:
                    pulse = self.model.rattle_ticks
                    for _ in range(self.model.rattle):
                        self.tama.button(btn, True)
                        self.tama.run(pulse)
                        self.tama.button(btn, False)
                        self.tama.run(pulse)
                return
            if down:
                self.tama.button(btn, True)
                self.pressed[btn] = now
                self.release.pop(btn, None)
            elif btn in self.pressed:
                hold = max(MIN_HOLD, int(self.model.hold * TICK_HZ))
                self.release[btn] = max(now, self.pressed[btn] + hold)

    def icon(self, index):
        with self.lock:
            self.take_over()
            self.bot.request(index)

    def watched(self):
        """Someone has the page of this pet open."""
        with self.lock:
            self.watched_until = time.monotonic() + WATCHED_FOR

    def wake(self):
        """Someone looks at the pet: a press of A takes the screen saver away (the Morino
        has one; there A does nothing else). Not while the bot or the user is at work."""
        with self.lock:
            self.watched_until = time.monotonic() + WATCHED_FOR
            if self.pressed or getattr(self.bot, "task", None) is not None \
                    or not self.bot.status().get("saver"):
                return
            now = self.tama.ticks
            self.tama.button(BTN_A, True)
            self.pressed[BTN_A] = now
            self.release[BTN_A] = now + int(max(self.model.hold, 0.2) * TICK_HZ)

    def spar(self):
        """Digimon: a fight against an opponent that is not there."""
        with self.lock:
            if hasattr(self.bot, "request_spar"):
                self.take_over()
                self.bot.request_spar()

    # A fight between two Digimon of the user's: the server carries the words from one to the
    # other in three steps (carebot_digimon.py). What a step has found goes back with tell.

    def duel_word(self):
        with self.lock:
            self.take_over()
            self.bot.request(self.bot.duel_word(lambda word: self.tell("duel", word)))

    def duel_host(self, about, name):
        with self.lock:
            self.take_over()
            self.bot.request(self.bot.duel_host(about, name, lambda words: self.tell("duel", words)))

    def duel_guest(self, about, outcome, name):
        with self.lock:
            self.take_over()
            self.bot.request(self.bot.duel_guest(about, outcome, name))

    def place(self, what, slot=0, goal=None):
        """Game Boy: bring the pet of one of the three places onto the screen ("show"), or
        take a new egg ("egg"), or say what a place is to raise ("goal": a character, None, or -1
        for one drawn by lot with every egg)."""
        with self.lock:
            if not hasattr(self.bot, "show"):
                return
            if what == "show" and slot in range(3):
                self.take_over()
                self.bot.request(self.bot.show(slot))
            elif what == "egg":
                self.take_over()
                self.bot.request(self.bot.begin())
            elif what == "goal" and slot in range(3):
                self.bot.wish(slot, goal)
                self.add_log("Platz %d, Ziel: %s" % (slot + 1, "zufällig" if goal == -1
                                                     else self.model.names[goal] if goal else "keins"))

    def configure(self, bot=None, discipline=None, speed=None, paused=None, goal=False,
                  restart=None, shuffle=None, flip=None, keep=None, pace=None):
        with self.lock:
            if keep in (1, 2, 3) and hasattr(self.bot, "keep") and keep != self.bot.keep:
                self.bot.keep = keep
                self.add_log("Der Bot hält %s" % ("ein Tier" if keep == 1 else "%d Tiere zugleich" % keep))
            if pace in (0, 1, 2) and hasattr(self.bot, "pace") and pace != self.bot.pace:
                self.bot.pace = pace
                self.bot.set_pace()
                self.add_log("Die Zeit im Spiel läuft jetzt %s" % self.bot.PACES[pace])
            if bot is not None and bool(bot) != self.bot_enabled:
                self.bot_enabled = bool(bot)
                self.hands_off = None
                self.bot.stop()
                self.add_log("Care-Bot an" if self.bot_enabled else "Care-Bot aus")
            if discipline is not None:
                self.bot.discipline = bool(discipline)
            if restart is not None:
                self.bot.restart = bool(restart)
            if shuffle is not None:
                self.shuffle = bool(shuffle)
            if flip is not None and bool(flip) != self.flip:
                self.flip = bool(flip)
                self.add_log("Zeitumkehrer %s: gilt ab dem nächsten Ei" % ("an" if self.flip else "aus"))
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
            for place in list(self.tracks):
                self.finish(place, "neu begonnen")
            self.end_life("neu begonnen")
            self.bot.stop()
            self.bot.clock_set_at = None
            self.bot.gone = False
            self.bot.generation = 1
            self.tama.reset()
            self.reborn()
            self.add_log("Aus- und eingeschaltet" if self.model.game == "gameboy" else "Neues Ei")

    def reborn(self):
        """A new life has begun: the day's counters belong to the one before."""
        self.end_life("neu begonnen")
        self.bot.shift = FLIP if self.flip else 0     # the clock of the new one is set by it
        self.report.reset_counters()
        self.report.asleep = False

    def programmes(self):
        """The goals that take more than one life (Lucky Unchi-Kun, Mothra's twins): the bot
        begins the next life itself then."""
        rules = self.model.growth
        more = getattr(rules, "GENERATIONS", ())
        return [g for g in (getattr(rules, "LUCKY", None),) + (more if isinstance(more, tuple) else ())
                if g is not None]

    def begun_again(self):
        """The bot has begun a new life itself. If asked to, it raises another character
        this time: any goal but the last one and but what the last life became.
        A programme over several lives (Lucky Unchi-Kun, Mothra's twins) is left alone."""
        last = self.lives[-1]["stages"][-1][0] if self.lives and self.lives[-1]["stages"] else None
        self.reborn()
        long = self.programmes()
        if not (self.shuffle and self.bot.restart and self.model.goals) or self.bot.goal in long:
            return
        pool = [g for g in self.model.growth.GOALS if g not in long and g not in (self.bot.goal, last)]
        if pool:
            self.bot.goal = random.choice(pool)
            self.bot.generation = 1
            self.add_log("Ziel ausgelost: " + self.model.names[self.bot.goal])

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
                self.report.send(self.bot.status(), direct=True)

    def report_now(self):
        """For the gathered mail: how the day has been so far (the pet has not fallen asleep
        in time). The counters go on until it does."""
        with self.lock:
            if self.report.hand_over:
                self.report.hand_over(dict(self.report.section(self.bot.status()), late=True))

    def note(self, msg):
        with self.lock:
            self.add_log(msg)

    # -- emulation loop ----------------------------------------------------

    def slice(self):
        tama = self.tama
        tama.run(CHUNK)
        now = tama.ticks
        for btn, at in self.pressed.items():
            # a key whose release never came (the page closed with it down, a finger slid off
            # it): it is let go, or the bot would wait for the user for ever
            if btn not in self.release and now - at > STUCK * TICK_HZ:
                self.release[btn] = now
        for btn, at in list(self.release.items()):
            if now >= at:
                tama.button(btn, False)
                del self.release[btn]
                del self.pressed[btn]
        if self.hands_off is not None and time.monotonic() >= self.hands_off \
                and not self.pressed and not self.bot.manual:   # what was asked for is finished first
            self.hands_off = None
            self.bot.resume()
        if self.bot.manual or (self.bot_enabled and self.hands_off is None):
            self.bot.step()
        self.slices += 1
        if self.slices % 32 == 0:   # once per emulated second
            status = self.bot.status()
            # (the Game Boy's chronicle follows its first place; all three are in the history)
            self.chronicle(self.bot.status(0) if hasattr(self.bot, "pets") else status)
            self.track_all(status)
            if self.outbox:
                self.tell("history", self.outbox)
                self.outbox = []
            pixels, icons = tama.frame()
            if self.model.game == "pikachu":
                # its picture is the dot matrix, while it shows Pikachu and no menu
                pixels = tama.dots() if status["screen"] == 0 else None
            self.report.observe(status, pixels, icons, now)

    def unwatched(self, now):
        """The Game Boy with its bot switched off and nobody at its page: it stands still."""
        return self.model.game == "gameboy" and not self.bot_enabled and now >= self.watched_until

    def publish(self):
        tama = self.tama
        pixels, icons = tama.frame()
        rows = []
        if self.model.game == "pikachu":
            # its LCD memory as it is; nothing while the display is switched off
            rows.append((tama.lcd_memory() or b"").hex())
        elif self.model.game == "gameboy":
            # the Game Boy's picture, four dots to a byte; nothing while the display is off
            rows.append(base64.b64encode(tama.packed()).decode())
        else:
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
            "chart": self.bot.chart() if hasattr(self.bot, "chart") else None,
            "bot": self.bot_enabled,
            "handsOff": self.hands_off is not None,
            "discipline": self.bot.discipline,
            "restart": self.bot.restart,
            "shuffle": self.shuffle,
            "programme": self.bot.goal in self.programmes(),
            "flip": self.flip,
            "flipped": self.bot.shift != 0,
            "goal": self.bot.goal,
            "goalName": self.model.names.get(self.bot.goal),
            "pets": self.bot.pets() if hasattr(self.bot, "pets") else None,
            "keep": getattr(self.bot, "keep", None),
            "pace": getattr(self.bot, "pace", None),
            "eggs": self.bot.eggs_left() if hasattr(self.bot, "eggs_left") else None,
            "speed": self.speed,
            "paused": self.paused,
            "idle": self.unwatched(time.monotonic()),
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
                if self.unwatched(start):
                    owed = 0.0          # nobody looks: it stands still
                elif not self.paused:
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

    sending = threading.Lock()      # the loop and the commands both write to the server

    def tell(*msg):
        try:
            with sending:
                conn.send(msg)
        except (BrokenPipeError, OSError):
            engine.running = False

    def emit(snap, sound, log, lives):
        tell("snap", snap, sound, log, lives)

    try:
        engine = Engine(rom_path, state_path, smtp, models.BY_ID[model_id], name, emit)
    except (SystemExit, OSError, RuntimeError, ValueError, KeyError) as e:
        conn.send(("error", str(e)))
        return
    signal.signal(signal.SIGTERM, lambda *_: setattr(engine, "running", False))
    engine.report.hand_over = lambda section: tell("report", section)
    engine.tell = tell

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
