"""Care-Bot: looks after the Tamagotchi by pressing its three buttons.

The bot reads the pet's needs from the emulated RAM and LCD and then does
what a human would do: walk the icon menu with A, confirm with B, cancel
with C. All timing is in emulated seconds, so it works at any speed.
"""
import random
import time

import growth
from tama import BTN_A, BTN_B, BTN_C, LCD_W

# RAM cells of the P1 ROM (found by experiment, one 4-bit value each)
MEM_SEC_LO, MEM_SEC_HI = 0x10, 0x11     # clock seconds, BCD
MEM_MIN_LO, MEM_MIN_HI = 0x12, 0x13     # clock minutes, BCD
MEM_HOUR_LO, MEM_HOUR_HI = 0x14, 0x15   # clock hours, binary
MEM_HUNGER = 0x40                       # 0..15, a heart per 4
MEM_HAPPY = 0x41                        # 0..15, a heart per 4
MEM_WEIGHT_LO, MEM_WEIGHT_HI = 0x46, 0x47  # BCD
MEM_GAME_WIN = 0x84                     # game: non-zero if the coming round is a win
MEM_POOP = 0x4D                         # number of droppings on screen
MEM_STAGE = 0x5D                        # 0 egg/dead, 1 baby, 2 child, ... (growth.py)
MEM_MISTAKES = 0x42                     # care mistakes so far, 0..15
MEM_DISCIPLINE = 0x43                   # discipline meter, +4 per scolding
MEM_KIND = 0x50                         # tells the two kinds of a teenager apart
MEM_MISSED = 0x51                       # discipline calls left unanswered, 0..15

ICON_FOOD, ICON_LIGHT, ICON_GAME, ICON_MEDICINE, ICON_TOILET, ICON_STATUS, \
    ICON_DISCIPLINE, ICON_ATTENTION = range(8)

CLOCK_TOLERANCE = 45    # seconds the pet's clock may be off before it is set again
NEGLECT_LIMIT = 40 * 60  # give up waiting for a wanted care mistake after this long

PRESS = 0.15    # how long a button is held
PAUSE = 0.4     # gap after a button press

SKULL = ("........", "..#####.", ".#######", ".#..#..#",
         ".#######", ".###.###", "..#####.", "..#.#.#.")
Z_SMALL = ("........", "........", ".####...", "....#...",
           "...#....", "..#.....", ".#......", ".####...")
Z_BIG = ("....###.", "......#.", ".....#..", "....#...",
         "..#.###.", "#.......", "........", "........")
ARROW = ("........", "...#....", "...##...", ".#####..",
         ".######.", ".#####..", "...##...", "...#....")
CLOCK_M = ("........", ".##.###.", ".#.#.##.", ".#.#.##.")
DEAD = (
    (".#...#..", "#....#..", ".###.#..", "..#.#...",
     ".##.....", "#.#.....", "#.......", "........"),
    ("........", ".#...#..", "...#....", "..#.#...",
     "...#....", ".#...#..", "........", "........"),
    ("........", "........", ".#.#.#.#", ".#.#.##.",
     ".#.#.#..", "..##.#..", "...#.#..", ".##....."),
)


def hearts(value):
    return (value + 1) // 4


class Screen:
    def __init__(self, pixels, icons):
        self.pixels = pixels
        self.icons = icons

    def region(self, x0, y0, w, h):
        return tuple(
            "".join("#" if self.pixels[(y0 + y) * LCD_W + x0 + x] else "."
                    for x in range(w))
            for y in range(h))

    def lit(self):
        return sum(1 for p in self.pixels if p)

    def selected(self):
        """Index of the highlighted menu icon, or None."""
        for i in range(7):
            if self.icons[i]:
                return i
        return None


