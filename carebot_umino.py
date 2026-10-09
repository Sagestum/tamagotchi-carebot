"""Care-Bot for the Umino (Umi de Hakken! Tamagotch, the Tamagotchi Ocean).

Its program keeps everything in other RAM cells than the P1 family, and its care has
more to it: the water gets dirty by itself, a polar bear lies in wait, an octopus
breaks into the game, and what it is fed decides whether it falls ill. So it has a bot
of its own, built on the buttons and the scheduler of carebot.py.
"""
import time

from carebot import CareBot, CLOCK_TOLERANCE, PRESS, PAUSE
from tama import BTN_A, BTN_B, BTN_C

# RAM cells of the Umino ROM (found by experiment, one 4-bit value each)
MEM_SEC_LO, MEM_SEC_HI = 0x11, 0x12     # clock seconds, BCD
MEM_MIN_LO, MEM_MIN_HI = 0x13, 0x14     # clock minutes, BCD
MEM_SHOWN_LO, MEM_SHOWN_HI = 0x15, 0x16  # the hour as the clock shows it, 12 hours; 00 if unset
MEM_HOUR_LO, MEM_HOUR_HI = 0x17, 0x18   # clock hours, BCD, 0 to 23
MEM_ENEMY = 0x6B                        # 5 while the pet dozes and something lies in wait
MEM_ARROW = 0x6E                        # a menu of two: 0 the first entry, 4 the second
MEM_FLAGS = 0x70                        # bit 2 ill or hurt, bit 3 asleep; 1 dead
MEM_CALL = 0x71                         # it calls although nothing is missing: tell it off
MEM_CURSOR = 0x72                       # the menu icon the cursor is at, 15 none
MEM_FOOD = 0x74                         # food menu: 0 the meal, 1 the snack (it stays there)
MEM_GAME = 0x75                         # game: 1 intro, 2 waiting for the press, 3 won, 4 lost
MEM_LIGHT = 0x78                        # 0 on, 1 off
MEM_AGE = 0x79
MEM_WEIGHT_LO, MEM_WEIGHT_HI = 0x7B, 0x7C  # BCD, grams; a new egg weighs nothing
MEM_DISCIPLINE = 0x7D                   # the meter on the status screen, 0 to 7
MEM_HUNGER, MEM_HAPPY = 0x7E, 0x7F      # hearts, 0 to 4
MEM_WATER = 0x80                        # skulls on the status screen, 0 clean to 4 black
MEM_SNACKS_LO, MEM_SNACKS_HI = 0x8E, 0x8F  # goes up 2 to 6 with every snack, over 255 to 0
MEM_LUCK = 0x92                         # game: counts on; the press wins while it is even
MEM_POSE = 0xC5                         # 7 together with MEM_ENEMY 5: something lies in wait
MEM_CHARACTER = 0xC6                    # 0 the baby ... 9 the mermaid (growth_umino.py)
MEM_MISTAKES = 0x165                    # care mistakes as this character
MEM_MISSED = 0x166                      # calls to be told off that were left alone

FLAG_SICK, FLAG_ASLEEP, DEAD = 4, 8, 1
LURKING = 40            # seconds the signs must last: Taiyakitchi shows them briefly in passing
SNACKS_SAFE = 10        # with the snack counter below this it does not fall ill
SNACKS_AT_A_TIME = 6
WINNING = (2, 4, 6, 8)  # values of MEM_LUCK at which the press was a win in every trial
HEAVY = 80              # g: play it off before it reaches 99 (unless that is the goal)
CLOCK_M = ("........", "##.###..", "#.#.##..", "#.#.##..")


