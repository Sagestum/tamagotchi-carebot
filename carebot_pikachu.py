"""Care-Bot for the Pocket Pikachu (1998), the step counter with Pikachu in it.

There is nothing to feed. It wants to be walked with and to be given the watts the walking
earns (growth_pikachu.py). So the bot swings the pendulum, two steps a second, and once a
day it gives away what has come together.

The device switches its display off after a minute. A dark display looks like a device
that has given up, so the bot switches it on again at once. With the display on it matters
when one walks: Pikachu woken at night or disturbed at play takes offence. So the bot walks
by day, from 7 to 8 in the evening, and not while Pikachu is busy.
"""
import time

import growth_pikachu as rules
from carebot import CareBot
from pika import (BTN_A, BTN_B, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_START, BTN_STEP, BTN_UP)

# RAM cells of the Pocket Pikachu ROM (read from the program, checked by experiment)
MEM_SECOND, MEM_MINUTE, MEM_HOUR, MEM_PM = 0x57, 0x58, 0x59, 0x5A   # BCD; the hour 0 to 11
MEM_STEPS = (0x64, 0x63, 0x62)          # BCD, the counter on the display
MEM_TOTAL = (0x67, 0x66, 0x65)          # BCD, the steps the friend screen shows, to 99 999
MEM_UNLOCK = 0x69                       # 0 to 3: what it has learnt by the steps
MEM_ACCOUNT = (0x6E, 0x6D)              # BCD, its affection
MEM_WALKED = 0x6F                       # watts walked today that went to the account
MEM_GIVEN = (0x71, 0x70)                # BCD, watts given today
MEM_MOOD = 0x72                         # 0 gone, 1 cross ... 4 loves you; set at 8 o'clock
MEM_WATTS = (0x74, 0x73)                # BCD, the watts to give away or to gamble with
MEM_MODE = 0x79                         # what is on the display
MEM_BED = 0x7B                          # it has gone to bed
MEM_DIGITS = (0xAE, 0xAF, 0xB0)         # gift screen: hundreds, tens and ones being dialled
MEM_CURSOR = 0xB7                       # options: 2 the counter, 3 the clock
MEM_DOING = 0xEB                        # the animation that is running
# the screen that sets the clock: what is being dialled
MEM_DIAL_FIELD, MEM_DIAL_PM, MEM_DIAL_HOUR, MEM_DIAL_MINUTE = 0x9A, 0x9B, 0x9C, 0x9D

HOME, OPTIONS, FRIEND, CLOCK, GIFT, GAME, END, DARK, SETTING, TITLE = 0, 1, 2, 3, 4, 5, 6, 7, 8, 0xA
ICON_CLOCK, ICON_GIFT, ICON_GAME = (174, 7), (171, 7), (168, 7)    # LCD bits of the three icons
# Animations in which it does not want to be disturbed (the program's own two lists)
AT_PLAY = (0x1E, 0x17, 0x4B, 0x24, 0x66, 0x28, 0x3E, 0x3F, 0x40, 0x42, 0x43, 0x44, 0x4F, 0x50, 0x1F)
DAY = range(7, 20)              # hours in which walking with the display on does not wake it
MORNING, EVENING = 8, 20        # its day begins at 8; it sleeps from 8 pm on
SPREAD = (EVENING - MORNING) * 60 - 20      # minutes over which the day's steps are spread
GIVE_FROM = 19                  # the hour from which the day's watts are given away
BOUT = 20                       # steps taken before the bot looks up again
HOLD, PAUSE = 0.15, 0.45
SWING = 0.1                     # the pendulum touches for this long
CLOCK_TOLERANCE = 90
GONE_FOR = 20                   # seconds without affection until it counts as gone