class CareBot:
    def __init__(self, tama, log=print, discipline=True, feed_below=3, play_below=3):
        self.tama = tama
        self.log = log
        self.discipline = discipline    # scold at all (only asked when there is no goal)
        self.goal = None                # character to raise (growth.GOALS) or None
        self.feed_below = feed_below    # act when fewer hearts than this
        self.play_below = play_below
        self.task = None
        self.manual = False             # the task is a menu walk the user asked for
        self.wake = 0.0
        self.held = None
        self.clock_set_at = None
        self.dead_logged = False
        self.scold_after = None
        self.light_wish = None
        self.realtime = True        # False while the emulation is sped up
        self.clock_check = 0.0
        self.counted = None             # (stage, mistakes, missed) last seen
        self.neglect = None             # (since, next precautionary scolding)
        self.ignoring = False

    # -- state readers -----------------------------------------------------

    def screen(self):
        return Screen(*self.tama.frame())

    def status(self):
        m = self.tama.memory
        s = self.screen()
        top_right = s.region(24, 0, 8, 8)
        # Light off inverts the LCD: all black when awake, black with a
        # floating "Z" cut out while it sleeps.
        dark = s.lit() > 400
        return {
            "stage": m(MEM_STAGE),
            "hunger": hearts(m(MEM_HUNGER)),
            "happy": hearts(m(MEM_HAPPY)),
            "weight": m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO),
            "poop": m(MEM_POOP),
            "mistakes": m(MEM_MISTAKES),
            "missed": m(MEM_MISSED),
            "training": hearts(m(MEM_DISCIPLINE)),   # the meter on the status screen
            "kind": m(MEM_KIND),
            "sick": top_right == SKULL,
            "asleep": top_right in (Z_SMALL, Z_BIG) or (dark and s.lit() < len(s.pixels)),
            "light": not dark,
            "attention": bool(s.icons[ICON_ATTENTION]),
            "dead": s.region(24, 8, 8, 8) in DEAD,
            # Only meaningful while the game is running (decided before the press)
            "game": bool(m(MEM_GAME_WIN)) if s.icons[ICON_GAME] else None,
            "clock": "%02d:%d%d" % (m(MEM_HOUR_HI) * 16 + m(MEM_HOUR_LO),
                                    m(MEM_MIN_HI), m(MEM_MIN_LO)),
        }

    # -- scheduler ---------------------------------------------------------

    def step(self):
        """Call often; does at most one thing and returns immediately."""
        now = self.tama.seconds
        if now < self.wake:
            return
        if self.task is None:
            self.task = self.plan()
            if self.task is None:
                self.wake = now + 1.0
                return
        try:
            self.wake = now + next(self.task)
        except StopIteration:
            self.task = None
            self.manual = False
            self.wake = now + 1.0

    def stop(self):
        """Drop whatever the bot was doing (and let go of the button)."""
        if self.held is not None:
            for btn in self.held if isinstance(self.held, tuple) else (self.held,):
                self.tama.button(btn, False)
            self.held = None
        self.task = None
        self.manual = False
        self.wake = 0.0

    # -- primitives (generators yielding emulated seconds to wait) ---------

    def press(self, btn, pause=PAUSE):
        self.held = btn
        self.tama.button(btn, True)
        yield PRESS
        self.tama.button(btn, False)
        self.held = None
        yield pause

    def home(self):
        """Back to the plain pet screen: no menu icon selected, no clock."""
        for _ in range(4):
            if self.screen().selected() is None:
                break
            yield from self.press(BTN_C, 0.8)
        if self.screen().region(2, 12, 8, 4) == CLOCK_M:
            yield from self.press(BTN_B, 3.0)

    def select(self, icon):
        for _ in range(10):
            if self.screen().selected() == icon:
                return True
            yield from self.press(BTN_A)
        return False

    def goto(self, icon):
        """Walk to a menu icon and stop there; confirming is left to the user."""
        for _ in range(3):              # the ROM ignores buttons during animations
            if self.screen().selected() == icon:
                break
            yield from self.home()      # A means something else inside a submenu
            yield from self.select(icon)

    def request(self, icon):
        """The user clicked a menu icon: walk there, whatever the bot was doing."""
        self.stop()
        self.task = self.goto(icon)
        self.manual = True

    def resume(self):
        """Take over again after the user played: they may have left a menu open."""
        self.stop()
        self.task = self.home()

    # -- actions -----------------------------------------------------------

    def device_time(self):
        """Seconds since midnight on the pet's own clock."""
        m = self.tama.memory
        return ((m(MEM_HOUR_HI) * 16 + m(MEM_HOUR_LO)) * 3600
                + (m(MEM_MIN_HI) * 10 + m(MEM_MIN_LO)) * 60
                + m(MEM_SEC_HI) * 10 + m(MEM_SEC_LO))

    def clock_error(self):
        """How far the pet's clock is ahead of the real time, in seconds."""
        t = time.localtime()
        real = t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec
        return (self.device_time() - real + 43200) % 86400 - 43200

    def dial(self):
        """In clock-set mode: dial in the time and confirm it on the minute.

        Dialling takes up to 45 seconds and the clock restarts at second 0
        when C is pressed, so aim at a minute boundary a little ahead and
        press C exactly then. Presses are checked against the clock in RAM,
        so it is also right when resumed half-way (restart).
        """
        m = self.tama.memory
        for _ in range(3):
            goal = time.time()
            if self.realtime:
                # Leave enough time for the presses, then round up to the minute
                t = time.localtime(goal)
                presses = ((t.tm_hour - m(MEM_HOUR_HI) * 16 - m(MEM_HOUR_LO)) % 24
                           + (t.tm_min + 1 - m(MEM_MIN_HI) * 10 - m(MEM_MIN_LO)) % 60)
                goal = (goal + 10 + presses * (PRESS + PAUSE) * 1.2) // 60 * 60 + 60
            t = time.localtime(goal)
            for read, btn, want, tries in (
                    (lambda: m(MEM_HOUR_HI) * 16 + m(MEM_HOUR_LO), BTN_A, t.tm_hour, 30),
                    (lambda: m(MEM_MIN_HI) * 10 + m(MEM_MIN_LO), BTN_B, t.tm_min, 70)):
                for _ in range(tries):
                    before = read()
                    if before == want:
                        break
                    yield from self.press(btn)
                    if read() == before:
                        return False    # not in set mode after all
            if not self.realtime or time.time() < goal:
                break
        while self.realtime and time.time() < goal:
            yield 0.05
        yield from self.press(BTN_C, 2.0)
        return True

    def set_clock(self):
        """A fresh egg: it only starts hatching once the clock has been set."""
        self.log("Uhr stellen")
        yield from self.press(BTN_B, 1.5)
        if (yield from self.dial()):
            self.clock_set_at = self.tama.seconds

    def sync_clock(self, error):
        self.log("Uhr nachstellen (ging %d s %s)" % (abs(error), "vor" if error > 0 else "nach"))
        yield from self.home()
        if self.screen().region(2, 12, 8, 4) != CLOCK_M:
            yield from self.press(BTN_B, 4.0)       # open the clock view (slides in)
        for _ in range(3):
            if self.screen().region(2, 12, 8, 4) != CLOCK_M:
                break
            # A and C together switch the clock view to set mode
            self.tama.button(BTN_A, True)
            self.tama.button(BTN_C, True)
            self.held = (BTN_A, BTN_C)
            yield 0.3
            self.tama.button(BTN_A, False)
            self.tama.button(BTN_C, False)
            self.held = None
            yield 1.5
            # In set mode the clock stands still at second 0
            if self.device_time() % 60 == 0:
                yield 1.5
                if self.device_time() % 60 == 0:
                    yield from self.dial()
                    yield 1.0
                    break
        yield from self.home()

    def feed(self):
        self.log("Füttern (Hunger %d/4)" % hearts(self.tama.memory(MEM_HUNGER)))
        yield from self.home()
        if not (yield from self.select(ICON_FOOD)):
            return
        yield from self.press(BTN_B, 1.0)
        if self.screen().region(0, 0, 8, 8) != ARROW:
            yield from self.press(BTN_A)  # arrow was on the snack
        for _ in range(5):
            if hearts(self.tama.memory(MEM_HUNGER)) >= 4:
                break
            yield from self.press(BTN_B, 7.0)
        yield from self.home()

    def play(self):
        self.log("Spielen (Glück %d/4)" % hearts(self.tama.memory(MEM_HAPPY)))
        yield from self.home()
        for _ in range(3):
            if hearts(self.tama.memory(MEM_HAPPY)) >= 4:
                break
            if not (yield from self.select(ICON_GAME)):
                return
            yield from self.press(BTN_B, 5.0)
            for _ in range(5):
                yield from self.press(random.choice((BTN_A, BTN_B)), 8.0)
            yield 8.0
            yield from self.home()

    def clean(self):
        self.log("Saubermachen")
        yield from self.home()
        if (yield from self.select(ICON_TOILET)):
            yield from self.press(BTN_B, 8.0)
        yield from self.home()

    def heal(self):
        self.log("Medizin geben")
        yield from self.home()
        for _ in range(3):
            if not (yield from self.select(ICON_MEDICINE)):
                return
            yield from self.press(BTN_B, 7.0)
            yield from self.home()
            if self.screen().region(24, 0, 8, 8) != SKULL:
                break

    def light(self, on):
        self.log("Licht an" if on else "Licht aus")
        yield from self.home()
        if not (yield from self.select(ICON_LIGHT)):
            return
        yield from self.press(BTN_B, 1.0)
        if (self.screen().region(0, 0, 8, 8) == ARROW) != on:
            yield from self.press(BTN_A)
        yield from self.press(BTN_B, 2.0)
        yield from self.home()

    def scold(self, why="Schimpfen"):
        self.log(why)
        yield from self.home()
        if (yield from self.select(ICON_DISCIPLINE)):
            yield from self.press(BTN_B, 6.0)
        yield from self.home()

    # -- decision ----------------------------------------------------------

    def targets(self, st):
        """Counter values (mistakes, missed) to reach before the next evolution."""
        if self.goal is not None and st["stage"] >= growth.CHILD:
            way = growth.plan(self.goal, st["stage"], st["kind"], st["mistakes"], st["missed"])
            if way:
                return way[0], way[1]
        return st["mistakes"], st["missed"]     # nothing on purpose

    def growth(self, st):
        """Where the pet stands in the growth chart, for the web UI."""
        if st["dead"]:
            return None
        here = st["stage"], st["kind"], st["mistakes"], st["missed"]
        way = growth.plan(self.goal, *here) if self.goal is not None else None
        return {
            "forecast": growth.forecast(*here),
            "reachable": growth.reachable(*here),
            "plan": way[2] if way else None,
            "wanted": [way[0], way[1]] if way else None,
        }

    def watch(self, st):
        """Log what the ROM has counted and what the pet has turned into."""
        seen = st["stage"], st["mistakes"], st["missed"]
        if self.counted and st["stage"] >= growth.CHILD:
            stage, mistakes, missed = self.counted
            if stage != st["stage"] and stage > 0:
                self.log("Verwandelt in " + growth.stage_name(st["stage"]))
            if st["mistakes"] > mistakes and stage >= growth.CHILD:
                self.log("Pflegefehler gezählt (jetzt %d)" % st["mistakes"])
            if st["missed"] > missed and stage >= growth.CHILD:
                self.log("Schimpf-Ruf verpasst (jetzt %d)" % st["missed"])
        self.counted = seen

    def plan(self):
        st = self.status()
        now = self.tama.seconds
        if not st["dead"]:
            self.watch(st)

        if st["dead"]:
            if not self.dead_logged:
                self.log("Das Tamagotchi ist gestorben.")
                self.dead_logged = True
            return None
        self.dead_logged = False

        if st["stage"] == 0:
            # Egg: it only starts hatching (about 5 minutes) once the clock is set
            if self.clock_set_at is None or not 0 <= now - self.clock_set_at < 420:
                return self.set_clock()
            return None

        # Light off while it sleeps, on again once it is awake. The sleep
        # animation flickers between frames, so wait until the wish is stable.
        wish = None
        if st["asleep"] and st["light"]:
            wish = False
        elif not st["asleep"] and not st["light"]:
            wish = True
        if wish is None:
            self.light_wish = None
        elif self.light_wish is None or self.light_wish[0] != wish:
            self.light_wish = (wish, now)
        elif now - self.light_wish[1] >= 5:
            self.light_wish = None
            return self.light(wish)
        if st["asleep"] or not st["light"]:
            return None

        if st["poop"] > 0:
            return self.clean()
        if st["sick"]:
            return self.heal()

        cm_goal, dm_goal = self.targets(st)
        hungry, sad = st["hunger"] == 0, st["happy"] == 0

        # Calling although nothing is missing: it wants to be told off, and
        # until then it refuses food and games. Whether the call is answered
        # decides the character (growth.py). Give the call a moment, the icon
        # lags behind feeding and playing.
        if st["attention"] and not hungry and not sad:
            if st["missed"] < dm_goal or (self.goal is None and not self.discipline):
                if not self.ignoring and st["missed"] < dm_goal:
                    self.log("Schimpf-Ruf wird mit Absicht übergangen")
                self.ignoring = True
                return None
            if self.scold_after is None:
                self.scold_after = now + 20
            elif now >= self.scold_after:
                self.scold_after = None
                return self.scold()
            return None
        self.scold_after = None
        self.ignoring = False

        # A care mistake is wanted: let it go hungry and leave the call
        # unanswered until the ROM has counted it (about 15 minutes).
        if st["mistakes"] < cm_goal:
            if not hungry:
                self.neglect = None
            elif self.neglect is None:
                self.log("Pflegefehler mit Absicht: Hunger-Ruf wird übergangen")
                self.neglect = (now, now + 60)
            elif now - self.neglect[0] > NEGLECT_LIMIT:
                return self.feed()
            elif st["attention"] and st["missed"] >= dm_goal and now >= self.neglect[1]:
                # A discipline call could hide behind the hunger call.
                # Scolding does no harm when there is none.
                self.neglect = (self.neglect[0], now + 240)
                return self.scold("Vorsorglich schimpfen")
        else:
            self.neglect = None
            if st["hunger"] < self.feed_below:
                return self.feed()
        if st["happy"] < self.play_below:
            return self.play()

        # Nothing else to do: keep the pet's clock on the real time (it falls
        # behind while the server is down, and summer time changes). Not for
        # babies: they need care every few minutes and were only just set.
        if self.realtime and st["stage"] >= 2 and now >= self.clock_check:
            self.clock_check = now + 600
            error = self.clock_error()
            if abs(error) > CLOCK_TOLERANCE:
                return self.sync_clock(error)
        return None
