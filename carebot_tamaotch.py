"""Care-Bot for the Tamaotch (Tamaotch, 1998).

Another program once more: it keeps its state in the upper half of the RAM, wants a button
held for a third of a second before it takes it, and has a sensor for knocks on the case.

Three meters have to be kept from running empty: hunger, happiness and training. Fifteen
minutes after one of them has emptied a care mistake is counted, and another every fifteen
minutes for as long as it stays empty. The training meter only rises in the training games.

The training games (three of them, all played alike): three times in a row the player
strikes three poses with A and B, the pet strikes them after him, and if its third pose is
the right one the player knocks on the case (else he presses A). The first two poses it
always gets right. The third it does not copy at all: it takes it from the device's
seconds, A in an odd second and B in an even one. So the bot waits for a second to begin
and strikes the pose that goes with it; that way every round is won.

The sensor is read in bursts on the fast clock of the MCU, which look for two edges within
a fraction of a millisecond. A knock is therefore a rattle: a third of a second of edges 61
microseconds apart.
"""
import time

from carebot import CareBot
from tama import BTN_A, BTN_B, BTN_C, BTN_TAP

# RAM cells of the Tamaotch ROM (found by experiment, one 4-bit value each)
MEM_SECOND = 0x102                      # seconds, 0 to 9 round and round
MEM_MIN_LO, MEM_MIN_HI = 0x104, 0x105   # clock minutes, BCD
MEM_HOUR_LO, MEM_HOUR_HI = 0x106, 0x107  # clock hours, 0 to 11: bit 0 of the high cell is
                                        # the ten, bit 3 says afternoon
MEM_STATE = 0x120                       # what is on the screen, see below
MEM_WEIGHT_LO, MEM_WEIGHT_HI = 0x154, 0x155  # BCD, grams
MEM_REELS = (0x1A1, 0x1A2, 0x1A3)       # slot machine: the picture on each reel, 0 to 5
MEM_PHASE = 0x1A0                       # training game: 1 it wants the poses, 8 it asks
MEM_RIGHT = 0x1A4                       # training game: third poses it got right so far
MEM_WAKE_LO, MEM_WAKE_HI = 0x1C2, 0x1C3  # the hour it wakes at (the high cell is the ten)
MEM_SLEEP_LO, MEM_SLEEP_HI = 0x1C6, 0x1C7  # the hour it goes to sleep, as the clock's hour
MEM_CHARACTER = 0x1D8                   # 1 Ashitchi ... (growth_tamaotch.py)
MEM_EVOLVE_LO, MEM_EVOLVE_HI = 0x1DC, 0x1DD  # hours until it changes
MEM_HUNGER, MEM_HAPPY = 0x1E0, 0x1E1    # hearts, 0 to 4
MEM_TRAINING = 0x1E3                    # the training meter, 0 to 4
MEM_WON_TODAY = 0x1E5                   # training games won since midnight
MEM_GAMES = (0x1E8, 0x1E6, 0x1E7)       # games won of each kind, less the least of the three
MEM_FANS = 0x1E9                        # its popularity: one less at midnight, more for a
                                        # knock on the case while it gets its shot
MEM_ILL_LO, MEM_ILL_HI = 0x1EA, 0x1EB   # hours until it falls ill (a snack takes one off)
MEM_CURE = 0x1ED                        # 0 well; else what the cure still takes (4 a shot)
MEM_MISSED = 0x1F2                      # calls to be told off that were missed
MEM_MISTAKES = 0x1F7                    # care mistakes as this character
MEM_CALLS = 0x1FA                       # bits 0 and 1 it wants the light off, bit 3 it
                                        # wants to be told off
MEM_POOP = 0x1FD                        # droppings

# MEM_STATE
BOOT, SETTING, HATCHING, HOME, CLOCK = 0, 1, 3, 4, 6
STAGE, STUCK = 0, 1     # with a pet there: it is on stage; it takes no button until knocked
FOOD, MEDICINE, SCOLDING, SLOT, TOILET, STATUS, TRAINING, ASLEEP = 7, 8, 9, 0xA, 0xB, 0xD, 0xE, 0xF

ICON_SLOT = 2
ICON_FOOD, ICON_TRAINING, ICON_TOILET, ICON_MEDICINE, ICON_LIGHT, ICON_SCOLD = 1, 3, 4, 5, 6, 7
MEAL, SNACK, FAN_LETTER = 0, 1, 2       # the entries of the food menu