class PikachuBot(CareBot):
    def __init__(self, tama, log=print, discipline=True, feed_below=3, play_below=3, model=None):
        super().__init__(tama, log, discipline, feed_below, play_below, model)
        self.day_from = None            # the total of steps when its day began
        self.last_hour = None
        self.mood_seen = None
        self.stage_seen = None
        self.gave_at = None             # the day (its count of steps at the start) a gift went
        self.waiting = False            # held back because the display is on
        self.gone_since = None

    def memo(self):
        return {"day_from": self.day_from, "last_hour": self.last_hour, "gave_at": self.gave_at}

    def recall(self, memo):
        if isinstance(memo, dict):
            self.day_from = memo.get("day_from")
            self.last_hour = memo.get("last_hour")
            self.gave_at = memo.get("gave_at")

    # -- state readers -----------------------------------------------------

    def bcd(self, cells):
        n = 0
        for cell in cells:
            v = self.tama.memory(cell)
            n = n * 100 + (v >> 4) * 10 + (v & 15)
        return n

    def hour(self):
        m = self.tama.memory
        return self.bcd((MEM_HOUR,)) % 12 + (12 if m(MEM_PM) else 0)

    def device_time(self):
        return self.hour() * 3600 + self.bcd((MEM_MINUTE,)) * 60 + self.bcd((MEM_SECOND,))

    def clock_error(self):
        want = self.wall()
        diff = self.device_time() - (want.tm_hour * 3600 + want.tm_min * 60 + want.tm_sec)
        return (diff + 43200) % 86400 - 43200

    def today(self):
        """Steps since its day began (8 in the morning), by the counter on the display.
        (The other one, on the friend screen, ends at 99 999.)"""
        steps = self.bcd(MEM_STEPS)
        if self.day_from is None or self.day_from > steps:     # the counter has been reset
            self.day_from = steps
        return steps - self.day_from

    def status(self):
        m = self.tama.memory
        mode = m(MEM_MODE)
        begun = mode not in (TITLE, SETTING) or self.bcd(MEM_TOTAL) > 0
        steps, account = self.bcd(MEM_STEPS), self.bcd(MEM_ACCOUNT)
        stage = rules.stage(steps, m(MEM_UNLOCK)) if begun else 0
        mood = m(MEM_MOOD)
        hour = self.hour()
        return {
            "stage": stage, "name": rules.NAMES.get(stage, "Pocket Pikachu"),
            "away": False, "praying": False, "sickness": 0,
            # a million steps: it says so and stands still, clock and all, until it is reset
            "leaving": stage == 5, "thanked": mode == END,
            "generation": None,
            "hunger": 0, "happy": mood, "weight": self.bcd(MEM_WATTS),
            "poop": 0, "mistakes": 0, "age": 0, "illnesses": 0, "missed": 0, "training": 0,
            "meter": 0, "kind": 0, "sick": False, "attack": False, "cocoon": False,
            "temperature": None, "friendship": None, "sweetness": None, "look": None, "back": False,
            "asleep": bool(m(MEM_BED)) and begun, "light": True,
            "attention": False, "scold": False, "dead": False, "game": None,
            "saver": mode == DARK, "screen": mode,
            "clock": "%02d:%02d" % (hour, self.bcd((MEM_MINUTE,))),
            # what only this one has
            "steps": steps, "total": self.bcd(MEM_TOTAL), "today": self.today() if begun else 0,
            "account": account, "mood": mood, "moodName": rules.MOODS.get(mood, "?"),
            "walked": m(MEM_WALKED), "given": self.bcd(MEM_GIVEN),
            "perDay": rules.a_day(self.goal), "held": self.waiting,
        }

    def growth(self, st):
        """For the page of the bot: what each way of walking brings a day and how long
        things take with it."""
        ways = []
        for goal in (None,) + rules.GOALS:
            walked, given, lost = rules.balance(goal)
            ways.append({
                "goal": goal, "name": rules.NAMES.get(goal, "Ohne Ziel"),
                "perDay": rules.a_day(goal), "walked": walked, "given": given, "lost": lost,
                "moods": [[mood, rules.MOODS[mood], frm, rules.days_to(st["account"], frm, goal)]
                          for mood, frm in sorted(rules.MOOD_FROM.items()) if mood > 1],
                "full": rules.days_to(st["account"], rules.MOST, goal),
                "unlocks": [[n, rules.days_to_steps(st["steps"], n, goal)]
                            for n in rules.UNLOCKS + (rules.LAST,)],
            })
        return {"forecast": [], "reachable": list(rules.GOALS), "plan": None, "wanted": None,
                "ways": ways}

    def report_rows(self, st, stats):
        """The daily report: this one has neither hearts nor weight."""
        return [
            ("Ins Bett gegangen", stats["slept"] or "–"),
            ("Schritte heute", "{:,}".format(st["today"]).replace(",", ".")),
            ("Schritte auf dem Zähler", "{:,}".format(st["steps"]).replace(",", ".")),
            ("Watt", "%d, heute verschenkt %d" % (st["weight"], st["given"])),
            ("Zuneigung", "%s (Konto %d von %d)" % (st["moodName"], st["account"], rules.MOST)),
        ]

    # -- primitives ---------------------------------------------------------

    def press(self, btn, pause=PAUSE):
        self.held = btn
        self.tama.button(btn, True)
        yield HOLD
        self.tama.button(btn, False)
        self.held = None
        yield pause

    def home(self):
        """To Pikachu's own screen, with the display on."""
        m = self.tama.memory
        for _ in range(6):
            if m(MEM_MODE) == HOME:
                return
            if m(MEM_MODE) in (TITLE, SETTING, END):
                return
            # A switches the dark display on and does nothing else then
            yield from self.press(BTN_A if m(MEM_MODE) == DARK else BTN_B, 1.5)

    def request(self, icon):
        """There are no menu icons to walk to; a task (a generator) is taken as it is."""
        if hasattr(icon, "__next__"):
            self.stop()
            self.task, self.manual = icon, True

    def resume(self):
        self.stop()

    def dialled(self):
        """The time on the setting screen: (hour, minute, whether the hour is being set)."""
        m = self.tama.memory
        return (self.bcd((MEM_DIAL_HOUR,)) % 12 + (12 if m(MEM_DIAL_PM) else 0),
                self.bcd((MEM_DIAL_MINUTE,)), bool(m(MEM_DIAL_FIELD)))

    def dial(self):
        """Set hour and minute on the screen that asks for them; True if it took them."""
        want = self.wall(time.time() + 15)
        for field, wish, turn in ((0, want.tm_hour, 24), (1, want.tm_min, 60)):
            if self.dialled()[2] != (field == 0):
                return False
            for _ in range(turn):
                have = self.dialled()[field]
                if have == wish:
                    break
                yield from self.press(BTN_UP if (wish - have) % turn <= turn // 2 else BTN_DOWN, 0.3)
            if self.dialled()[field] != wish:
                return False
            if field and self.realtime:
                # the last press starts the minute: wait for it
                for _ in range(600):
                    if self.wall().tm_min == want.tm_min:
                        break
                    yield 0.1
            yield from self.press(BTN_A, 1.0)
        return True

    def begin(self):
        """From the title: any key, then the clock."""
        m = self.tama.memory
        if m(MEM_MODE) == TITLE:
            yield 3.0                           # the title takes no key at first
            yield from self.press(BTN_A, 3.0)
        if m(MEM_MODE) == SETTING:
            if (yield from self.dial()):
                yield 4.0
                self.clock_set_at = self.tama.seconds
                self.log("Uhr gestellt: %s" % self.status()["clock"])
            else:
                yield 2.0

    def set_clock(self):
        m = self.tama.memory
        yield from self.home()
        if m(MEM_MODE) != HOME:
            return
        yield from self.press(BTN_START, 2.0)
        if m(MEM_MODE) != OPTIONS:
            return
        for _ in range(3):
            if m(MEM_CURSOR) == 3:
                break
            yield from self.press(BTN_DOWN, 0.6)
        if m(MEM_CURSOR) != 3:
            yield from self.home()
            return
        yield from self.press(BTN_A, 1.2)
        done = yield from self.dial()
        yield from self.home()
        if done:
            self.clock_set_at = self.tama.seconds
            self.log("Uhr gestellt: %s" % self.status()["clock"])

    def give(self, watts):
        """The gift screen: dial the three digits, confirm, and say yes to "GIVE ?"."""
        m = self.tama.memory
        yield from self.home()
        if m(MEM_MODE) != HOME:
            return
        for _ in range(4):
            if self.tama.lit(*ICON_GIFT):
                break
            yield from self.press(BTN_RIGHT, 0.6)
        if not self.tama.lit(*ICON_GIFT):
            return
        yield from self.press(BTN_A, 1.5)
        if m(MEM_MODE) != GIFT:
            return
        before = self.bcd(MEM_WATTS)
        for cell, digit in zip(MEM_DIGITS, "%03d" % watts):
            for _ in range(12):
                if m(cell) == int(digit):
                    break
                yield from self.press(BTN_UP, 0.3)
            if m(cell) != int(digit):
                yield from self.home()
                return
            yield from self.press(BTN_A, 0.8)
        yield 1.0
        yield from self.press(BTN_A, 1.0)       # GIVE ?
        for _ in range(40):                     # it shows what it thinks of the gift
            if m(MEM_MODE) == HOME and self.bcd(MEM_WATTS) != before:
                break
            yield 1.0
        if self.bcd(MEM_WATTS) < before:
            self.gave_at = self.day_from
            self.log("%d Watt geschenkt (Zuneigung %d)" % (before - self.bcd(MEM_WATTS),
                                                           self.bcd(MEM_ACCOUNT)))
        yield from self.home()

    def may_walk(self):
        """Not while it sleeps and not while it is busy with something: with the display
        on, that would be held against the walker."""
        m = self.tama.memory
        return m(MEM_MODE) == HOME and self.hour() in DAY and m(MEM_DOING) not in AT_PLAY \
            and not m(MEM_BED)

    def walk(self, steps):
        for _ in range(steps):
            if not self.may_walk():
                return
            self.held = BTN_STEP
            self.tama.button(BTN_STEP, True)
            yield SWING
            self.tama.button(BTN_STEP, False)
            self.held = None
            yield rules.STEP - SWING

    def call_back(self):
        """It has left. With the display on, shaking brings it back."""
        yield from self.home()
        self.log("Pikachu ist weg: schütteln, bis es wiederkommt")
        for _ in range(40):
            self.tama.button(BTN_STEP, True)
            yield SWING
            self.tama.button(BTN_STEP, False)
            yield rules.STEP - SWING
            if self.tama.memory(MEM_MOOD):
                self.log("Pikachu ist wieder da")
                break

    # -- the plan -----------------------------------------------------------

    def due(self, hour, minute):
        """Steps that should have been walked by now, of its day (from 8 to 8)."""
        per_day = rules.PACE.get(self.goal, rules.DEFAULT)
        if per_day is None:
            return None
        if MORNING <= hour < EVENING:
            spent = (hour - MORNING) * 60 + minute
            return min(per_day, per_day * (spent + 1) // SPREAD)
        return per_day

    def plan(self):
        m = self.tama.memory
        mode = m(MEM_MODE)
        if mode in (TITLE, SETTING):
            return self.begin()
        now = self.tama.seconds
        hour, minute = self.hour(), self.bcd((MEM_MINUTE,))

        # its day begins at 8 in the morning
        today = self.today()
        if self.last_hour is not None and self.last_hour < MORNING <= hour:
            self.day_from = self.bcd(MEM_STEPS)
            today = 0
        self.last_hour = hour

        mood, stage = m(MEM_MOOD), rules.stage(self.bcd(MEM_STEPS), m(MEM_UNLOCK))
        if self.mood_seen and mood and mood != self.mood_seen:
            self.log("Zuneigung: %s" % rules.MOODS.get(mood, "?"))
        if self.stage_seen is not None and stage > self.stage_seen:
            self.log(rules.NAMES[stage])
        self.mood_seen, self.stage_seen = mood, stage

        if self.realtime and now >= self.clock_check:
            self.clock_check = now + 600
            if abs(self.clock_error()) > CLOCK_TOLERANCE:
                return self.set_clock()

        if stage == 5:
            # The counter is full. Sooner or later the last screen comes, and then nothing
            # goes on but a reset.
            if mode == END and self.restart:
                self.log("Der Zähler ist voll: Neubeginn")
                self.tama.reset()
                self.day_from = self.gave_at = self.last_hour = None
                self.mood_seen = self.stage_seen = None
                if self.reborn:
                    self.reborn()
                return None
            if mode == DARK:
                return self.home()              # that switches it on, to the last screen
            return None
        if mood == 0 and self.bcd(MEM_ACCOUNT) == 0:
            # (the memory is as empty for a moment after a reset)
            if self.gone_since is None:
                self.gone_since = now
            if now - self.gone_since >= GONE_FOR:
                self.gone_since = None
                return self.call_back()
            return None
        self.gone_since = None

        # give away what the day has brought: once from the evening on, or as soon as
        # there is more than it takes in a day
        watts, given = self.bcd(MEM_WATTS), self.bcd(MEM_GIVEN)
        room = rules.GIVEN_A_DAY - given
        if hour in DAY and not m(MEM_BED) and room > 0 and watts > 0 and (
                watts >= room or (hour >= GIVE_FROM and self.gave_at != self.day_from)):
            if mode in (HOME, DARK) and m(MEM_DOING) not in AT_PLAY:
                return self.give(min(watts, room, 999))

        if mode == DARK:
            return self.press(BTN_A, 1.0)       # the display stays on

        due = self.due(hour, minute)
        if due is None or today + BOUT <= due or (today < due and minute >= 30 and hour == EVENING - 1):
            self.waiting = not self.may_walk()
            if not self.waiting:
                return self.walk(BOUT if due is None else max(1, min(BOUT, due - today)))
        else:
            self.waiting = False
        return None
