"""Care-Bot for the Digimon (Digital Monster Ver. 1 to 3).

Its program is of the Mothra's family: the clock, the hearts, the weight and the character
sit where carebot_mothra.py has them, so this bot is built on that one. What differs is
here: other counters decide what it becomes (growth_digimon.py), strength comes from
vitamins instead of a game, it is trained, and it fights. The fights are held against an
opponent that is not there (link.py): it begins and then reports its own defeat, which the
device confirms and counts as a win.

The three versions differ in their characters and in the training: Ver. 1 strikes high or
low at its shadow, Ver. 2 stops a bar that runs up at its top, Ver. 3 fills the bar by
pressing fast. Some characters ask for overfeeding and for being woken at night; the bot
does both on purpose when the goal needs it.
"""
import link
from carebot import CLOCK_TOLERANCE
from carebot_mothra import (MothraBot, MEM_FLAGS, MEM_POOP, MEM_CHARACTER, MEM_STATE,
                            MEM_ARROW, MEM_HAPPY, MEM_GAME, FLAG_SICK, FLAG_ASLEEP, DEAD)
from tama import BTN_A, BTN_B, BTN_C

# RAM cells that the Digimon has of its own (found by experiment)
MEM_DARK = 0x08                         # bit 3: the light is off
MEM_MISTAKES = 0x31                     # care mistakes as this character
MEM_OVERFED = 0x32                      # times it was fed until it turned the meat down
MEM_DISTURBED = 0x33                    # times it was woken from its sleep
MEM_TRAINING_LO, MEM_TRAINING_HI = 0x34, 0x35   # +2 for every training
MEM_FULL_LO, MEM_FULL_HI = 0x3E, 0x3F   # how full it is, BCD: 4 hearts from 4 on, up to 24
MEM_STRENGTH = MEM_HAPPY                # hearts, 0 to 4
MEM_WINS = 0x90                         # fights won in its life, two digits (0x91 the tens)
MEM_FIGHTS = 0x94                       # fights in its life, two digits (0x95 the tens)
MEM_SCORE = 0x98                        # fights won that count for the next change, up to 15
MEM_FOUGHT = 0x99                       # fights that count for the next change, up to 15
MEM_ROUNDS = 0x9B                       # training: rounds still to come

HOLD = 0.3              # seconds a button is held: shorter presses are lost now and then
ABOUT = 0x24DB          # the word a rookie sends about itself: the opponent's is the same
SPAR_PAUSE = 20 * 60    # seconds between two fights
BAR_ROW, BAR_FULL = 12, 14      # the power bar of the training: its LCD row and its length
BAR_LEAD = 46 / 1000    # Ver. 2: seconds from the bar showing one short of full to the press
                        # that stops it full (40 to 52 ms do it; later it has run over)
MASH = 0.06             # Ver. 3: seconds a button is held, and let go, to fill the bar