HOLD = 0.35             # seconds a button has to be held
RATTLE = 0.3            # seconds of rattling that make a knock
RATTLE_TICKS = 2        # ticks between two edges of it
SEVEN = 3               # the reels' picture that is worth three hearts
GAMES_A_DAY = 12        # training games won in a day: one more after these overworks it
LEAD = 2                # how far ahead the game that is to count is kept
FANS = 3                # the popularity to keep where it has to be high (from 2 on it is)
SNACKS = 14             # snacks within two hours that take time off its health
NAMES = {0: "Ei"}       # filled from the growth chart once the characters are known


class TamaotchBot(CareBot):
    def __init__(self, tama, log=print, discipline=True, feed_below=3, play_below=3, model=None):
        super().__init__(tama, log, discipline, feed_below, play_below, model)
        self.next_game = self.next_knock = self.next_light = 0.0
        self.game = 0                   # the training game to play (0 to 2)
        self.fans = True                # make it popular (knock while it gets its shot)
        self.bad = 0                    # care mistakes to make as every character
        self.snacked = (0.0, 0)         # since when, and how many snacks to fall ill

    def weight(self):
        m = self.tama.memory
        return m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO)

    def dark(self):
        """The light is off: the whole screen is black then."""
        return sum(1 for p in self.tama.frame()[0] if p) > 400

    def clock(self):
        m = self.tama.memory
        hour = (m(MEM_HOUR_HI) & 1) * 10 + m(MEM_HOUR_LO) + (12 if m(MEM_HOUR_HI) & 8 else 0)
        return hour, m(MEM_MIN_HI) * 10 + m(MEM_MIN_LO)

    def status(self):
        m = self.tama.memory
        state = m(MEM_STATE)
        stage = m(MEM_CHARACTER) if self.weight() else 0
        names = getattr(self.model.growth, "NAMES", None) or self.model.names
        hour, minute = self.clock()
        return {
            "stage": stage,
            "away": False, "praying": False, "sickness": 0, "leaving": False, "thanked": False,
            "generation": None,
            "name": names.get(stage, "Tamaotch %d" % stage),
            "hunger": m(MEM_HUNGER),
            "happy": m(MEM_HAPPY),
            "weight": self.weight(),
            "poop": m(MEM_POOP),
            "mistakes": m(MEM_MISTAKES),
            "missed": m(MEM_MISSED),
            "fans": m(MEM_FANS),
            "training": m(MEM_TRAINING), "meter": m(MEM_TRAINING),
            "games": [m(a) for a in MEM_GAMES],
            "won_today": m(MEM_WON_TODAY),
            "kind": 0,
            "sick": m(MEM_CURE) > 0,
            "ill_in": m(MEM_ILL_HI) * 16 + m(MEM_ILL_LO),
            "asleep": state == ASLEEP,
            "attack": False,
            "cocoon": False, "temperature": None, "friendship": None, "sweetness": None,
            "look": None, "back": False,
            "light": not self.dark(),
            "attention": bool(m(MEM_CALLS) & 8),
            "scold": bool(m(MEM_CALLS) & 8),
            "dead": False,
            "game": None,
            "screen": state,
            "clock": "%02d:%02d" % (hour, minute),
        }

    # -- primitives ---------------------------------------------------------

    def step(self):
        """As in CareBot, but the time is taken after the task has run: the knock and the
        wait for a second to begin run the emulator themselves."""
        tama = self.tama
        if tama.seconds < self.wake:
            return
        if self.task is None:
            self.task = self.plan()
            if self.task is None:
                self.wake = tama.seconds + 1.0
                return
        try:
            wait = next(self.task)
        except StopIteration:
            self.task = None
            self.manual = False
            wait = 1.0
        self.wake = tama.seconds + wait

    def press(self, btn, pause=0.6):
        self.held = btn
        self.tama.button(btn, True)
        yield HOLD
        self.tama.button(btn, False)
        self.held = None
        yield pause

    def knock(self):
        """A knock on the case. The sensor wants edges faster than the bot is called, so
        the rattle is run here in one go."""
        tama = self.tama
        for _ in range(int(RATTLE * 32768 / (2 * RATTLE_TICKS))):
            tama.button(BTN_TAP, True)
            tama.run(RATTLE_TICKS)
            tama.button(BTN_TAP, False)
            tama.run(RATTLE_TICKS)

    def at_icon(self):
        icons = self.tama.frame()[1]
        for i in range(8):
            if icons[i]:
                return i
        return None

    def home(self):
        """Back to the plain pet screen: C leaves a menu, B the clock."""
        m = self.tama.memory
        for _ in range(6):
            state = m(MEM_STATE)
            if state == CLOCK:
                yield from self.press(BTN_B, 1.5)
            elif state not in (HOME, ASLEEP) or self.at_icon() is not None:
                yield from self.press(BTN_C, 1.0)
            else:
                break

    def select(self, icon):
        for _ in range(10):
            if self.at_icon() == icon:
                return True
            yield from self.press(BTN_A, 0.6)
        return False

    def open(self, icon, state):
        """Walk to an icon and confirm it; True if its screen came up."""
        yield from self.home()
        if not (yield from self.select(icon)):
            return False
        yield from self.press(BTN_B, 1.5)
        return self.tama.memory(MEM_STATE) == state

    # -- actions -------------------------------------------------------------

    def set_clock(self):
        """A fresh device shows three eggs: B opens the clock, A sets the hour and B the
        minute, C takes it and another B lets an egg hatch."""
        m = self.tama.memory
        self.log("Uhr stellen")
        if m(MEM_STATE) == BOOT:
            yield from self.press(BTN_B, 1.5)
        t = time.localtime()
        for _ in range(26):
            if m(MEM_STATE) != SETTING or self.clock()[0] == t.tm_hour:
                break
            yield from self.press(BTN_A, 0.5)
        for _ in range(62):
            if m(MEM_STATE) != SETTING or self.clock()[1] == t.tm_min:
                break
            yield from self.press(BTN_B, 0.5)
        if m(MEM_STATE) == SETTING:
            yield from self.press(BTN_C, 1.5)
        if m(MEM_STATE) == CLOCK:
            yield from self.press(BTN_B, 1.5)
        self.clock_set_at = self.tama.seconds

    def eat(self, entry):
        """One helping from the food menu. Returns whether it went down."""
        before = self.tama.memory(MEM_HUNGER), self.tama.memory(MEM_HAPPY), self.weight()
        if not (yield from self.open(ICON_FOOD, FOOD)):
            yield from self.home()
            return False
        for _ in range(entry):
            yield from self.press(BTN_A, 0.6)
        yield from self.press(BTN_B, 9.0)
        yield from self.home()
        return (self.tama.memory(MEM_HUNGER), self.tama.memory(MEM_HAPPY), self.weight()) != before

    def feed(self):
        m = self.tama.memory
        self.log("Füttern (Hunger %d/4)" % m(MEM_HUNGER))
        for _ in range(4):
            if m(MEM_HUNGER) >= 4 or not (yield from self.eat(MEAL)):
                break

    def sweets(self):
        m = self.tama.memory
        self.log("Snack (Glück %d/4)" % m(MEM_HAPPY))
        for _ in range(4):
            if m(MEM_HAPPY) >= 4 or not (yield from self.eat(SNACK)):
                break

    def reel(self, cell, value):
        """Run until a reel has just come to a picture."""
        m, tama = self.tama.memory, self.tama
        for _ in range(4000):
            if m(cell) != value:
                break
            tama.run(33)
        for _ in range(4000):
            if m(cell) == value:
                break
            tama.run(33)

    def slot(self):
        """The slot machine, for happiness without the weight of snacks. A stops the first
        reel and B the second, each one picture after the press; the third the pet stops
        itself, and it matches when the first two do. Three sevens are three hearts."""
        m = self.tama.memory
        self.log("Einarmiger Bandit (Glück %d/4)" % m(MEM_HAPPY))
        if not (yield from self.open(ICON_SLOT, SLOT)):
            yield from self.home()
            return
        self.reel(MEM_REELS[0], (SEVEN + 1) % 6)
        yield from self.press(BTN_A, 1.0)
        self.reel(MEM_REELS[1], (m(MEM_REELS[0]) + 1) % 6)
        yield from self.press(BTN_B, 6.0)
        yield from self.home()

    def hours(self):
        """(hours until it goes to sleep, hours its night lasts), from the character's own
        times."""
        m = self.tama.memory
        wake = m(MEM_WAKE_HI) * 10 + m(MEM_WAKE_LO)
        sleep = (m(MEM_SLEEP_HI) & 1) * 10 + m(MEM_SLEEP_LO) + (12 if m(MEM_SLEEP_HI) & 8 else 0)
        return (sleep - self.clock()[0]) % 24, (wake - sleep) % 24

    def fall_ill(self, why):
        """Snacks until it is about to fall ill. Every snack takes an hour off the time it
        stays well (no more than 14 of them in two hours do). It is made ill for two
        reasons: so that it does not fall ill in its sleep, when nobody can give it its
        shot (six hours of that and it is overworked), and because being cured is what
        makes it popular."""
        m = self.tama.memory
        now = self.tama.seconds
        if now - self.snacked[0] >= 7200:
            self.snacked = (now, 0)
        self.log(why)
        while self.snacked[1] < SNACKS:
            if m(MEM_CURE) or m(MEM_ILL_HI) * 16 + m(MEM_ILL_LO) <= 1:
                break
            if not (yield from self.eat(SNACK)):
                break
            self.snacked = (self.snacked[0], self.snacked[1] + 1)

    def unstick(self):
        self.log("Klopfen: es nimmt keine Taste an")
        self.knock()
        yield 5.0

    def clean(self):
        self.log("Toilette")
        yield from self.home()
        if (yield from self.select(ICON_TOILET)):
            yield from self.press(BTN_B, 8.0)
        yield from self.home()

    def heal(self):
        """Shots until it is well. A knock on the case while it gets one is what makes it
        popular."""
        m = self.tama.memory
        self.log("Medizin")
        for _ in range(5):
            if not m(MEM_CURE):
                break
            yield from self.home()
            if not (yield from self.select(ICON_MEDICINE)):
                break
            yield from self.press(BTN_B, 4.0)
            if self.wish(self.status())[2] and m(MEM_FANS) < FANS + 1 and m(MEM_STATE) == MEDICINE:
                self.knock()
            yield 5.0
        yield from self.home()

    def light(self, on, why=None):
        self.log(why or ("Licht an" if on else "Licht aus"))
        yield from self.home()
        if (yield from self.select(ICON_LIGHT)):
            yield from self.press(BTN_B, 1.5)   # the menu: on, off
            yield from self.press(BTN_A, 1.0)
            yield from self.press(BTN_B, 3.0)
        yield from self.home()

    def scold(self, why="Schimpfen"):
        self.log(why)
        yield from self.home()
        if (yield from self.select(ICON_SCOLD)):
            yield from self.press(BTN_B, 8.0)
        yield from self.home()

    def train(self, game):
        """One training game, all three rounds of it won (see the top of this file)."""
        m = self.tama.memory
        tama = self.tama
        self.log("Übungsspiel %d (Übung %d/4)" % (game + 1, m(MEM_TRAINING)))
        if not (yield from self.open(ICON_TRAINING, TRAINING)):
            yield from self.home()
            return
        for _ in range(game):
            yield from self.press(BTN_A, 0.8)
        yield from self.press(BTN_B, 3.0)
        for _ in range(3):
            waited = 0.0
            while m(MEM_STATE) == TRAINING and m(MEM_PHASE) != 1 and waited < 30:
                yield 0.1
                waited += 0.1
            if m(MEM_STATE) != TRAINING or m(MEM_PHASE) != 1:
                break
            had = m(MEM_RIGHT)
            yield from self.press(BTN_A, 1.2)
            yield from self.press(BTN_B, 1.2)
            # the third pose on the stroke of a second: it will strike A in an odd one
            second = m(MEM_SECOND)
            for _ in range(3000):
                if m(MEM_SECOND) != second:
                    break
                tama.run(33)
            yield from self.press(BTN_A if m(MEM_SECOND) & 1 else BTN_B, 1.2)
            waited = 0.0
            while m(MEM_STATE) == TRAINING and m(MEM_PHASE) != 8 and waited < 25:
                yield 0.05
                waited += 0.05
            if m(MEM_STATE) != TRAINING or m(MEM_PHASE) != 8:
                break
            if m(MEM_RIGHT) > had:
                self.knock()
            else:
                yield from self.press(BTN_A, 0.2)
            yield 1.0
        waited = 0.0
        while m(MEM_STATE) == TRAINING and waited < 40:
            yield 0.2
            waited += 0.2
        yield 3.0
        yield from self.home()

    # -- decision -------------------------------------------------------------

    def wish(self, st):
        """What to do as this character: (care mistakes to make, the game that is to be
        ahead, whether to be popular, the characters still to come)."""
        rules = self.model.growth
        if self.goal is None or rules is None or st["stage"] == 0:
            return self.bad, self.game, self.fans, None
        way = rules.route(self.goal, st["stage"], rules.lead(st["games"]), st["fans"] >= rules.POPULAR)
        if not way:
            # there (or out of reach): keep it what it is, if anything does
            keep = rules.stay(st["stage"]) if way == [] else None
            if keep:
                return (0 if keep[0] else rules.GOOD + 1), keep[1], keep[2], way
            return 0, rules.lead(st["games"]) or 0, False, way
        _, good, game, popular = way[0]
        rest = [w[0] for w in way[1:]] + [self.goal]
        return (0 if good else rules.GOOD + 1), game, popular, rest

    def pick(self, st, want):
        """The training game to play next. The one that is to count is kept a little
        ahead, and no more: the counts end at 15, and a lead as long as that could not be
        caught up within the life of the next character. The counts are kept less the
        least of them, so a win in the game that is behind takes one off the others."""
        games = st["games"]
        others = [g for i, g in enumerate(games) if i != want]
        if games[want] >= max(others) and games[want] - max(others) < LEAD:
            return want
        low = min(games)
        return want if games[want] == low else games.index(low)

    def growth(self, st):
        rules = self.model.growth
        if rules is None or st["stage"] == 0:
            return None
        mistakes, game, popular, rest = self.wish(st)
        return {
            "forecast": rules.forecast(st["stage"], st["mistakes"], st["games"], st["fans"]),
            "reachable": rules.reachable(st["stage"]),
            "plan": rest,
            "wanted": {"mistakes": mistakes, "game": game, "popular": popular},
        }

    def watch(self, st):
        seen = st["stage"], st["mistakes"]
        if self.counted and st["stage"] > 0:
            stage, mistakes = self.counted[:2]
            if stage != st["stage"] and stage > 0:
                self.log("Verwandelt in " + st["name"])
            elif st["mistakes"] > mistakes:
                self.log("Pflegefehler gezählt (jetzt %d)" % st["mistakes"])
        self.counted = seen

    def plan(self):
        m = self.tama.memory
        st = self.status()
        now = self.tama.seconds
        state = st["screen"]
        if not self.weight():
            if state in (BOOT, SETTING, CLOCK) and now > 3 and now >= self.clock_check:
                self.clock_check = now + 20
                return self.set_clock()
            return None
        self.watch(st)
        if state == STAGE:
            return None                     # its performance: nothing to do
        if state == STUCK:
            if now >= self.next_knock:
                self.next_knock = now + 30
                return self.unstick()
            return None
        if st["asleep"]:
            if st["light"] and now >= self.next_light:
                self.next_light = now + 60
                return self.light(False)
            return None
        if state != HOME:
            return self.home()
        if st["sick"]:
            return self.heal()
        if st["poop"] > 0:
            return self.clean()
        bad, game, popular, _ = self.wish(st)
        if st["mistakes"] < bad:
            # care mistakes on purpose: no food until enough have been counted (one a
            # quarter of an hour once the hearts are gone)
            if not self.ignoring:
                self.ignoring = True
                self.log("Pflegefehler mit Absicht: es bleibt hungrig (%d von %d)" % (st["mistakes"], bad))
        else:
            self.ignoring = False
            if st["hunger"] < self.feed_below:
                return self.feed()
        to_sleep, night = self.hours()
        budget = now - self.snacked[0] >= 7200 or self.snacked[1] < SNACKS
        if 1 < to_sleep <= 3 and 1 < st["ill_in"] < night + 2 + to_sleep and budget:
            return self.fall_ill("Snacks, damit es noch vor der Nacht krank wird (statt im Schlaf)")
        if popular and st["fans"] < FANS and to_sleep > 2 and st["ill_in"] > 1 and budget:
            return self.fall_ill("Snacks, damit es krank wird: gesund gepflegt gewinnt es Fans (%d)" % st["fans"])
        if st["happy"] < self.play_below:
            return self.slot()
        if st["scold"] and self.discipline:
            return self.scold()
        if st["won_today"] < GAMES_A_DAY and now >= self.next_game:
            games = st["games"]
            behind = games[game] - max(g for i, g in enumerate(games) if i != game) < LEAD
            if st["training"] < 2 or (behind and st["training"] < 4):
                self.next_game = now + 60
                return self.train(self.pick(st, game))
        return None
