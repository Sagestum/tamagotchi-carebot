"""Care-Bot for the Mothra (Mothra no Tamagotch) and the Genjintch.

Another program again: nothing sits where the P1 or the Umino have it. It sleeps between
its pictures and only a button wakes it, it attacks a tower and wants to be told off for
that, and it turns food down while it is ill. Built on the buttons and the scheduler of
carebot.py.

The Genjintch runs the same program with other characters: it makes pottery instead of
attacking a tower and wants to be praised for it. Every cell sits where the Mothra has it;
what differs is in the growth modules (growth_mothra.py, growth_genjin.py).
"""
import time

from carebot import CareBot, CLOCK_TOLERANCE, PRESS, PAUSE
from tama import BTN_A, BTN_B, BTN_C

# RAM cells of the Mothra ROM (found by experiment, one 4-bit value each)
MEM_FLAGS = 0x05                        # bit 0 ill, bit 2 asleep
MEM_LIGHT = 0x06                        # asleep: bit 0 the light is still on; bit 3 it calls
MEM_POOP = 0x07                         # droppings on the screen
MEM_GAME = 0x0A                         # in the game: 3 intro, 4 waiting for the pick, 5 the
                                        # hole opens (the cell serves other screens as well)
MEM_CHARACTER = 0x0B                    # 0 the egg ... (growth_mothra.py), 15 dead
MEM_STATE = 0x0C                        # 0 awake, 1 the egg waits, 5 a nap, 6 asleep,
                                        # 8 and 9 it attacks the tower, 10 and 11 ill
MEM_GENERATION = 0x16                   # generations in a row that were a flawless Mothra Leo
                                        # (kept when a new egg is begun; growth_mothra.py)
MEM_SEC_LO, MEM_SEC_HI = 0x1A, 0x1B     # clock seconds, BCD
MEM_MIN_LO, MEM_MIN_HI = 0x1C, 0x1D     # clock minutes, BCD
MEM_HOUR, MEM_PM = 0x1E, 0x1F           # 1 to 12 and whether it is afternoon; 0 if unset
MEM_ARROW = 0x23                        # a menu of two: 1 the first entry, 2 the second
MEM_MISTAKES = 0x37                     # care mistakes as this character
MEM_JUSTICE = 0x3B                      # the Justice meter, 0 to 4
MEM_HAPPY, MEM_HUNGER = 0x3D, 0x3E      # hearts, 0 to 4
MEM_HOLE = 0x50                         # game: the hole the arrow is at
MEM_WEIGHT_LO, MEM_WEIGHT_HI = 0x56, 0x57  # BCD, tons
MEM_SNACKS = 0x62                       # snacks eaten as this character, in threes (0x3C
                                        # counts the single ones)
MEM_ILLNESS = 0x6B                      # how easily this character falls ill, 1 to 15
MEM_DESTINED = 0x63                     # in the cocoon: the character that will come out
MEM_OLD = 0x76                          # 2 once it is old enough to leave an egg when it dies
MEM_ROUNDS = 0x9B                       # game: rounds still to come

FLAG_SICK, FLAG_ASLEEP = 1, 4
SAFE_SUM = 14           # MEM_ILLNESS and MEM_SNACKS together: at this it does not fall ill
CLOCK_M = ("........", ".###.##.", ".##.#.#.", ".##.#.#.")     # the M of AM and PM
CLOCK_SET = (".##..###.###", "#..#.#....#.", "#....#....#.")  # the top of the word SET
SETTLE = 90             # seconds to wait after a heart has gone before doing anything about it
DEAD = 15


