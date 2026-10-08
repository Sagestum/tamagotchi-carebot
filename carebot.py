"""Care-Bot: looks after the Tamagotchi by pressing its three buttons.

The bot reads the pet's needs from the emulated RAM and LCD and then does
what a human would do: walk the icon menu with A, confirm with B, cancel
with C. All timing is in emulated seconds, so it works at any speed.
"""
import random
import time

import growth
import models
from tama import BTN_A, BTN_B, BTN_C, BTN_TAP, LCD_W

UNSET_HOUR = 32         # what the hour cells hold before the clock has been set

# RAM cells of the P1 and P2 ROMs (found by experiment, one 4-bit value each)
MEM_SEC_LO, MEM_SEC_HI = 0x10, 0x11     # clock seconds, BCD
MEM_MIN_LO, MEM_MIN_HI = 0x12, 0x13     # clock minutes, BCD
MEM_HOUR_LO, MEM_HOUR_HI = 0x14, 0x15   # clock hours, binary
MEM_HUNGER = 0x40                       # 0..15, a heart per 4
MEM_HAPPY = 0x41                        # 0..15, a heart per 4
MEM_WEIGHT_LO, MEM_WEIGHT_HI = 0x46, 0x47  # BCD
MEM_GAME_WIN = 0x84                     # P1 game: non-zero if the coming round is a win
MEM_GAME_NUMBER = 0x71                  # P2 game: the number on the screen, less one
MEM_SICK_COUNT = 0x49                   # Angel: times it has been ill as this character
MEM_JUMP_OBSTACLE = 0x81                # Angel game: where the obstacle is, 0xC far to 0x9 hit
MEM_JUMP_ROUNDS = 0x85                  # Angel game: rounds still to come, 5 to 0
MEM_ANGEL_STATE = 0x5E                  # Angel: 1 awake, 3 asleep, 9 sick, 2 eating, 0xD a bat
                                        # is after the sweet, 0xA praying, 0xB out for a
                                        # stroll, 4 making a dropping (5, 7, 8 in the game),
                                        # 0xC crying because its time is over
MEM_POOP = 0x4D                         # number of droppings on screen
MEM_STAGE = 0x5D                        # 0 egg/dead, 1 baby, 2 child, ... (growth.py)
MEM_MISTAKES = 0x42                     # care mistakes so far, 0..15
MEM_DISCIPLINE = 0x43                   # discipline meter, +4 per scolding
MEM_KIND = 0x50                         # tells the two kinds of a teenager apart
MEM_MISSED = 0x51                       # discipline calls left unanswered, 0..15