class UminoBot(CareBot):
    def __init__(self, tama, log=print, discipline=True, feed_below=3, play_below=3, model=None):
        super().__init__(tama, log, discipline, feed_below, play_below, model)
        self.lurk_since = None          # since when something has been lying in wait
        self.lurking = False            # ... for long enough to be sure
        self.neglecting = False         # a care mistake is being made on purpose
        self.octopus = 0
        self.drops = (None, 0, 0.0)     # (character, hunger last seen, when it last fell)
        self.old = False                # the hearts fall every few minutes: it is old
        self.awake = (None, 0.0, 0.0)   # (character, seconds awake as it, when last looked)

    # -- state readers -----------------------------------------------------

    def snacks(self):
        return self.tama.memory(MEM_SNACKS_HI) * 16 + self.tama.memory(MEM_SNACKS_LO)

    def status(self):
        m = self.tama.memory
        flags = m(MEM_FLAGS)
        weight = m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO)
        dead = flags == DEAD
        self.gone = dead
        stage = 0 if dead or weight == 0 else m(MEM_CHARACTER) + 1
        return {
            "stage": stage,
            "away": False, "praying": False, "sickness": 0, "leaving": False, "thanked": False,
            "generation": None,
            "name": self.model.stage_name(stage),
            "hunger": m(MEM_HUNGER),
            "happy": m(MEM_HAPPY),
            "weight": weight,
            "poop": m(MEM_WATER),           # how dirty the water is, 0 to 4
            "mistakes": m(MEM_MISTAKES),
            "missed": m(MEM_MISSED),
            "training": (m(MEM_DISCIPLINE) + 1) // 2,
            "kind": 0,
            "sick": bool(flags & FLAG_SICK) and not dead,
            "asleep": bool(flags & FLAG_ASLEEP) and not dead,
            "attack": self.lurking and stage > 0,
            "cocoon": False, "temperature": None, "friendship": None, "sweetness": None,
            "look": None, "back": False,
            "light": m(MEM_LIGHT) == 0,
            "attention": stage > 0 and bool(m(MEM_CALL) or self.tama.frame()[1][7]),
            "scold": stage > 0 and bool(m(MEM_CALL)),     # it wants to be told off
            "dead": dead,
            "game": None,
            "snacks": self.snacks(),
            "clock": "%d%d:%d%d" % (m(MEM_HOUR_HI), m(MEM_HOUR_LO), m(MEM_MIN_HI), m(MEM_MIN_LO)),
        }

    def step(self):
        # Something lies in wait: only sure once the signs have lasted a while
        m = self.tama.memory
        now = self.tama.seconds
        if m(MEM_ENEMY) == 5 and m(MEM_POSE) == 7 and m(MEM_WEIGHT_HI) + m(MEM_WEIGHT_LO):
            if self.lurk_since is None:
                self.lurk_since = now
            self.lurking = now - self.lurk_since >= LURKING
        else:
            self.lurk_since, self.lurking = None, False
        super().step()

    # -- primitives ---------------------------------------------------------

    def at_icon(self):
        at = self.tama.memory(MEM_CURSOR)
        return None if at == 15 else at

    def clock_up(self):
        return self.screen().region(2, 12, 8, 4) == CLOCK_M

    def home(self):
        """Back to the plain pet screen: C leaves a menu, a game and the clock."""
        for _ in range(5):
            if self.at_icon() is None and not self.tama.memory(MEM_GAME) and not self.clock_up():
                break
            yield from self.press(BTN_C, 0.8)

    def goto(self, icon):
        for _ in range(3):
            if self.at_icon() == icon:
                break
            yield from self.home()
            yield from self.select(icon)

    # -- the clock ----------------------------------------------------------

    def hour(self):
        return self.tama.memory(MEM_HOUR_HI) * 10 + self.tama.memory(MEM_HOUR_LO)

    def minute(self):
        return self.tama.memory(MEM_MIN_HI) * 10 + self.tama.memory(MEM_MIN_LO)

    def unset(self):
        m = self.tama.memory
        return m(MEM_SHOWN_HI) == 0 and m(MEM_SHOWN_LO) == 0

    def device_time(self):
        m = self.tama.memory
        return self.hour() * 3600 + self.minute() * 60 + m(MEM_SEC_HI) * 10 + m(MEM_SEC_LO)

    def dial(self):
        """In clock-set mode: A the hour, B the minute, C on the minute (see carebot.py)."""
        for _ in range(3):
            goal = time.time()
            if self.realtime:
                t = time.localtime(goal)
                presses = (t.tm_hour - self.hour()) % 24 + (t.tm_min + 1 - self.minute()) % 60
                goal = (goal + 10 + presses * (PRESS + PAUSE) * 1.2) // 60 * 60 + 60
            t = time.localtime(goal)
            if self.unset() and t.tm_hour == 0:
                # A clock that has never been set shows 00 and the egg waits: go round once
                yield from self.press(BTN_A)
            for read, btn, want, tries in ((self.hour, BTN_A, t.tm_hour, 30),
                                           (self.minute, BTN_B, t.tm_min, 70)):
                stuck = 0
                for _ in range(tries):
                    before = read()
                    if before == want:
                        break
                    yield from self.press(btn)
                    stuck = stuck + 1 if read() == before else 0    # now and then one is lost
                    if stuck >= 3:
                        return False    # not in set mode after all
            if not self.realtime or time.time() < goal:
                break
        while self.realtime and time.time() < goal:
            yield 0.05
        yield from self.press(BTN_C, 2.0)
        return True

    def finish_clock(self):
        """The egg still shows the clock being set (it stands at second 0): dial again."""
        yield 1.5
        if self.device_time() % 60 == 0:
            yield 1.5
            if self.device_time() % 60 == 0 and (yield from self.dial()):
                self.clock_set_at = self.tama.seconds

    def sync_clock(self, error):
        self.log("Uhr nachstellen (ging %d s %s)" % (abs(error), "vor" if error > 0 else "nach"))
        yield from self.home()
        yield from self.press(BTN_B, 2.0)       # B shows the clock
        for _ in range(3):
            if not self.clock_up():
                break
            self.tama.button(BTN_A, True)
            self.tama.button(BTN_C, True)
            self.held = (BTN_A, BTN_C)
            yield 0.3
            self.tama.button(BTN_A, False)
            self.tama.button(BTN_C, False)
            self.held = None
            yield 1.5
            if self.device_time() % 60 == 0:    # in set mode the clock stands at second 0
                yield 1.5
                if self.device_time() % 60 == 0:
                    yield from self.dial()
                    yield 1.0
                    break
        yield from self.home()

    # -- actions -------------------------------------------------------------

    def eat(self, snack):
        """One helping. Returns whether it was taken."""
        m = self.tama.memory
        before = self.snacks() if snack else m(MEM_HUNGER)
        weight = m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO)
        yield from self.home()
        if not (yield from self.select(self.model.icon("food"))):
            return False
        yield from self.press(BTN_B, 0.8)
        for _ in range(3):
            if m(MEM_FOOD) == (1 if snack else 0):
                break
            yield from self.press(BTN_A)
        yield from self.press(BTN_B, 8.0)
        yield from self.home()
        after = self.snacks() if snack else m(MEM_HUNGER)
        return after != before or m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO) != weight

    def feed(self):
        m = self.tama.memory
        self.log("Füttern (Hunger %d/4)" % m(MEM_HUNGER))
        for _ in range(4):
            if m(MEM_HUNGER) >= 4 or m(MEM_FLAGS) & (FLAG_SICK | FLAG_ASLEEP):
                break
            if not (yield from self.eat(False)):
                break               # it turns the food down: it wants to be told off first

    def sweets(self, why, count=SNACKS_AT_A_TIME, until=None):
        m = self.tama.memory
        self.log(why)
        for _ in range(count):
            if m(MEM_FLAGS) & (FLAG_SICK | FLAG_ASLEEP) or (until and until()):
                break
            if not (yield from self.eat(True)):
                break

    def play(self, why=None):
        """Five rounds: whichever button, the press wins while RAM 0x92 is even. Three
        rounds won fill a heart; every game takes a gram off. Now and then an octopus
        breaks in: it blackens the water and takes all the happiness."""
        m = self.tama.memory
        self.log(why or "Spielen (Glück %d/4)" % m(MEM_HAPPY))
        water = m(MEM_WATER)
        yield from self.home()
        if not (yield from self.select(self.model.icon("game"))):
            return
        yield from self.press(BTN_B, 0.3)
        rounds, waited = 0, 0.0
        while rounds < 5 and waited < 45:
            yield 1 / 32
            waited += 1 / 32
            if m(MEM_GAME) == 2 and m(MEM_LUCK) in WINNING:
                self.held = BTN_A
                self.tama.button(BTN_A, True)
                yield 0.1
                self.tama.button(BTN_A, False)
                self.held = None
                for _ in range(60):
                    yield 1 / 16
                    if m(MEM_GAME) in (3, 4):
                        rounds += 1
                        break
                for _ in range(200):
                    if m(MEM_GAME) not in (3, 4):
                        break
                    yield 1 / 16
                waited = 0.0
        if rounds == 5:
            for _ in range(160):        # the next game begins by itself: leave it
                yield 1 / 16
                if m(MEM_GAME) in (1, 2):
                    break
        yield from self.home()
        if m(MEM_WATER) == 4 and water < 4:
            self.octopus += 1
            self.log("Ein Krake hat das Wasser geschwärzt")

    def clean(self):
        self.log("Wasser wechseln (Stufe %d von 4)" % self.tama.memory(MEM_WATER))
        yield from self.home()
        if (yield from self.select(self.model.icon("toilet"))):
            yield from self.press(BTN_B, 8.0)
        yield from self.home()

    def heal(self):
        self.log("Medizin geben")
        for _ in range(4):
            yield from self.home()
            if not (yield from self.select(self.model.icon("medicine"))):
                return
            yield from self.press(BTN_B, 8.0)
            yield from self.home()
            if not self.tama.memory(MEM_FLAGS) & FLAG_SICK:
                break

    def light(self, on, why=None):
        self.log(why or ("Licht an" if on else "Licht aus"))
        yield from self.home()
        if not (yield from self.select(self.model.icon("light"))):
            return
        yield from self.press(BTN_B, 0.6)
        for _ in range(3):
            if (self.tama.memory(MEM_ARROW) == 0) == on:
                break
            yield from self.press(BTN_A)
        yield from self.press(BTN_B, 1.5)
        yield from self.home()

    def scold(self, why="Schimpfen"):
        self.log(why)
        yield from self.home()
        if (yield from self.select(self.model.icon("discipline"))):
            yield from self.press(BTN_B, 12.0)      # it sulks for a while and takes nothing
        yield from self.home()

    def drive_off(self):
        """A polar bear (or whatever hunts this one) lies in wait while the pet dozes. Any
        button wakes it and the hunter leaves. A alone does it; the calling box would
        count as answering a call."""
        self.log("Fressfeind vertrieben")
        yield from self.press(BTN_A, 4.0)
        yield from self.home()

    def fresh(self):
        m = self.tama.memory
        return m(MEM_CHARACTER) == 0 and m(MEM_FLAGS) == 0 \
            and m(MEM_WEIGHT_HI) + m(MEM_WEIGHT_LO) == 0

    # -- decision -------------------------------------------------------------

    def wish(self, st):
        """What the goal asks of the present character: (care mistakes and missed calls to
        reach, weight and water to have when it changes, the characters to come) or None."""
        rules = self.model.growth
        if self.goal is None or st["stage"] == 0:
            return None
        return rules.plan(self.goal, st["stage"], st["mistakes"], st["missed"])

    def hours_left(self, st):
        """Waking hours until this character changes, as far as the bot has seen them."""
        hours = self.model.growth.WAKING_HOURS.get(st["stage"])
        if hours is None or self.awake[0] != st["stage"] or self.awake[1] is None:
            return None
        return hours - self.awake[1] / 3600

    def growth(self, st):
        if st["dead"]:
            return None
        rules = self.model.growth
        way = self.wish(st)
        alive = st["stage"] > 0
        left = self.hours_left(st)
        return {
            "forecast": rules.forecast(st["stage"], st["mistakes"], st["missed"], st["weight"],
                                       st["poop"]) if alive else [],
            "reachable": rules.reachable(st["stage"], st["mistakes"], st["missed"]),
            "plan": way[4] if way else None,
            "wanted": {"mistakes": way[0], "missed": way[1], "weight": way[2], "water": way[3]}
            if way else None,
            "hoursLeft": None if left is None else round(max(0.0, left), 1),
        }

    def watch(self, st):
        seen = st["stage"], st["mistakes"], st["missed"]
        if self.counted and st["stage"] > 0:
            stage, mistakes, missed = self.counted
            if stage != st["stage"] and stage > 0:
                self.log("Verwandelt in " + st["name"])
            elif st["mistakes"] > mistakes:
                self.log("Pflegefehler gezählt (jetzt %d)" % st["mistakes"])
            elif st["missed"] > missed:
                self.log("Ruf verpasst (jetzt %d)" % st["missed"])
        self.counted = seen

    def count_awake(self, st, now):
        """Keep count of the waking time as this character (the changes go by it). Only
        known if the bot has watched it from its first minute."""
        stage, seconds, at = self.awake
        if stage != st["stage"]:
            watched = self.counted is not None and self.counted[0] != st["stage"]
            stage, seconds = st["stage"], 0.0 if watched else None
        elif seconds is not None and not st["asleep"] and 0 < now - at < 900:
            seconds += now - at
        self.awake = (stage, seconds, now)

    def memo(self):
        return list(self.awake[:2])

    def recall(self, memo):
        if isinstance(memo, list) and len(memo) == 2:
            self.awake = (memo[0], memo[1], 0.0)

    def plan(self):
        st = self.status()
        now = self.tama.seconds
        m = self.tama.memory
        rules = self.model.growth
        if st["dead"]:
            if not self.dead_logged:
                self.log("Das Tamagotchi ist gestorben.")
                self.dead_logged = True
                self.counted = None
            return self.new_life() if self.restart else None
        self.dead_logged = False
        if st["stage"] == 0:
            # Egg: it hatches about five minutes after the clock has been set
            self.counted = (0, 0, 0)
            self.awake = (rules.PLANKTONTCHI, 0.0, now)
            if self.unset() and now > 3:
                return self.set_clock()
            if self.device_time() % 60 == 0 and now >= self.clock_check:
                self.clock_check = now + 20
                return self.finish_clock()
            return None
        self.count_awake(st, now)
        # An old one loses a heart every two or three minutes instead of every ten
        stage, hunger, at = self.drops
        if stage != st["stage"]:
            self.old, at = False, 0.0
        elif st["hunger"] < hunger and not st["asleep"]:
            if at and now - at < 240 and st["stage"] > rules.KINGYOTCHI and not self.old:
                self.old = True
                self.log("Es ist alt geworden: Die Herzen fallen jetzt schnell")
            at = now
        self.drops = (st["stage"], st["hunger"], at)
        self.watch(st)

        # At five past five in the morning a carp streamer swims by, if no button is
        # pressed for that minute
        if self.hour() == 5 and 4 <= self.minute() <= 6 and not st["sick"]:
            return None
        if self.lurking:
            return self.drive_off()

        if st["asleep"] != (not st["light"]):
            wanted = not st["asleep"]
            if self.light_wish is None or self.light_wish[0] != wanted:
                self.light_wish = (wanted, now)
            elif now - self.light_wish[1] >= 5:
                self.light_wish = None
                return self.light(wanted)
        else:
            self.light_wish = None
        if st["asleep"] or not st["light"]:
            return None
        if st["sick"]:
            return self.heal()

        way = self.wish(st)
        mistakes_goal, missed_goal, weight_goal, water_goal = way[:4] if way \
            else (st["mistakes"], st["missed"], None, None)
        left = self.hours_left(st)
        hungry, sad = st["hunger"] == 0, st["happy"] == 0
        neglect = st["mistakes"] < mistakes_goal       # a care mistake is wanted
        miss = st["missed"] < missed_goal or (self.goal is None and not self.discipline)

        # RAM 0x71: it calls although nothing is missing. It wants to be told off, and
        # until then it takes neither food nor a game. Left alone the call is counted as
        # missed after a quarter of an hour, or after two hours: it is only worth waiting
        # for while both rows of hearts last.
        if st["scold"]:
            if not miss or hungry or sad:
                self.ignoring = False
                return self.scold("Schimpfen (sonst frisst es nicht)" if miss else "Schimpfen")
            if not self.ignoring:
                self.ignoring = True
                self.log("Ruf wird mit Absicht übergangen" + (
                    " (%d von %d)" % (st["missed"] + 1, missed_goal) if self.goal else ""))
        else:
            self.ignoring = False

        # The water: a skull more about every two hours, black at four. Ashigyotchi needs
        # it black when Kingyotchi changes, so it is left alone for that
        dirty = water_goal is not None and st["stage"] == rules.KINGYOTCHI
        # (an octopus leaves the water black and no happiness at all: the hearts first,
        # an old one does not live long with a row empty)
        if sad and not st["scold"]:
            # for an old one an empty row is the end, and a snack is the quickest heart
            if self.old:
                return self.sweets("Snack, weil kein Glücksherz mehr da ist", count=2)
            if st["hunger"] > 0:
                return self.play()
        if st["poop"] > 0 and not dirty:
            return self.clean()
        if self.ignoring:
            return None

        # Kujiratchi: 99 g when the teenager changes. Snacks weigh most; begin in time
        fatten = weight_goal == rules.HEAVIEST and (left is None or left < 2.5)
        if fatten and st["weight"] < rules.HEAVIEST:
            return self.sweets("Snacks, damit es 99 g wiegt (%d g)" % st["weight"],
                               until=lambda: m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO) >= 99)

        # A care mistake on purpose: let the hunger run out and leave it at that until
        # the ROM has counted (20 to 45 minutes for each)
        if neglect:
            if not self.neglecting:
                self.neglecting = True
                self.log("Pflegefehler mit Absicht: es bleibt hungrig (%d von %d)"
                         % (st["mistakes"], mistakes_goal))
        else:
            self.neglecting = False
            # with a call to miss ahead both rows have to be full when it comes
            if st["hunger"] < (4 if miss or self.old else self.feed_below):
                return self.feed()

        # Every snack moves a hidden counter, and that decides every two and a half
        # hours whether it falls ill; four illnesses as the same character kill it. Near
        # 0 it stays healthy, and the only way there is on over 255.
        if st["snacks"] >= SNACKS_SAFE and not fatten and not neglect \
                and (st["weight"] < HEAVY or st["stage"] not in rules.TEENS):
            return self.sweets("Snacks gegen Krankheit (Zähler %d, sicher unter %d)"
                               % (st["snacks"], SNACKS_SAFE),
                               until=lambda: self.snacks() < SNACKS_SAFE)

        if st["happy"] < (4 if miss or self.old else self.play_below):
            return self.play()
        # Weight: Kaitchi must weigh exactly 10 g to become the mermaid, and a teenager
        # of 99 g becomes Kujiratchi. Otherwise it may weigh what it likes
        if not fatten:
            if weight_goal == rules.MERMAID_WEIGHT and st["weight"] > weight_goal:
                return self.play("Spielen, damit es %d g wiegt (%d g)" % (weight_goal, st["weight"]))
            if st["weight"] >= HEAVY and st["stage"] in rules.TEENS:
                return self.play("Spielen, damit es leichter wird (%d g)" % st["weight"])

        if self.realtime and st["stage"] >= 2 and now >= self.clock_check:
            self.clock_check = now + 600
            error = self.clock_error()
            if abs(error) > CLOCK_TOLERANCE:
                return self.sync_clock(error)
        return None