class MothraBot(CareBot):
    def __init__(self, tama, log=print, discipline=True, feed_below=3, play_below=3, model=None):
        super().__init__(tama, log, discipline, feed_below, play_below, model)
        self.neglecting = False         # a care mistake is being made on purpose
        self.hearts = (None, 0.0)       # (hunger and happiness last seen, since when)
        self.letting_go = None          # why this one is left to die (the twins take generations)

    # -- state readers -----------------------------------------------------

    def weight(self):
        m = self.tama.memory
        return m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO)

    def status(self):
        m = self.tama.memory
        stage = m(MEM_CHARACTER)
        dead = stage == DEAD
        self.gone = dead
        if dead:
            stage = 0
        flags = m(MEM_FLAGS)
        alive = stage > 0
        return {
            "stage": stage,
            "away": False, "praying": False, "sickness": 0, "leaving": False, "thanked": False,
            "generation": m(MEM_GENERATION),
            "snacks": m(MEM_SNACKS) * 3 + m(0x3C) % 3,
            "old": alive and m(MEM_OLD) >= 2,
            "name": self.model.stage_name(stage),
            "hunger": m(MEM_HUNGER),
            "happy": m(MEM_HAPPY),
            "weight": self.weight(),
            "poop": m(MEM_POOP),
            "mistakes": m(MEM_MISTAKES),
            "missed": 0,
            "meter": m(MEM_JUSTICE),                    # as the rules count it
            "training": min(4, m(MEM_JUSTICE) * 4 // self.model.growth.FULL),   # in quarters
            "kind": 0,
            "sick": alive and bool(flags & FLAG_SICK),
            "asleep": alive and bool(flags & FLAG_ASLEEP),
            "attack": False,
            "cocoon": stage == self.model.growth.COCOON,
            "destined": m(MEM_DESTINED) if stage == self.model.growth.COCOON else None,
            "temperature": None, "friendship": None, "sweetness": None,
            "look": None, "back": False,
            # the light only counts while it sleeps; in the morning it comes on by itself
            "light": not flags & FLAG_ASLEEP or bool(m(MEM_LIGHT) & 1),
            "attention": alive and bool(self.tama.frame()[1][7]),
            "scold": alive and m(MEM_STATE) in self.model.growth.CALLING,   # it wants an answer
            "dead": dead,
            "game": None,
            "clock": "%02d:%d%d" % (self.hour(), m(MEM_MIN_HI), m(MEM_MIN_LO)),
        }

    # -- primitives ---------------------------------------------------------

    def at_icon(self):
        return self.screen().selected()

    def clock_up(self):
        return self.screen().region(2, 12, 8, 4) == CLOCK_M

    def setting(self):
        """The clock is being set: the word SET stands where the seconds were."""
        return self.clock_up() and self.screen().region(18, 9, 12, 3) == CLOCK_SET

    def home(self):
        """Back to the plain pet screen: C leaves a menu and the game and ends the setting
        of the clock, B leaves the clock. Right after a change no button is taken."""
        for _ in range(6):
            if self.clock_up():
                yield from self.press(BTN_C if self.setting() else BTN_B, 1.5)
            elif self.at_icon() is not None:
                yield from self.press(BTN_C, 0.8)
            else:
                break

    def goto(self, icon):
        for _ in range(3):
            if self.at_icon() == icon:
                break
            yield from self.home()
            yield from self.select(icon)

    # -- the clock ----------------------------------------------------------

    def hour(self):
        m = self.tama.memory
        return m(MEM_HOUR) % 12 + 12 * (m(MEM_PM) & 1)

    def minute(self):
        return self.tama.memory(MEM_MIN_HI) * 10 + self.tama.memory(MEM_MIN_LO)

    def unset(self):
        return self.tama.memory(MEM_HOUR) == 0

    def device_time(self):
        m = self.tama.memory
        return self.hour() * 3600 + self.minute() * 60 + m(MEM_SEC_HI) * 10 + m(MEM_SEC_LO)

    def dial(self):
        """In clock-set mode: A the hour, B the minute, C on the minute (see carebot.py)."""
        if not self.setting():
            return False
        for _ in range(3):
            goal = time.time()
            if self.realtime:
                t = time.localtime(goal)
                presses = (t.tm_hour - self.hour()) % 24 + (t.tm_min + 1 - self.minute()) % 60
                goal = (goal + 10 + presses * (PRESS + PAUSE) * 1.2) // 60 * 60 + 60
            t = time.localtime(goal)
            if self.unset():
                yield from self.press(BTN_A)    # a clock never set: one press gives it an hour
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
                        return False
            if not self.realtime or time.time() < goal:
                break
        while self.realtime and time.time() < goal:
            yield 0.05
        yield from self.press(BTN_C, 2.0)
        return True

    def set_clock(self):
        """A fresh egg: it only starts hatching once the clock has been set."""
        self.log("Uhr stellen")
        if not self.setting():
            yield from self.home()
            yield from self.press(BTN_B, 1.5)
        if (yield from self.dial()):
            self.clock_set_at = self.tama.seconds
        yield from self.home()

    def sync_clock(self, error):
        self.log("Uhr nachstellen (ging %d s %s)" % (abs(error), "vor" if error > 0 else "nach"))
        yield from self.home()
        yield from self.press(BTN_B, 1.5)       # B shows the clock
        for _ in range(3):
            if not self.clock_up() or self.setting():
                break
            self.tama.button(BTN_A, True)       # A and C together: set mode
            self.tama.button(BTN_C, True)
            self.held = (BTN_A, BTN_C)
            yield 0.3
            self.tama.button(BTN_A, False)
            self.tama.button(BTN_C, False)
            self.held = None
            yield 1.5
        if self.setting():
            yield from self.dial()
            yield 1.0
        yield from self.home()

    # -- actions -------------------------------------------------------------

    def eat(self, snack):
        """One helping. Returns whether it was taken."""
        m = self.tama.memory
        before = (m(MEM_HAPPY) if snack else m(MEM_HUNGER)), self.weight()
        yield from self.home()
        if not (yield from self.select(self.model.icon("food"))):
            return False
        yield from self.press(BTN_B, 0.8)
        for _ in range(3):
            if m(MEM_ARROW) == (2 if snack else 1):
                break
            yield from self.press(BTN_A)
        yield from self.press(BTN_B, 8.0)
        yield from self.home()
        return ((m(MEM_HAPPY) if snack else m(MEM_HUNGER)), self.weight()) != before

    def feed(self, meals=4):
        m = self.tama.memory
        self.log("Füttern (Hunger %d/4)" % m(MEM_HUNGER))
        for _ in range(meals):
            if m(MEM_HUNGER) >= 4 or m(MEM_FLAGS) & (FLAG_SICK | FLAG_ASLEEP) \
                    or m(MEM_STATE) in self.model.growth.CALLING:
                break
            if not (yield from self.eat(False)):
                break

    def sweets(self, why, count=1, until=None):
        m = self.tama.memory
        self.log(why)
        for _ in range(count):
            if m(MEM_FLAGS) & (FLAG_SICK | FLAG_ASLEEP) \
                    or m(MEM_STATE) in self.model.growth.CALLING \
                    or (until and until()):
                break
            yield from self.eat(True)

    def play(self, why=None):
        """Five rounds: the Mothra hides in one of four holes, A moves the arrow and B
        picks. Three rounds found fill a heart and take a ton off, all five two."""
        m = self.tama.memory
        self.log(why or "Spielen (Glück %d/4)" % m(MEM_HAPPY))
        yield from self.home()
        if not (yield from self.select(self.model.icon("game"))):
            return
        yield from self.press(BTN_B, 0.3)
        rounds, waited = 0, 0.0
        while rounds < 5 and waited < 30:
            yield 0.1
            waited += 0.1
            if m(MEM_GAME) == 4:
                yield 0.3
                yield from self.press(BTN_B, 0.3)
                for _ in range(100):
                    if m(MEM_GAME) != 4:
                        break
                    yield 0.1
                rounds += 1
                waited = 0.0
            elif rounds and self.at_icon() is None:
                break
        for _ in range(150):            # the result, then the pet again
            if self.at_icon() is None:
                break
            yield 0.1
        yield 2.0
        yield from self.home()

    def clean(self):
        self.log("Saubermachen")
        yield from self.home()
        if (yield from self.select(self.model.icon("toilet"))):
            yield from self.press(BTN_B, 6.0)
        yield from self.home()

    def heal(self):
        """Moll and Lora sing. It takes two visits, sometimes more."""
        self.log("Medizin geben")
        for _ in range(4):
            yield from self.home()
            if not (yield from self.select(self.model.icon("medicine"))):
                return
            yield from self.press(BTN_B, 10.0)
            yield from self.home()
            if not self.tama.memory(MEM_FLAGS) & FLAG_SICK:
                break

    def light(self, on, why=None):
        """Only ever needed to put the light out for the night. Where the arrow of this
        menu stands is not in a cell the bot knows (RAM 0x23 is the food menu's and stays
        where the last meal left it), so look at the result and try the other entry."""
        m = self.tama.memory
        self.log(why or ("Licht an" if on else "Licht aus"))
        for attempt in range(4):
            yield from self.home()
            if not (yield from self.select(self.model.icon("light"))):
                return
            yield from self.press(BTN_B, 0.8)
            if attempt % 2:
                yield from self.press(BTN_A)
            yield from self.press(BTN_B, 2.0)
            yield from self.home()
            if bool(m(MEM_LIGHT) & 1) == on or not m(MEM_FLAGS) & FLAG_ASLEEP:
                break

    def scold(self, why=None):
        """Answer the call that fills the meter: telling the Mothra off at the tower,
        praising the Genjintch at its pottery. The fifth icon on both."""
        praise = "praise" in self.model.icons
        self.log(why or ("Loben" if praise else "Schimpfen"))
        yield from self.home()
        if (yield from self.select(self.model.icon("praise" if praise else "discipline"))):
            yield from self.press(BTN_B, 8.0)
        yield from self.home()

    def fresh(self):
        m = self.tama.memory
        return m(MEM_CHARACTER) == 0

    # -- decision -------------------------------------------------------------

    def wish(self, st):
        """What the goal asks of the present character: (care mistakes to reach, the
        characters to come) or None."""
        if self.goal is None or st["stage"] == 0:
            return None
        return self.model.growth.plan(self.goal, st["stage"], st["mistakes"], st["meter"])

    def let_go(self, st):
        """The twins and Lucky Haka-Kun take several lives (growth_mothra.py). Returns why
        this one has to end, or None if it is to be cared for."""
        rules = self.model.growth
        if self.goal not in rules.GENERATIONS or st["stage"] in (0, rules.COCOON):
            return None
        stage, count = st["stage"], st["generation"]
        if stage == rules.HAKA or (stage == rules.MOLL_LORA and self.goal == rules.MOLL_LORA):
            return None                     # there it is
        if stage == rules.MOLL_LORA:        # on the way to Lucky Haka-Kun: the next egg
            return "Generation %d ist alt genug: Sie macht dem nächsten Ei Platz" % count \
                if st["old"] else None
        if stage == rules.LEO and st["old"]:
            # 75 waking hours are over: it has been counted, or it has not
            if count == 0:
                return "Mothra Leo wurde nicht gezählt (Gewicht oder Pflegefehler): neuer Anlauf"
            return "Mothra Leo ist gezählt (Generation %d): Er macht dem nächsten Ei Platz" % count
        if not rules.flawless(stage, st["mistakes"]):
            return "Aus diesem Tier wird kein fehlerfreier Mothra Leo mehr: neuer Anlauf"
        return None

    def weight_wish(self, st):
        """Genjintch: (weight, whether to hold it or to keep away from it), or None."""
        wish = getattr(self.model.growth, "weight_goal", None)
        return wish(self.goal, st["stage"]) if wish and self.goal else None

    def growth(self, st):
        if st["dead"]:
            return None
        rules = self.model.growth
        way = self.wish(st)
        alive = st["stage"] > 0
        if st["cocoon"]:
            forecast = [st["destined"]]
        else:
            more = (st["weight"],) if hasattr(rules, "weight_goal") else ()
            forecast = rules.forecast(st["stage"], st["mistakes"], st["meter"], *more) \
                if alive else []
        return {
            "forecast": forecast,
            "reachable": rules.reachable(st["stage"], st["mistakes"], st["meter"]),
            "plan": way[1] if way else None,
            "wanted": {"mistakes": way[0], "justice": rules.FULL,
                       "weight": self.weight_wish(st)} if way else None,
        }

    def watch(self, st):
        seen = st["stage"], st["mistakes"], st["meter"]
        if self.counted and st["stage"] > 0:
            stage, mistakes, justice = self.counted
            if stage != st["stage"] and stage > 0:
                self.log("Verwandelt in " + st["name"])
            elif st["mistakes"] > mistakes:
                self.log("Pflegefehler gezählt (jetzt %d)" % st["mistakes"])
        self.counted = seen

    def plan(self):
        st = self.status()
        now = self.tama.seconds
        if st["dead"]:
            if not self.dead_logged:
                self.log("Das Tamagotchi ist gestorben.")
                self.dead_logged = True
                self.counted = None
            # on the way to the twins the next egg is part of the plan
            again = self.restart or self.letting_go is not None
            return self.new_life() if again else None
        if st["stage"] == 0:
            self.letting_go = None
        self.dead_logged = False
        if st["stage"] == 0:
            # Egg: it hatches five minutes after the clock has been set
            self.counted = (0, 0, 0)
            if (self.unset() or self.setting()) and now > 3 and now >= self.clock_check:
                self.clock_check = now + 20
                return self.set_clock()
            return None
        self.watch(st)
        if st["cocoon"]:
            return None             # an hour in which nothing can be done

        if st["asleep"]:
            # It calls for the light to be put out; in the morning it comes on by itself
            if st["light"]:
                if self.light_wish is None:
                    self.light_wish = (False, now)
                elif now - self.light_wish[1] >= 5:
                    self.light_wish = None
                    return self.light(False)
            return None
        self.light_wish = None
        if st["sick"]:
            return self.heal()

        # It attacks the tower: telling it off fills a quarter of the Justice. Every
        # character calls only as often as its meter has room, so none may be missed
        if st["scold"]:
            # Fairy and Mayura turn into Ghogo and Godzilla once their Justice is full
            # and no mistake has been made. If they are the goal, the calls are left alone
            rules = self.model.growth
            stay = self.goal == st["stage"] and rules.adult(st["stage"], 0, rules.FULL) \
                and not getattr(rules, "STAY_BY_MISTAKES", False)
            answer = getattr(rules, "answer", None)
            if answer and self.goal and not answer(self.goal, st["stage"]):
                # Genjintch: only a Genjintchi that was never praised goes back to Ukitchi
                if not self.ignoring:
                    self.ignoring = True
                    self.log("Töpfern wird nicht gelobt, damit es wieder Ukitchi wird")
                return None
            if stay and not self.ignoring:
                self.ignoring = True
                self.log("Turmangriff wird übergangen, damit es %s bleibt" % st["name"])
            if (self.goal is not None or self.discipline) and not stay:
                return self.scold()
            return None
        self.ignoring = False

        # The tower attacks begin in the minute in which a heart goes, and a game or a
        # meal begun just then swallows the call: the Justice it would have brought is
        # lost for good. So wait a moment after every heart before doing something
        hearts = st["hunger"], st["happy"]
        if self.hearts[0] != hearts:
            self.hearts = (hearts, now)
        settled = now - self.hearts[1] >= SETTLE

        # The twins: a life that has done its part, or cannot do it any more, is left
        # hungry until it dies. It is still healed and cleaned: only a death of care
        # mistakes leaves an egg that keeps the count
        why = self.let_go(st)
        if why:
            if self.letting_go != why:
                self.letting_go = why
                self.log(why)
            return self.clean() if st["poop"] > 0 and settled else None
        self.letting_go = None

        way = self.wish(st)
        mistakes_goal = way[0] if way else st["mistakes"]
        neglect = st["mistakes"] < mistakes_goal        # a care mistake is wanted
        if not settled:
            return None
        if st["poop"] > 0:
            return self.clean()

        # A care mistake on purpose: let the hunger run out and leave the call alone until
        # the ROM has counted it (a quarter of an hour)
        if neglect:
            if not self.neglecting:
                self.neglecting = True
                self.log("Pflegefehler mit Absicht: es bleibt hungrig (%d von %d)"
                         % (st["mistakes"], mistakes_goal))
            if st["happy"] < self.play_below and st["hunger"] > 0:
                return self.play()
            return None
        self.neglecting = False
        # Genjintch: a weight to be at when the change comes (Gaikotchi), or to stay away
        # from. A meal adds 1 kg, a game takes 1 or 2 off: at the weight, feed and play as
        # late as the hearts allow, and put right at once what a meal or a game has moved
        wish = self.weight_wish(st)
        held = wish and wish[1] and st["weight"] == wish[0]
        if st["hunger"] < (2 if held else self.feed_below):
            return self.feed(1 if wish and wish[1] else 4)
        # The fourth illness as the same character is its death, and at one exact count
        # of snacks it does not fall ill at all (growth_mothra.py). Eat up to there in
        # one go: on the way the chance is at its highest. The baby is over in an hour
        rules = self.model.growth
        m = self.tama.memory
        safe = SAFE_SUM - m(MEM_ILLNESS) if st["stage"] > rules.BABY else 0
        # (not the Mothra Leo of the twins: he needs his few snacks for his weight, and
        # with few he rarely falls ill in the six days he has)
        twin = self.goal in rules.GENERATIONS and st["stage"] == rules.LEO
        if safe > 0 and m(MEM_SNACKS) < safe and not twin:
            return self.sweets("Snacks, bis es nicht mehr krank wird (%d von %d)"
                               % (st["snacks"], safe * 3), count=12,
                               until=lambda: m(MEM_SNACKS) >= safe)
        # Mothra Leo has to weigh 70 to 79 t when his 75 waking hours are over. A game
        # takes 1 or 2 t off, a snack adds 2
        if twin:
            low, high = rules.TWIN_WEIGHT
            if st["weight"] > high - 2:
                return self.play("Spielen, damit er %d bis %d t wiegt (%d t)" % (low, high, st["weight"]))
            if st["weight"] < low + 3:
                return self.sweets("Snack, damit er %d bis %d t wiegt (%d t)" % (low, high, st["weight"]))
        if wish:
            goal_weight, wanted = wish
            unit = self.model.unit
            if wanted and st["weight"] > goal_weight:
                return self.play("Spielen, damit es %d %s wiegt (%d %s)"
                                 % (goal_weight, unit, st["weight"], unit))
            if wanted and st["weight"] < goal_weight and st["hunger"] < 4:
                return self.feed(1)     # every meal is a kilo
            if wanted and st["weight"] < goal_weight - 1 \
                    and m(MEM_SNACKS) != safe:
                return self.sweets("Snack, damit es %d %s wiegt (%d %s)"
                                   % (goal_weight, unit, st["weight"], unit))
            if not wanted and st["weight"] == goal_weight:
                return self.play("Spielen, damit es nicht %d %s wiegt" % (goal_weight, unit))
        if st["happy"] < (2 if held else self.play_below):
            return self.play()

        if self.realtime and st["stage"] >= 2 and now >= self.clock_check:
            self.clock_check = now + 600
            error = self.clock_error()
            if abs(error) > CLOCK_TOLERANCE:
                return self.sync_clock(error)
        return None
