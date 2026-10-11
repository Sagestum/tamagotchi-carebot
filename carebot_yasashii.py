"""Care-Bot for the Yasashii Tamagotch (1998), the gentle one with a button for every action.

There is no menu: the buttons for food, mood, care, toilet, light and the check meter each
open their own screen, "select" (B) moves within it and the same button again confirms;
"cancel" (C) goes back.

It is quick to take offence: 2 minutes and 12 seconds after it has called (hearts empty, a
dropping, asleep with the light on, ill) a care mistake is counted. The mistakes as a child
decide which teenager it becomes, the mistakes as a teenager which adult; they begin again
at 0 with every change (growth_yasashii.py).
"""
import time

from carebot import CareBot, CLOCK_TOLERANCE
from tama import BTN_A, BTN_B, BTN_C, BTN_TAP

# RAM cells of the Yasashii ROM (found by experiment, one 4-bit value each)
MEM_POOP = 0x07                         # droppings on the screen
MEM_SCREEN = 0x09                       # what is up: 2 the pet, 3 the check meter, 4 the food,
                                        # 5 the game, 6 the mood menu, 0xA the clock, 1 the
                                        # clock being set
MEM_SEC_LO, MEM_SEC_HI = 0x1A, 0x1B     # the clock: seconds and minutes in BCD,
MEM_MIN_LO, MEM_MIN_HI = 0x1C, 0x1D
MEM_HOUR, MEM_PM = 0x1E, 0x1F           # the hour from 1 to 12, and 1 in the afternoon
MEM_CURSOR = 0x0A                       # in a menu: 0 the first entry, 8 the second
MEM_CHARACTER = 0x0B                    # 1 the baby, 2 the child, ... (growth_yasashii.py)
MEM_HUNGER, MEM_HAPPY = 0x31, 0x32      # hearts, 0 to 4
MEM_AGE = 0x36                          # its age: one more every time it wakes up
MEM_ILLNESSES = 0x39                    # times it has been ill; the third is its death
MEM_WEIGHT_LO, MEM_WEIGHT_HI = 0x34, 0x35  # BCD, grams
MEM_MISTAKES = 0x3D                     # care mistakes as this character
MEM_FLAGS = 0x05                        # bit 0 ill, bit 1 dead, bit 2 asleep. Bit 3: it is up to no good; once it calls (MEM_CALL
                                        # is 1) it takes neither food nor snack until it has
                                        # been told off with the heart button
MEM_CALL = 0x42
MEM_DISCIPLINE = 0x33                   # the discipline meter, 2 more for every telling off

HOME, METER, FOOD, GAME, MOOD, CLOCK, SETTING = 2, 3, 4, 5, 6, 0xA, 1
BTN_CLEAN, BTN_HEART, BTN_SMILE, BTN_FOOD = 4, 5, 6, 7     # the inputs K10 to K13
BTN_METER, BTN_SELECT, BTN_CANCEL, BTN_LIGHT = BTN_A, BTN_B, BTN_C, BTN_TAP
HOLD = 0.2
LIFE = {2: 48.0, 3: 73.0, 4: 73.0}          # hours a character stays