ICON_ATTENTION = 7      # the menu icons are in another order on each model (models.py)

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
THANKS = ("###.#.", ".#..#.", ".#..#.")     # Angel: the "T" and "h" of its last screen
ARROW = ("........", "...#....", "...##...", ".#####..",
         ".######.", ".#####..", "...##...", "...#....")

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
    def __init__(self, tama, log=print, discipline=True, feed_below=3, play_below=3,
                 model=models.P1):
        self.tama = tama
        self.model = model
        self.log = log
        self.discipline = discipline    # scold at all (only asked when there is no goal)
        self.restart = False            # after the end, begin a new life with A and C
        self.reborn = None              # called when the bot has begun one
        self.goal = None                # character to raise (growth.GOALS) or None
        self.feed_below = feed_below    # act when fewer hearts than this
        self.play_below = play_below
        self.power_below = 20           # Angel: give sweets below this much Angel Power
        self.task = None
        self.manual = False             # the task is a menu walk the user asked for
        self.wake = 0.0
        self.held = None
        self.clock_set_at = None
        self.dead_logged = False
        self.gone = False               # the pet has died (kept while the end screen slides)
        self.walking = False            # Angel: out for a walk
        self.praised = False            # Angel: this prayer has been praised
        self.generation = 1             # Angel: which one on the way to Lucky Unchi-Kun
        self.settled = None             # when the adult of this generation was first seen
        self.extra = (0, 0.0)           # mistakes to reach so that it takes its leave, and
                                        # when to ask for the next one
        self.leaving_logged = False
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
        stage = m(MEM_STAGE)
        angel = self.model.game == "jump"
        weight = m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO)
        # No character and the end screen. A new egg weighs nothing.
        self.gone = stage == 0 and (s.region(24, 8, 8, 8) in self.model.dead
                                    or (self.gone and weight > 0))
        if angel:       # the end screens: no character, and the state the sleepers have
            self.gone = stage == 0 and m(MEM_ANGEL_STATE) == 3
        away = angel and m(MEM_ANGEL_STATE) == 0xB      # a door on the screen
        return {
            "stage": stage,
            "away": away,
            "praying": angel and m(MEM_ANGEL_STATE) == 0xA,
            "sickness": m(MEM_SICK_COUNT) if angel else 0,
            "leaving": angel and m(MEM_ANGEL_STATE) == 0xC,     # it cries: its time is over
            "thanked": angel and m(MEM_ANGEL_STATE) == 0xC      # B was pressed: "Thanks!"
            and s.region(2, 1, 6, 3) == THANKS,
            "generation": self.generation if angel else None,
            "name": "Unterwegs" if away else self.model.stage_name(stage),
            "hunger": hearts(m(MEM_HUNGER)),
            "happy": hearts(m(MEM_HAPPY)),
            "weight": weight,
            "poop": m(MEM_POOP),
            "mistakes": m(MEM_MISTAKES),
            "missed": m(MEM_MISSED),
            "training": hearts(m(MEM_DISCIPLINE)),   # the meter on the status screen
            "kind": m(MEM_KIND),
            "sick": top_right == SKULL or (angel and m(MEM_ANGEL_STATE) == 9),
            "asleep": m(MEM_ANGEL_STATE) == 3 if angel
            else top_right in (Z_SMALL, Z_BIG) or (dark and s.lit() < len(s.pixels)),
            "light": not dark,
            "attention": bool(s.icons[ICON_ATTENTION]),
            "dead": self.gone,
            # P1, while the game is running: the round is decided before the press
            "game": bool(m(MEM_GAME_WIN))
            if self.model.game == "direction" and s.icons[self.model.icon("game")] else None,
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
        if self.screen().region(2, 12, 8, 4) == self.model.clock_m:
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
        if self.screen().region(2, 12, 8, 4) != self.model.clock_m:
            yield from self.press(BTN_B, 4.0)       # open the clock view (slides in)
        for _ in range(3):
            if self.screen().region(2, 12, 8, 4) != self.model.clock_m:
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
        if not (yield from self.select(self.model.icon("food"))):
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
            if not (yield from self.select(self.model.icon("game"))):
                return
            if self.model.game == "jump":
                # An obstacle comes along five times: jump (B) when it is two steps away
                yield from self.press(BTN_B, 1.0)
                waited, armed, begun = 0.0, True, False
                while waited < 60:
                    yield 0.05
                    waited += 0.05
                    at = self.tama.memory(MEM_JUMP_OBSTACLE)
                    begun = begun or self.tama.memory(MEM_JUMP_ROUNDS) > 0
                    if armed and at == 0xA:
                        yield from self.press(BTN_B, 0.05)
                        armed = False
                    elif at == 0xC:
                        armed = True
                    if begun and self.tama.memory(MEM_JUMP_ROUNDS) == 0 \
                            and self.tama.memory(MEM_ANGEL_STATE) not in (5, 8):
                        break
            elif self.model.game == "number":
                # Higher (B) or lower (A) than the number shown, 1 to 9? The
                # next number is only drawn when the button goes down.
                yield from self.press(BTN_B, 6.0)
                for _ in range(5):
                    low = self.tama.memory(MEM_GAME_NUMBER) <= 3
                    yield from self.press(BTN_B if low else BTN_A, 9.5)
            else:
                # Left or right: the round is decided before the press (MEM_GAME_WIN)
                yield from self.press(BTN_B, 5.0)
                for _ in range(5):
                    yield from self.press(random.choice((BTN_A, BTN_B)), 8.0)
            yield 8.0
            yield from self.home()

    def clean(self):
        self.log("Saubermachen")
        yield from self.home()
        if (yield from self.select(self.model.icon("toilet"))):
            yield from self.press(BTN_B, 8.0)
        yield from self.home()

    def heal(self):
        self.log("Medizin geben")
        yield from self.home()
        for _ in range(3):
            if not (yield from self.select(self.model.icon("medicine"))):
                return
            yield from self.press(BTN_B, 7.0)
            yield from self.home()
            if not self.status()["sick"]:
                break

    def light(self, on, why=None):
        self.log(why or ("Licht an" if on else "Licht aus"))
        yield from self.home()
        if not (yield from self.select(self.model.icon("light"))):
            return
        yield from self.press(BTN_B, 1.0)
        if (self.screen().region(0, 0, 8, 8) == ARROW) != on:
            yield from self.press(BTN_A)
        yield from self.press(BTN_B, 2.0)
        yield from self.home()

    def candy(self):
        """Angel: the sweet is the second entry of the food menu and gives Angel Power."""
        self.log("Süßes geben (Angel Power %d)" % self.status()["weight"])
        yield from self.home()
        if not (yield from self.select(self.model.icon("food"))):
            return
        yield from self.press(BTN_B, 1.0)
        if self.screen().region(0, 0, 8, 8) == ARROW:
            yield from self.press(BTN_A)
        yield from self.press(BTN_B, 0.1)
        # Now and then a bat comes for the sweet: a tap on the case drives it away
        for _ in range(90):
            yield 0.1
            if self.tama.memory(MEM_ANGEL_STATE) == 0xD:
                self.log("Fledermaus verscheucht")
                yield 0.3
                yield from self.press(BTN_TAP, 6.0)
                break
        yield from self.home()

    def praise(self, why="Loben"):
        self.log(why)
        yield from self.home()
        if (yield from self.select(self.model.icon("praise"))):
            yield from self.press(BTN_B, 6.0)
        yield from self.home()

    def fresh(self):
        """A new egg as A and C leave it: nothing counted yet, and no character."""
        m = self.tama.memory
        return (m(MEM_STAGE) == 0 and m(MEM_HUNGER) == 1 and m(MEM_HAPPY) == 1
                and m(MEM_MISTAKES) == 0)

    def begin(self):
        """On an end screen: A and C together bring a new egg. Its clock keeps running and
        it hatches by itself. The ROM does not take every press, so look and try again."""
        for _ in range(6):
            self.tama.button(BTN_A, True)
            self.tama.button(BTN_C, True)
            self.held = (BTN_A, BTN_C)
            yield 0.3
            self.tama.button(BTN_A, False)
            self.tama.button(BTN_C, False)
            self.held = None
            yield 5.0
            if self.fresh():
                self.gone = False
                self.counted = None
                self.clock_set_at = self.tama.seconds   # it is set already
                if self.reborn:
                    self.reborn()
                return True
        return False

    def new_life(self):
        """The pet has died: begin again with a new egg."""
        yield 10.0
        if self.status()["dead"] and (yield from self.begin()):
            self.log("Neues Ei")

    def farewell(self):
        """Angel: let the one that is crying go (B) and begin the next generation (A and C)."""
        lucky = self.goal == self.model.growth.LUCKY
        self.log("Generation %d verabschiedet sich" % self.generation if lucky
                 else "Verabschiedet sich")
        for _ in range(3):
            yield from self.press(BTN_C, 1.0)
        yield 5.0
        yield from self.press(BTN_B, 40.0)
        if (yield from self.begin()):
            if not lucky:
                self.log("Neues Ei")
                return
            # After the fourth the programme is through: begin it again
            self.generation = self.generation + 1 if self.generation < 4 else 1
            self.log("Generation %d beginnt" % self.generation)

    def scold(self, why="Schimpfen"):
        self.log(why)
        yield from self.home()
        if (yield from self.select(self.model.icon("discipline"))):
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
        if self.model.game == "jump":
            more, low, high, way = self.angel_wish(st)
            rules = self.model.growth
            alive = st["stage"] > 0 or st["away"]
            return {
                "forecast": rules.forecast(st["stage"], st["mistakes"], st["weight"]) if alive else [],
                "reachable": rules.reachable(st["stage"], st["mistakes"]) if alive
                else list(rules.GOALS),
                "plan": way,
                "wanted": {"mistakes": more,
                           "power": [low, high] if self.goal and way is not None else None,
                           "raising": rules.GENERATIONS.get(self.generation)
                           if self.goal == rules.LUCKY else None},
            }
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
        if st["away"]:
            return                      # out for a walk: it is still the same one
        seen = st["stage"], st["mistakes"], st["missed"]
        if self.counted and st["stage"] >= growth.CHILD:
            stage, mistakes, missed = self.counted
            if stage != st["stage"] and stage > 0:
                self.log("Verwandelt in " + st["name"])
            if st["mistakes"] > mistakes and stage >= growth.CHILD:
                self.log("Pflegefehler gezählt (jetzt %d)" % st["mistakes"])
            if st["missed"] > missed and stage >= growth.CHILD:
                self.log("Schimpf-Ruf verpasst (jetzt %d)" % st["missed"])
        self.counted = seen

    def angel_wish(self, st):
        """What the goal asks of the present character: (mistakes still to make, least and
        most Angel Power to hold, the characters to come). Without a goal: just good care."""
        rules = self.model.growth
        goal, extra = self.goal, 0
        if goal == rules.LUCKY:
            # Four generations (growth_angel.py): raise this generation's adult and, once it
            # has been one for two days, add a care mistake every half day until it leaves
            if st["stage"] == rules.GHOST_LUCKY:
                self.generation = 4
            goal = rules.GENERATIONS.get(self.generation)
            now = self.tama.seconds
            if st["stage"] != goal:
                self.settled, self.extra = None, (0, 0.0)
            else:
                if self.settled is None:
                    self.settled = now
                if now - self.settled > 2 * 86400 and now >= self.extra[1]:
                    self.extra = (min(rules.MOST, st["mistakes"] + 1), now + 43200)
                extra = self.extra[0]
        way = rules.plan(goal, st["stage"], st["mistakes"]) if goal else None
        if not way:
            return 0, self.power_below, rules.FULL, None
        _, least, _, low, high = way[0]
        more = max(0, max(least, extra) - st["mistakes"]) if st["stage"] >= rules.CHILD else 0
        if high < rules.FULL:           # a ceiling: stay a little above the floor, no more
            low = low + 4 if low else 0
        elif low:                       # a floor: keep well above it
            low = low + 6
        else:
            low = self.power_below
        return more, low, high, [step[0] for step in way[1:]]

    def plan_angel(self, st, now):
        """The Angel: food, game, sweets, medicine, light, and praise when it prays."""
        more, low, high, _ = self.angel_wish(st)
        capped = high < self.model.growth.FULL
        # Out for a stroll: it comes back by itself after five minutes, nothing is lost
        if st["away"]:
            if not self.walking:
                self.walking = True
                self.log("Macht einen Spaziergang")
            return None
        self.walking = False
        # Praying (it stands in the middle with its arms up): praise it. That gives
        # 20 Angel Power; afterwards it leaves a dropping either way.
        if st["praying"]:
            # (not when the Angel Power has to stay low: praise would add 20)
            if not self.praised and not capped:
                self.praised = True
                return self.praise("Betet: loben")
            return None
        self.praised = False
        if st["asleep"] != (not st["light"]):
            wish = not st["asleep"]
            if self.light_wish is None or self.light_wish[0] != wish:
                self.light_wish = (wish, now)
            elif now - self.light_wish[1] >= 5:
                self.light_wish = None
                return self.light(wish)
        else:
            self.light_wish = None
        if st["asleep"] or not st["light"]:
            return None
        if st["poop"] > 0:
            return self.clean()
        if st["sick"]:
            return self.heal()
        if self.goal == self.model.growth.DEVILTCHI and st["stage"] >= self.model.growth.CHILD:
            # The bad end: ill three times as the same character. Light off while it is
            # awake makes it ill at once; the lines above switch it on again and cure it.
            return self.light(False, "Licht aus im Wachen: das macht krank (%d von 3)"
                              % (st["sickness"] + 1))
        if st["hunger"] < self.feed_below:
            return self.feed()
        if more:
            # Care mistakes are wanted: every praise takes a heart of effort; with none
            # left it calls, and a call left alone for a quarter of an hour counts
            if st["happy"] > 0:
                if self.tama.memory(MEM_HAPPY) > 1:
                    return self.praise("Pflegefehler mit Absicht: Einsatz leeren")
            elif not self.ignoring:
                self.ignoring = True
                self.log("Pflegefehler mit Absicht: Ruf wird übergangen (noch %d)" % more)
        else:
            self.ignoring = False
            if st["happy"] < self.play_below:
                return self.play()
        if st["weight"] < low:
            return self.candy()
        if self.realtime and now >= self.clock_check:
            self.clock_check = now + 600
            error = self.clock_error()
            if abs(error) > CLOCK_TOLERANCE:
                return self.sync_clock(error)
        return None

    def plan(self):
        st = self.status()
        now = self.tama.seconds
        if st["stage"] == 0 and self.counted and self.counted[0] > 0 and st["weight"] > 0 \
                and self.model.game != "jump":
            self.gone = st["dead"] = True       # it was alive a moment ago
        if not st["dead"]:
            self.watch(st)

        if st["dead"]:
            if not self.dead_logged:
                self.log("Das Tamagotchi ist gestorben.")
                self.dead_logged = True
            return self.new_life() if self.restart else None
        self.dead_logged = False

        if not self.model.care or self.model.game == "jump":
            # The clock of a new one is set once; whether a pet has died is not known here
            m = self.tama.memory
            if st["leaving"]:
                # Its time is over. On the way to Lucky Unchi-Kun the next generation follows;
                # otherwise the farewell is left to the user (B, then A and C for a new one)
                # unless the bot has been told to begin again
                if self.restart or (self.goal == self.model.growth.LUCKY and self.generation < 4):
                    return self.farewell()
                if not self.leaving_logged:
                    self.leaving_logged = True
                    self.log("Seine Zeit ist um: B verabschiedet es, danach A und C für ein neues")
                return None
            self.leaving_logged = False
            if st["stage"] == 0:
                if m(MEM_HOUR_HI) * 16 + m(MEM_HOUR_LO) == UNSET_HOUR and now > 3:
                    return self.set_clock()
                return None
            return self.plan_angel(st, now) if self.model.care else None

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