class DigimonBot(MothraBot):
    def __init__(self, tama, log=print, discipline=True, feed_below=3, play_below=3, model=None):
        super().__init__(tama, log, discipline, feed_below, play_below, model)
        self.about = ABOUT              # what it said about itself in its last fight
        self.next_fight = 0.0
        self.neglecting = None          # the care mistakes there were when it began to go hungry
        self.silent = None              # since when it has been empty without calling
        self.next_training = 0.0
        self.next_wake = 0.0

    # -- state readers -----------------------------------------------------

    def fullness(self):
        m = self.tama.memory
        return m(MEM_FULL_HI) * 10 + m(MEM_FULL_LO)

    def trainings(self):
        m = self.tama.memory
        return (m(MEM_TRAINING_HI) * 16 + m(MEM_TRAINING_LO)) // self.model.growth.TRAINING_STEP

    def status(self):
        m = self.tama.memory
        st = super().status()
        alive = st["stage"] > 0
        st.update({
            "hunger": min(4, self.fullness()),
            "happy": m(MEM_STRENGTH),
            "mistakes": m(MEM_MISTAKES),
            "meter": self.trainings(),
            "training": 0,
            "trainings": self.trainings(),
            "overfed": m(MEM_OVERFED),
            "disturbed": m(MEM_DISTURBED),
            "fights": m(MEM_FIGHTS + 1) * 10 + m(MEM_FIGHTS),
            "wins": m(MEM_WINS + 1) * 10 + m(MEM_WINS),
            "fought": m(MEM_FOUGHT),
            "score": m(MEM_SCORE),
            "light": not m(MEM_DARK) & 8,
            "scold": False, "cocoon": False, "destined": None, "generation": None,
            "attention": alive and bool(self.tama.frame()[1][7]),
        })
        return st

    # -- primitives ---------------------------------------------------------

    def press(self, btn, pause=0.5):
        self.held = btn
        self.tama.button(btn, True)
        yield HOLD
        self.tama.button(btn, False)
        self.held = None
        yield pause

    # -- actions -------------------------------------------------------------

    def eat(self, vitamin):
        """One helping. In a menu of two RAM 0x0A is the arrow: 1 the first entry (meat,
        light on), 2 the second. Returns whether it was taken."""
        m = self.tama.memory
        before = m(MEM_STRENGTH), self.fullness(), self.weight(), m(0x3C)
        yield from self.home()
        if not (yield from self.select(self.model.icon("food"))):
            return False
        yield from self.press(BTN_B, 1.0)
        for _ in range(3):
            if m(MEM_GAME) == (2 if vitamin else 1):
                break
            yield from self.press(BTN_A, 0.6)
        yield from self.press(BTN_B, 7.0)
        yield from self.home()
        return (m(MEM_STRENGTH), self.fullness(), self.weight(), m(0x3C)) != before

    def feed(self, meals=4):
        self.log("Füttern (Hunger %d/4)" % min(4, self.fullness()))
        for _ in range(meals):
            if self.fullness() >= 4 or self.tama.memory(MEM_FLAGS) & (FLAG_SICK | FLAG_ASLEEP):
                break
            if not (yield from self.eat(False)):
                break

    def morsel(self):
        """One helping of whatever is empty, between two care mistakes on purpose."""
        m = self.tama.memory
        self.log("Ein Happen, damit es wieder rufen kann")
        if self.fullness() < 1:
            yield from self.eat(False)
        if m(MEM_STRENGTH) < 1:
            yield from self.eat(True)

    def vitamins(self):
        m = self.tama.memory
        self.log("Vitamine (Stärke %d/4)" % m(MEM_STRENGTH))
        for _ in range(4):
            if m(MEM_STRENGTH) >= 4 or m(MEM_FLAGS) & (FLAG_SICK | FLAG_ASLEEP):
                break
            if not (yield from self.eat(True)):
                break

    def light(self, on, why=None):
        """A menu of two: on and off (the arrow is RAM 0x0A, as in the food menu)."""
        m = self.tama.memory
        self.log(why or ("Licht an" if on else "Licht aus"))
        for attempt in range(4):
            yield from self.home()
            if not (yield from self.select(self.model.icon("light"))):
                return
            yield from self.press(BTN_B, 1.0)
            if m(MEM_GAME) != (1 if on else 2) or attempt >= 2:
                yield from self.press(BTN_A, 0.6)
            yield from self.press(BTN_B, 2.5)
            yield from self.home()
            if (not m(MEM_DARK) & 8) == on:
                break

    def train(self):
        """One training. It takes a gram off. On Ver. 1 it counts whether won or not, on the
        later ones only when won."""
        self.log("Training (%d bisher)" % self.trainings())
        yield from self.home()
        if not (yield from self.select(self.model.icon("training"))):
            return
        yield from self.press(BTN_B, 1.5)
        yield from {"bar": self.train_bar, "mash": self.train_mash}.get(
            self.model.growth.TRAINING, self.train_shadow)()
        yield from self.home()

    def train_shadow(self):
        """Ver. 1: five rounds against its own shadow, A strikes high, B low."""
        m = self.tama.memory
        rounds, waited = 0, 0.0
        while rounds < 5 and waited < 20:
            yield 0.1
            waited += 0.1
            if m(MEM_GAME) == 4:
                yield 0.3
                yield from self.press(BTN_A if rounds % 2 else BTN_B, 0.5)
                for _ in range(100):
                    if m(MEM_GAME) != 4:
                        break
                    yield 0.1
                rounds += 1
                waited = 0.0
        yield 12.0

    def bar(self):
        """How far the power bar of the training is filled, 0 to BAR_FULL."""
        pixels = self.tama.frame()[0]
        return sum(1 for p in pixels[BAR_ROW * 32:BAR_ROW * 32 + 32] if p) - 2

    def train_bar(self):
        """Ver. 2: the bar runs up again and again, in three quarters of a second; a button
        stops it, and only a full bar breaks the block. The device takes the press a moment
        late, so it is given while the bar still shows one short of full. That takes
        milliseconds, so this part runs here in slices of one instead of at the pace of
        the bot."""
        m = self.tama.memory
        for _ in range(200):                # the bar is there, and low
            if m(MEM_GAME) == 2 and 0 <= self.bar() < BAR_FULL - 4:
                break
            yield 0.05
        else:
            return
        for _ in range(3000):
            self.tama.run(32)
            if self.bar() == BAR_FULL - 1:
                break
        else:
            return
        self.tama.run(int(BAR_LEAD * 32768))
        yield from self.press(BTN_A, 8.0)   # it strikes, and the bar comes back
        yield from self.press(BTN_C, 1.0)   # leave it at this one

    def train_mash(self):
        """Ver. 3: five seconds to fill the bar by pressing fast."""
        m = self.tama.memory
        for _ in range(400):
            if m(MEM_GAME) != 2:
                break
            self.held = BTN_B
            self.tama.button(BTN_B, True)
            yield MASH
            self.tama.button(BTN_B, False)
            self.held = None
            yield MASH
        yield 12.0

    def overfeed(self):
        """Meat until it turns it down: that is counted once, and again only after it has
        lost a heart."""
        m = self.tama.memory
        before = m(MEM_OVERFED)
        self.log("Überfüttern mit Absicht (%d bisher)" % before)
        for _ in range(self.model.growth.OVERFED_AT + 4):
            if m(MEM_OVERFED) != before or m(MEM_FLAGS) & (FLAG_SICK | FLAG_ASLEEP):
                break
            yield from self.eat(False)

    def disturb(self):
        """Wake it from its sleep: a helping of meat does that."""
        self.log("Wecken mit Absicht (%d Schlafstörungen bisher)" % self.tama.memory(MEM_DISTURBED))
        yield from self.eat(False)

    def battle_screen(self):
        """Open the battle screen, where it waits for an opponent. A baby shakes its head."""
        yield from self.home()
        if not (yield from self.select(self.model.icon("battle"))):
            return False
        yield from self.press(BTN_B, 1.2)
        return True

    def exchange(self, begin, answer, call=False):
        """The words of a fight. The answers have to come within a few milliseconds, so
        this runs here in slices of one millisecond instead of at the pace of the bot.
        begin: the word to open with, or None if the device opens (call: with A).
        answer(n, word): what to send back to its n-th word, or None for nothing.
        Returns the words the device sent."""
        reader, words = link.Reader(), []
        self.tama.link_edges()              # forget what was on the pin before
        if begin is not None:
            self.tama.link_wave(link.wave(begin, 10))
        if call:
            self.tama.button(BTN_A, True)
        for ms in range(4000):
            if call and ms == 300:
                self.tama.button(BTN_A, False)
            self.tama.run(32)
            for word in reader.feed(self.tama.link_edges()):
                words.append(word)
                back = answer(len(words), word)
                if back is not None:
                    self.tama.link_wave(link.wave(back))
            if len(words) >= 2 and ms > 3000:
                break
        if call:
            self.tama.button(BTN_A, False)
        return words

    def spar(self):
        """A fight that is won: the opponent that is not there sends its word, takes the
        device's, and reports its own defeat."""
        if not (yield from self.battle_screen()):
            self.log("Sparring: das Kampf-Menü ist nicht erreichbar")
            return
        words = self.exchange(self.about, lambda n, word: link.framed(link.LOST) if n == 1 else None)
        if len(words) < 2:
            # now and then it does not take the call; a hurt one never does
            self.log("Sparring: kein Kampf zustande gekommen")
            self.next_fight = self.tama.seconds + 60
            yield from self.home()
            return
        self.about = words[0]
        self.log("Sparring: " + ("gewonnen" if link.won(words[1]) else "verloren")
                 + " (%d Kämpfe, %d Siege)" % (self.status()["fights"], self.status()["wins"]))
        yield 30.0                          # the fight is shown
        yield from self.home()

    # A fight between two Digimon of the user's. Each of them runs in a process of its own,
    # so their pins are not joined: the words are carried from one to the other, one fight
    # in three steps. The device that calls works out who wins; the other takes its word.

    TRIES = 6       # a word is not taken now and then, as between two real devices

    def fights(self):
        m = self.tama.memory
        return m(MEM_FIGHTS + 1) * 10 + m(MEM_FIGHTS)

    def fought(self, before):
        """Wait for the device to count the fight it has just agreed on; it does so while
        it shows it. Returns whether it did."""
        for _ in range(30):
            if self.fights() != before:
                return True
            yield 1.0
        return False

    def ready(self):
        """Before a fight: a hurt one does not take the call."""
        if self.tama.memory(MEM_FLAGS) & FLAG_SICK:
            yield from self.heal()

    def duel_word(self, tell):
        """Step 1, the guest: what it says about itself. It calls, nobody answers, and
        nothing is counted."""
        for _ in range(self.TRIES):
            yield from self.ready()
            if not (yield from self.battle_screen()):
                break
            words = self.exchange(None, lambda n, word: None, call=True)
            yield 8.0
            yield from self.home()
            if words:
                self.about = words[0]
                return tell(words[0])
        tell(None)

    def duel_host(self, about, name, tell):
        """Step 2, the host: it calls, is answered with the guest's word and says how the
        fight ends. Only a fight that it has counted is passed on."""
        for _ in range(self.TRIES):
            yield from self.ready()
            before = self.fights()
            if not (yield from self.battle_screen()):
                break
            words = self.exchange(
                None, lambda n, word: about if n == 1 else link.other(word) if n == 2 else None,
                call=True)
            if len(words) >= 2 and (yield from self.fought(before)):
                self.about = words[0]
                self.log("Kampf gegen %s: %s" % (name, "gewonnen" if link.won(words[1]) else "verloren"))
                tell(words[:2])
                yield 20.0
                yield from self.home()
                return
            yield from self.home()
            yield 5.0
        self.log("Kampf gegen %s: nicht zustande gekommen" % name)
        tell(None)

    def duel_guest(self, about, outcome, name):
        """Step 3, the guest: it is called with the host's word and told how it ended."""
        for _ in range(self.TRIES):
            yield from self.ready()
            before = self.fights()
            if not (yield from self.battle_screen()):
                break
            words = self.exchange(about, lambda n, word: outcome if n == 1 else None)
            if len(words) >= 2 and (yield from self.fought(before)):
                self.log("Kampf gegen %s: %s" % (name, "gewonnen" if link.won(words[1]) else "verloren"))
                yield 20.0
                yield from self.home()
                return
            yield from self.home()
            yield 5.0
        self.log("Kampf gegen %s: bei diesem Gerät nicht angekommen" % name)

    def request(self, task):
        """The user asked for something the bot does with its own hands."""
        self.stop()
        self.task = task
        self.manual = True

    def request_spar(self):
        """The user asked for a fight."""
        self.request(self.spar())

    # -- decision -------------------------------------------------------------

    def wish(self, st):
        if self.goal is None or st["stage"] == 0:
            return None
        return self.model.growth.plan(self.goal, *self.counters(st))

    def counters(self, st):
        """What the growth rules ask about."""
        return st["stage"], st["mistakes"], st["trainings"], st["overfed"], st["disturbed"]

    def growth(self, st):
        if st["dead"]:
            return None
        rules = self.model.growth
        way = self.wish(st)
        alive = st["stage"] > 0
        return {
            "forecast": rules.forecast(*self.counters(st)) if alive else [],
            "reachable": rules.reachable(*self.counters(st)),
            "plan": way["way"] if way else None,
            "wanted": {k: way[k] for k in ("mistakes", "trainings", "overfed", "disturbed",
                                           "battles")} if way else None,
        }

    def chart(self):
        """The growth chart of this version, for the page that shows it."""
        rules = self.model.growth
        return {"version": rules.VERSION, "names": rules.NAMES, "rows": rules.ROWS,
                "training": rules.TRAINING}

    def memo(self):
        return {"about": self.about}

    def recall(self, memo):
        if isinstance(memo, dict) and isinstance(memo.get("about"), int):
            self.about = memo["about"]

    def plan(self):
        st = self.status()
        now = self.tama.seconds
        rules = self.model.growth
        if st["dead"]:
            if not self.dead_logged:
                self.log("Das Digimon ist gestorben.")
                self.dead_logged = True
                self.counted = None
            return self.new_life() if self.restart else None
        self.dead_logged = False
        if st["stage"] == 0:
            self.counted = (0, 0, 0)
            if (self.unset() or self.setting()) and now > 3 and now >= self.clock_check:
                self.clock_check = now + 20
                return self.set_clock()
            return None
        self.watch(st)

        way = self.wish(st) or {"mistakes": st["mistakes"], "trainings": 0, "overfed": 0,
                                "disturbed": 0, "battles": 0}
        if st["asleep"]:
            if st["disturbed"] < way["disturbed"] and not st["sick"] and now >= self.next_wake:
                self.next_wake = now + 300
                return self.disturb()
            if st["light"]:
                if self.light_wish is None:
                    self.light_wish = (False, now)
                elif now - self.light_wish[1] >= 5:
                    self.light_wish = None
                    return self.light(False)
            return None
        self.light_wish = None
        if not st["light"]:
            return self.light(True)
        if st["sick"]:
            return self.heal()
        if st["poop"] > 0:
            return self.clean()

        if st["mistakes"] < way["mistakes"]:
            # A care mistake on purpose: no food until the call has run out (19 minutes).
            # It calls once only, and a day with empty hearts is its death, so after every
            # mistake it gets one helping of each, enough to call again soon
            if self.neglecting is None:
                self.neglecting = st["mistakes"]
                self.log("Pflegefehler mit Absicht: es bleibt hungrig (%d von %d)"
                         % (st["mistakes"], way["mistakes"]))
            if st["mistakes"] == self.neglecting:
                # empty and not calling: the helping did not go down, or the call is over
                # without a mistake. Left like that it would only starve
                if (st["hunger"] == 0 or st["happy"] == 0) and not st["attention"]:
                    if self.silent is None:
                        self.silent = now
                    elif now - self.silent > 25 * 60:
                        self.silent = None
                        return self.morsel()
                else:
                    self.silent = None
                return None
            self.neglecting = self.silent = None
            return self.morsel()
        self.neglecting = None
        if st["overfed"] < way["overfed"] and self.fullness() <= rules.FULL:
            return self.overfeed()
        if st["hunger"] < self.feed_below:
            return self.feed()
        if st["happy"] < self.play_below:
            return self.vitamins()

        if st["trainings"] < way["trainings"] and now >= self.next_training:
            self.next_training = now + 60
            return self.train()
        # The last stage needs fights as a rookie and a good score at both changes. Each
        # fight may leave it hurt, so there is a pause between two
        fighter = st["stage"] in rules.FIGHTERS
        if fighter and now >= self.next_fight and (
                st["fought"] < way["battles"]
                or (way["battles"] and st["score"] < rules.WINS)):
            self.next_fight = now + SPAR_PAUSE
            return self.spar()

        if self.realtime and st["stage"] >= 2 and now >= self.clock_check:
            self.clock_check = now + 600
            error = self.clock_error()
            if abs(error) > CLOCK_TOLERANCE:
                return self.sync_clock(error)
        return None