class YasashiiBot(CareBot):
    def __init__(self, tama, log=print, discipline=True, feed_below=3, play_below=3, model=None):
        super().__init__(tama, log, discipline, feed_below, play_below, model)
        self.bad = 0                    # care mistakes to make as every character
        self.next_light = self.next_care = 0.0
        self.spared = None              # the mistakes there were at the last helping
        self.woke = 0.0                 # when it was last seen asleep
        self.seen_dark = (None, False)
        self.kind = 1                   # the kind of teenager, by the child's care mistakes
        self.most = 0                   # the most care mistakes seen as this character
        self.since = None               # (character, emulated second it was first seen)
        self.owed = False               # a helping is due after a counted mistake
        self.empty = None               # since when a meter has been empty
        self.next_morsel = 0.0
        self.dropping = None            # (since when a dropping lies there, the mistakes then)

    def memo(self):
        return {"kind": self.kind, "since": self.since, "most": self.most}

    def recall(self, memo):
        if not isinstance(memo, dict):
            return
        if memo.get("kind") in (1, 2):
            self.kind = memo["kind"]
        if memo.get("since"):
            self.since = tuple(memo["since"])
        self.most = memo.get("most") or 0

    def weight(self):
        m = self.tama.memory
        return m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO)

    def hour(self):
        m = self.tama.memory
        return m(MEM_HOUR) % 12 + 12 * (m(MEM_PM) & 1)

    def minute(self):
        m = self.tama.memory
        return m(MEM_MIN_HI) * 10 + m(MEM_MIN_LO)

    def device_time(self):
        """Seconds since midnight on the pet's own clock."""
        m = self.tama.memory
        return self.hour() * 3600 + self.minute() * 60 + m(MEM_SEC_HI) * 10 + m(MEM_SEC_LO)

    def naughty(self):
        return bool(self.tama.memory(MEM_FLAGS) & 8)

    def dark(self):
        """Read off the picture, once a second at most (it is asked at every step)."""
        now = int(self.tama.seconds)
        if self.seen_dark[0] != now:
            self.seen_dark = now, sum(1 for p in self.tama.frame()[0] if p) > 400
        return self.seen_dark[1]

    def status(self):
        m = self.tama.memory
        stage = m(MEM_CHARACTER)
        names = getattr(self.model.growth, "NAMES", None) or self.model.names
        return {
            "stage": stage,
            "away": False, "praying": False, "sickness": 0, "leaving": False, "thanked": False,
            "generation": None,
            "name": names.get(stage, "Yasashii %d" % stage),
            "hunger": m(MEM_HUNGER), "happy": m(MEM_HAPPY), "weight": self.weight(),
            "poop": m(MEM_POOP), "mistakes": m(MEM_MISTAKES), "age": m(MEM_AGE),
            "illnesses": m(MEM_ILLNESSES), "missed": 0, "training": 0,
            "meter": 0, "kind": 0,
            "sick": bool(m(MEM_FLAGS) & 1), "asleep": bool(m(MEM_FLAGS) & 4), "attack": False,
            "cocoon": False, "temperature": None, "friendship": None, "sweetness": None,
            "look": None, "back": False,
            "light": not self.dark(), "attention": self.naughty(), "scold": self.naughty(),
            "dead": bool(m(MEM_FLAGS) & 2),
            "game": None, "screen": m(MEM_SCREEN), "clock": "%02d:%02d" % (self.hour(), self.minute()),
        }

    # -- primitives ---------------------------------------------------------

    def press(self, btn, pause=1.0):
        self.held = btn
        self.tama.button(btn, True)
        yield HOLD
        self.tama.button(btn, False)
        self.held = None
        yield pause

    def home(self):
        m = self.tama.memory
        for _ in range(5):
            if m(MEM_SCREEN) == HOME:
                break
            yield from self.press(BTN_CANCEL, 1.5)

    # -- actions -------------------------------------------------------------

    def set_clock(self):
        """A fresh device shows the egg: select opens the setting of the clock; once it
        is taken the egg hatches."""
        self.log("Uhr stellen")
        yield from self.press(BTN_SELECT, 1.0)
        if self.tama.memory(MEM_SCREEN) == SETTING and (yield from self.dial()):
            self.clock_set_at = self.tama.seconds
        yield from self.press(BTN_CANCEL, 2.0)

    def dial(self):
        """While the clock is being set: select counts the hours up, cancel the minutes,
        and the check meter takes it; the clock then begins at second 0. So a minute a
        little ahead is dialled and taken as it begins."""
        m = self.tama.memory
        for _ in range(3):
            goal = time.time()
            if self.realtime:
                # the minute to dial: the first one the presses are done before
                start, goal = goal, (goal + 5) // 60 * 60 + 60
                for _ in range(5):
                    t = self.wall(goal)
                    presses = (t.tm_hour - self.hour()) % 24 + (t.tm_min - self.minute()) % 60
                    if start + 5 + presses * (HOLD + 0.5) * 1.2 <= goal:
                        break
                    goal += 60
            t = self.wall(goal)
            for read, btn, want, tries in ((self.hour, BTN_SELECT, t.tm_hour, 30),
                                           (self.minute, BTN_CANCEL, t.tm_min, 70)):
                for _ in range(tries):
                    before = read()
                    if before == want:
                        break
                    yield from self.press(btn, 0.5)
                    if read() == before or m(MEM_SCREEN) != SETTING:
                        return False    # the clock is not being set after all
            if not self.realtime or time.time() < goal:
                break
        while self.realtime and time.time() < goal:
            yield 0.05
        yield from self.press(BTN_METER, 2.0)
        return True

    def sync_clock(self, error):
        """The clock of a living one: select shows it, select and cancel together begin
        the setting."""
        m = self.tama.memory
        self.log("Uhr nachstellen (ging %d min %s)" % (abs(error) // 60, "vor" if error > 0 else "nach")
                 if abs(error) >= 120 else
                 "Uhr nachstellen (ging %d s %s)" % (abs(error), "vor" if error > 0 else "nach"))
        yield from self.home()
        yield from self.press(BTN_SELECT, 2.0)
        if m(MEM_SCREEN) == CLOCK:
            self.held = (BTN_SELECT, BTN_CANCEL)
            for btn in self.held:
                self.tama.button(btn, True)
            yield 0.5
            for btn in self.held:
                self.tama.button(btn, False)
            self.held = None
            yield 2.0
            if m(MEM_SCREEN) == SETTING and (yield from self.dial()):
                self.clock_set_at = self.tama.seconds
        if m(MEM_SCREEN) == SETTING:
            yield from self.press(BTN_METER, 2.0)       # out of the setting, whatever was dialled
        yield from self.home()

    def meal(self):
        m = self.tama.memory
        before = m(MEM_HUNGER)
        yield from self.home()
        yield from self.press(BTN_FOOD, 1.5)
        if m(MEM_SCREEN) == FOOD:
            yield from self.press(BTN_FOOD, 9.0)
        yield from self.home()
        return m(MEM_HUNGER) > before

    def feed(self, meals=4):
        m = self.tama.memory
        self.log("Füttern (Hunger %d/4)" % m(MEM_HUNGER))
        for _ in range(meals):
            if m(MEM_HUNGER) >= 4 or not (yield from self.meal()):
                break

    def snack(self):
        """The mood button offers the game and the snack; the snack is the second."""
        m = self.tama.memory
        before = m(MEM_HAPPY)
        yield from self.home()
        yield from self.press(BTN_SMILE, 1.5)
        if m(MEM_SCREEN) == MOOD:
            if m(MEM_CURSOR) != 8:
                yield from self.press(BTN_SELECT, 1.0)
            yield from self.press(BTN_SMILE, 9.0)
        yield from self.home()
        return m(MEM_HAPPY) > before

    def sweets(self):
        m = self.tama.memory
        self.log("Snack (Glück %d/4)" % m(MEM_HAPPY))
        for _ in range(4):
            if m(MEM_HAPPY) >= 4 or not (yield from self.snack()):
                break

    def clean(self):
        self.log("Toilette")
        yield from self.home()
        yield from self.press(BTN_CLEAN, 8.0)
        yield from self.home()

    def light(self, on, why=None):
        self.log(why or ("Licht an" if on else "Licht aus"))
        yield from self.home()
        yield from self.press(BTN_LIGHT, 3.0)

    def care(self, why="Medizin"):
        """The heart: medicine when it is ill, a telling off when it is up to no good."""
        self.log(why)
        yield from self.home()
        yield from self.press(BTN_HEART, 8.0)
        yield from self.home()

    def scold(self, why="Schimpfen"):
        """While it is up to no good it does not call for anything else (so no care mistake
        is counted either), and it only shows it once food has been turned down. So it is
        offered a meal first, and then told off."""
        m = self.tama.memory
        if m(MEM_CALL) != 1:
            yield from self.meal()
        if m(MEM_FLAGS) & 8:
            yield from self.care(why)

    def new_life(self):
        """It has gone and left an egg that nothing but the reset button on the front of
        the case wakes. The reset here clears the memory too, so the album of those
        that went before is lost."""
        yield 30.0
        if not self.status()["dead"]:
            return
        self.tama.reset()
        self.counted = self.spared = None
        self.kind = 1
        self.clock_set_at = None
        self.clock_check = 0
        if self.reborn:
            self.reborn()
        self.log("Neues Ei")

    # -- decision -------------------------------------------------------------

    def left(self, st):
        """Hours until this character changes, as far as the bot has seen it begin: the
        child stays 48 hours, the teenager 73."""
        if self.since is None or self.since[0] != st["stage"] or st["stage"] not in LIFE:
            return None
        return LIFE[st["stage"]] - (self.tama.seconds - self.since[1]) / 3600

    def late(self, st, want):
        """Whether it is time for the care mistakes of this character. From the third on
        it falls ill, at once and again every morning, and the third illness of a
        character is its death (they are counted anew after every change). So the third
        mistake is not made before the last 30 hours, which have one morning in them.
        They have room for six to ten; if more are wanted, the first two are made a day
        earlier. Up to two do no harm and are left to the last day."""
        left = self.left(st)
        if left is None:
            return False
        if want <= 2:
            return left <= 20
        if left <= 30:
            return True
        return want > 6 and left <= 54 and st["mistakes"] < 2

    def starve(self, st):
        """One care mistake at a time: a meter is left empty until the mistake has been
        counted (when the next heart would have gone, an hour or two later), then it
        gets one helping, enough to run empty again. It does not call again while the
        meter stays empty, so no further mistake would be counted, and after a day of
        that it dies; the helping is not always taken, so it is offered until a heart
        is there, and also when nothing has been counted for three hours."""
        now = self.tama.seconds
        if self.spared is None or st["mistakes"] < self.spared:
            self.spared = st["mistakes"]
        if st["mistakes"] > self.spared:
            self.spared = st["mistakes"]
            self.owed = True
        bare = st["hunger"] == 0 or st["happy"] == 0
        if not bare:
            self.owed, self.empty = False, None
            return None
        if self.empty is None:
            self.empty = now
        if now - self.empty > 3 * 3600:
            self.owed = True
        if self.owed and now >= self.next_morsel:
            self.next_morsel = now + 60
            self.empty = now
            return self.morsel()
        return None

    def morsel(self, why="Ein Happen nach dem Pflegefehler"):
        m = self.tama.memory
        self.log(why)
        if m(MEM_HUNGER) == 0:
            yield from self.meal()
        if m(MEM_HAPPY) == 0:
            yield from self.snack()

    def wish(self, st):
        """What to do as this character: (care mistakes to make, the characters still to
        come, the chance that the goal comes out; None if it is out of reach)."""
        rules = self.model.growth
        if self.goal is None or rules is None:
            return self.bad, None, None
        way = rules.plan(self.goal, st["stage"], self.kind)
        return way if way else (0, None, None)

    def growth(self, st):
        rules = self.model.growth
        if rules is None or st["stage"] == 0:
            return None
        mistakes, rest, chance = self.wish(st)
        return {
            "forecast": rules.forecast(st["stage"], st["mistakes"], self.kind),
            "reachable": rules.reachable(st["stage"], self.kind),
            "plan": rest,
            "wanted": {"mistakes": mistakes, "chance": chance, "kind": self.kind},
        }

    def watch(self, st):
        seen = st["stage"], st["mistakes"]
        if self.since is not None and self.since[0] != st["stage"]:
            self.since = None
        if self.counted and st["stage"] > 0:
            stage, mistakes = self.counted[:2]
            if stage != st["stage"] and stage > 0:
                # the mistakes are cleared a moment before the character changes
                if stage == 2 and self.model.growth:
                    self.kind = self.model.growth.teen(max(mistakes, self.most))[1]
                elif st["stage"] <= 2:
                    self.kind = 1
                self.most = 0
                self.since = (st["stage"], self.tama.seconds)
                self.owed, self.empty, self.spared = False, None, None
                self.log("Verwandelt in " + st["name"])
            else:
                self.most = max(self.most, st["mistakes"])
                if st["mistakes"] > mistakes:
                    self.log("Pflegefehler gezählt (jetzt %d)" % st["mistakes"])
        self.counted = seen

    def plan(self):
        st = self.status()
        now = self.tama.seconds
        if st["dead"]:
            if not self.dead_logged:
                self.log("Das Tamagotchi ist gestorben.")
                self.dead_logged = True
            return self.new_life() if self.restart else None
        self.dead_logged = False
        if st["stage"] == 0:
            if now > 3 and now >= self.clock_check:
                self.clock_check = now + 600
                return self.set_clock()
            return None
        self.watch(st)
        if st["asleep"]:
            self.woke = now
            if st["light"] and now >= self.next_light:
                self.next_light = now + 20
                return self.light(False)
            return None
        if not st["light"] and now >= self.next_light:
            self.next_light = now + 20
            return self.light(True)
        if st["screen"] != HOME:
            return self.home()
        want = self.wish(st)[0]
        slack = st["mistakes"] < want and self.late(st, want)
        if st["poop"] > 0:
            # a dropping left for 2 minutes and 12 seconds is a care mistake too
            if self.dropping is None:
                self.dropping = now, st["mistakes"]
            if not slack or st["mistakes"] > self.dropping[1] or now - self.dropping[0] > 300:
                return self.clean()
        else:
            self.dropping = None
        if st["sick"] and now >= self.next_care:
            self.next_care = now + 15
            return self.care()
        if st["scold"] and now >= self.next_care:
            self.next_care = now + 30
            return self.scold()
        if slack:
            if not self.ignoring:
                self.ignoring = True
                self.log("Pflegefehler mit Absicht: es bleibt hungrig (%d von %d)" % (st["mistakes"], want))
            return self.starve(st) or self.check_clock(now)
        self.ignoring = False
        self.spared = None
        self.owed, self.empty = False, None
        left = self.left(st)
        if st["mistakes"] < want and want > 2 and left is not None and left <= 54:
            # before many mistakes the meters are kept low, a heart at a time, so that
            # both are empty soon once the time for them has come
            if st["hunger"] == 0 or st["happy"] == 0:
                return self.morsel("Ein Happen, mehr nicht")
            return self.check_clock(now)
        if st["hunger"] < self.feed_below:
            return self.feed()
        if st["happy"] < self.play_below:
            return self.sweets()
        return self.check_clock(now)

    def check_clock(self, now):
        """Every ten minutes, when nothing else is to be done: is its clock still right?"""
        if not self.realtime or now < self.clock_check:
            return None
        self.clock_check = now + 600
        error = self.clock_error()
        return self.sync_clock(error) if abs(error) > CLOCK_TOLERANCE else None
