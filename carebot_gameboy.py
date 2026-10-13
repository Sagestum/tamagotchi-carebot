"""Care-Bot for the Tamagotchi game on the Game Boy (1997).

The game is a Tamagotchi with more to it: three meals and two snacks, three games, two
medicines, scolding and praising, and two values it hides (growth_gameboy.py). An hour of
its day takes two minutes, so there is always something to do.

What the bot does: light off when it sleeps, the medicine that fits the illness, the
droppings away, the pet's favourite food when a heart is missing, the smile game for its
mood, a scolding whenever it refuses something and praise after a game it has won. It gives
no snacks: two of them make the pet ill. When a pet has died it puts it into the album, takes
the next egg and names it; it keeps as many pets as it is told to (one to three).

With a goal (growth_gameboy.WAYS) it steers what the game hides: it lets refusals pass until
the selfishness is where the goal wants it, it stresses a child that is to become
Kuchitamatchi with the food it dislikes, and it plays the study or the sports game with the
teenager so that it grows up cleverer or stronger.

All cells are in the Game Boy's own memory (0xC000 and on), found by experiment.
"""
import random

import growth_gameboy as rules
from carebot import CareBot
from tama import TICK_HZ
from gameboy import (BTN_A, BTN_B, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_START, BTN_UP)

# The record of the first pet; the second and third follow at 0xD100 and 0xD200. Up to three
# live at a time, each in a room of its own, and one of them is on the screen.
MEM_TYPE = 0xD000           # the character (growth_gameboy.CHARACTERS), 0 none
MEM_DAY = 0xD006            # its age in days of the game
MEM_WEIGHT = 0xD007
MEM_LIFE, MEM_FUN = 0xD008, 0xD009          # hearts, 0 to 4
MEM_BODY, MEM_DEED, MEM_IQ = 0xD00A, 0xD00B, 0xD00C
MEM_POOP = 0xD00E
MEM_NAME = 0xD014           # six letters, 1 for A
MEM_PRAISE = 0xD03D         # counts down (two seconds a step) while praise is called for
MEM_AFTER = 0xD043          # counts once it has died
MEM_FEAR, MEM_MINE = 0xD0C8, 0xD0C9         # stress and selfishness, the hidden ones
MEM_LIGHT_OFF, MEM_ASLEEP = 0xD0CA, 0xD0CB
MEM_SICK = 0xD0CF           # 1 wants the pill, 2 the shot
MEM_DOSES = 0xD0D0          # doses still needed
MEM_SCOLD = 0xD0D6          # counts down while a scolding is called for
MEM_URGE = 0xD0D3           # 1 for the five seconds before its droppings come. A teenager or an
                            # adult goes to the potty if the toilet icon is chosen then: nothing
                            # to clean, and praise is called for (2 while it sits)
MEM_MINUTE, MEM_HOUR = 0xD48F, 0xD490       # the time of day; a minute takes two seconds
RECORD = 0x100
PETS = 3
# The album ("Memory"): eight places in the cartridge's own memory, each the whole record of a
# pet as it was when it died. The place is chosen when the pet is put there.
ALBUM_AT = 0x10000 + 0x1000     # (gameboy.CART_RAM and on)
ALBUM_PLACES = 8
# The program
MEM_EGG = 0xD002            # the egg it came from, 0 to 7 as they stand in the egg room
MEM_HAND = 0xD498           # egg room: the egg the hand is on
MEM_EGGS_USED = 0xD481      # of the eight eggs; with the last pet of the last egg the game
                            # says so and begins anew, with all eight
EGGS = 8
MEM_SLOT = 0xD495           # the pet on the screen, 0 to 2
MEM_SCREEN = 0xCD92
MEM_ICON = 0xD497           # the main screen's cursor: 4 food to 11 the professor; in the
                            # row above them 1 to 3, the pets
MEM_CURSOR = 0xD498         # the entry in a menu; in the name entry the letters typed
MEM_NAME_X, MEM_NAME_Y = 0xD499, 0xD49A
MEM_WINS, MEM_LOSSES = 0xD5BD, 0xD5BE       # of the smile game
MEM_CAUGHT = 0xD5BC         # sports game: balls caught (of ten; five are the goal of level A)
MEM_RIGHT, MEM_WRONG = 0xD5BB, 0xD5BF       # study game: answers
OAM = 0xFE00                # the Game Boy's table of sprites: y, x, tile, flags
SPRITES = 40
BALL_TILES = (100, 102)     # sports game: the ball, and the pet (four tiles wide)
PET_TILES = range(112, 128)
HOP = 12                    # the pet is under the ball if it is no further off than this
MIDDLE = 80                 # where a ball comes down on the middle one of the five places

MAIN, ALBUM, STATUS, FOOD_MENU, LAB, EGG_ROOM, NAME_ENTRY = 0, 2, 3, 4, 5, 6, 7
GAME_MENU, MEDICINE_MENU, SCOLD_MENU, TITLE, WELCOME, SMILE_GAME, INTRO = 9, 10, 11, 12, 14, 29, 46
OPTION = 59                     # the options behind the title: the speed of time and the album
STUDY_LEVEL, STUDY_GAME, SPORTS_LEVEL, SPORTS_GAME = 15, 30, 42, 43
NO_EGGS = 51                        # "No more eggs left": A, and the game begins anew
SMILE, STUDY, SPORTS = 0, 1, 2      # the entries of the game menu
SCOLD, PRAISE = 0, 1                # and of the menu of the discipline icon
STUDY_HOURS = range(10, 17)         # studying early or late in the day stresses it
MEM_PACE = 0xD480               # the game's "Time speed": 0 fast, 1 medium, 2 slow (1, 2, 3 s a minute)
PACES = {0: "schnell", 1: "mittel", 2: "langsam"}
TRAIN_EVERY = 300                   # seconds between two games for IQ or Body, at medium pace
UNEASY, CALM_EVERY = 30, 120        # from this much stress on, a game for the praise, this often
# The contests in the laboratory ("Pick test"): one a day for every pet; an adult that wins is
# given an award, kept in a cell each. Race: the pet runs by itself, and A, which is to spur it
# on, tires it out at once (fastest without). Beauty: won by a pet that is happy and well
# behaved. Knowledge: sums as in the study game. What decides the other two is Body and IQ.
RACE, BEAUTY, KNOWLEDGE = range(3)
CONTESTS = {RACE: "Rennen", BEAUTY: "Schönheit", KNOWLEDGE: "Wissen"}
MEM_AWARD = 0xD003              # +0 race, +1 beauty, +2 knowledge: 1 once it is won
MEM_CONTESTED = 0xD0DC          # 1: it has been in a contest today
MEM_CHANCE = 0xFFF4             # its lowest bit tells the left-or-right game: 0, left wins
SMILE_LOST = 0.1                # the share of its rounds the bot loses on purpose
SMILE_ROUND = 5.0               # seconds a round of it takes until the next key counts
MEM_SHADES = 0xFF47             # the shades of the background and of the figures; others while fading
SHADES = (0xE4, 0xE0)
MEM_PHASE = 0xD5B8              # race: 2 while they run, 3 and more once they are in
CONTEST_SCREENS = (31, 45, 30)
HONOUR = 75                     # "Honorary member": the hall a pet with all three awards is shown in at its end
LAB_TEST = 2                    # "Pick test" in the laboratory's menu
CONTEST_HOURS = range(10, 18)
SKILL = {RACE: "body", KNOWLEDGE: "iq"}
SKILLED = 4                     # Body and IQ go from 0 to 4
GAMES_A_DAY = 4                 # training games for each of the two a day (they do not always add)
READY_EVERY = 60                # seconds between two games to get there
PATIENCE = 15                       # how much more another pet must need the bot for it to leave this one
HEAVY = 8                           # from this many pounds over a full ten on, sports to lose weight
ENOUGH = 2                          # the lead the wanted one of the two is kept at
TIDY_FROM = 18                      # the hour from which it is cleaned up in any case
STRESS_HIGH = 48                    # a child that is to be stressed is left in its dirt up to here
ICON_FOOD, ICON_LIGHT, ICON_GAME, ICON_MEDICINE, ICON_TOILET, ICON_STATUS, ICON_SCOLD, ICON_LAB = range(8)
SHOT, PILL = 0, 1
HOLD, PAUSE = 0.1, 0.4
FULL = 4                    # hearts
NAME_COLUMNS = 16           # of the name entry: A to G, a gap, a to g from the ninth on
NAME_LOWER = 8
NAME_END = (15, 4)          # where "ED" is
# The game's code of each letter, as the name is kept (measured: typed and read back)
LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                   (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 32, 33, 34, 35, 36, 37, 38,
                    40, 41, 43, 44)))
LETTERS.update({letter.lower(): code + 16 for letter, code in LETTERS.items()})
LETTER_OF = {code: letter for letter, code in LETTERS.items()}


RANDOM = -1                 # as the wish of a place: another goal, drawn by lot, for every egg


class GameBoyBot(CareBot):
    PACES = PACES
    CONTESTS = CONTESTS

    # Every place has a goal of its own. What the rest of the program calls the goal is the
    # one of the pet on the screen.
    @property
    def goal(self):
        return self.goals[self.slot()] if hasattr(self, "goals") else None

    @goal.setter
    def goal(self, goal):
        if hasattr(self, "goals"):
            self.wish(self.slot(), goal)

    def wish(self, slot, goal):
        """Set what a place is to raise: a character, None, or RANDOM."""
        self.wishes[slot] = goal
        self.goals[slot] = self.draw() if goal == RANDOM else goal

    def draw(self):
        return random.choice(rules.GOALS)

    def __init__(self, tama, log=print, discipline=True, feed_below=3, play_below=3, model=None):
        self.goals = [None] * PETS      # what each place is raising
        self.wishes = [None] * PETS     # what was asked for there (RANDOM stays, the goal changes)
        super().__init__(tama, log, discipline, feed_below, play_below, model)
        self.restart = True
        self.seen = {}              # of each pet, what was last logged of it
        self.last_name = None
        self.egg_pictures = {}          # the eggs as they stood in the egg room, by their number
        self.heirs = []                 # the dead whose name no pet bears on yet, the oldest first
        self.used = []                  # the names given so far, until all have had their turn
        self.keep = 1               # pets to have at a time
        self.pace = 1               # the game's speed of time to hold it at (PACES)
        self.contests = True        # let the adults go in for the contests
        self.trainings = {}         # (place, contest) -> (day of its life, games for it that day)
        self.album_next = 0         # the place of the album to write over once it is full
        self.eggs_seen = None       # the eggs left when last looked
        self.egg_back = None        # when one came back, and who died when: a pet that dies
        self.died = None            # of old age leaves its egg behind
        self.trained = 0.0          # when the last game for IQ or Body was played
        self.no_egg = 0.0           # no new attempt to take an egg before this
        self.passed = None          # the refusal last let pass, so that it is logged once

    def memo(self):
        return {"last_name": self.last_name, "used": self.used, "heirs": self.heirs, "keep": self.keep, "pace": self.pace, "contests": self.contests, "album_next": self.album_next,
                "goals": self.goals, "wishes": self.wishes}

    def recall(self, memo):
        if isinstance(memo, dict):
            self.last_name = memo.get("last_name")
            self.used = [n for n in memo.get("used") or () if isinstance(n, str)]
            self.heirs = [n for n in memo.get("heirs") or () if isinstance(n, str)]
            self.keep = max(1, min(PETS, int(memo.get("keep") or 1)))
            self.pace = memo.get("pace") if memo.get("pace") in PACES else 1
            self.contests = bool(memo.get("contests", True))
            self.album_next = int(memo.get("album_next") or 0)
            ok = lambda g: g if g in rules.GOALS else None
            if len(memo.get("goals") or ()) == PETS:
                self.goals = [ok(g) for g in memo["goals"]]
            if len(memo.get("wishes") or ()) == PETS:
                self.wishes = [g if g == RANDOM else ok(g) for g in memo["wishes"]]

    # -- state readers -----------------------------------------------------

    def slot(self):
        return min(self.tama.memory(MEM_SLOT), PETS - 1)

    def pet(self, slot=None):
        """A reader of one pet's record: the one on the screen, or another."""
        base = RECORD * (self.slot() if slot is None else slot)
        return lambda cell: self.tama.memory(cell + base)

    def pet_name(self, slot=None):
        m = self.pet(slot)
        letters = []
        for i in range(6):
            v = m(MEM_NAME + i)
            if v in (0, 0xFF):
                break
            letters.append(LETTER_OF.get(v, "?"))
        return "".join(letters)

    def status(self, slot=None):
        m, device = self.pet(slot), self.tama.memory
        kind = m(MEM_TYPE)
        if kind not in rules.NAMES:     # none, or the egg before it hatches
            kind = 0
        dead = bool(m(MEM_AFTER)) and kind != 0
        stage = rules.stage(kind)
        return {
            # "stage" is the character, as with the other models; the game calls the stages
            # of a life by other names
            "stage": kind, "name": rules.NAMES.get(kind, "Ei"),
            "away": False, "praying": False, "sickness": m(MEM_SICK), "leaving": False,
            "thanked": False, "generation": None,
            "hunger": m(MEM_LIFE), "happy": m(MEM_FUN), "weight": m(MEM_WEIGHT),
            "poop": m(MEM_POOP), "mistakes": 0, "age": m(MEM_DAY), "illnesses": 0,
            "missed": m(MEM_MINE), "training": m(MEM_DEED), "meter": 0, "kind": kind,
            "sick": bool(m(MEM_SICK)), "attack": False, "cocoon": False,
            "temperature": None, "friendship": None, "sweetness": None, "look": None, "back": False,
            "asleep": bool(m(MEM_ASLEEP)) and kind != 0, "light": not m(MEM_LIGHT_OFF),
            "attention": False, "scold": bool(m(MEM_SCOLD)), "praise": bool(m(MEM_PRAISE)),
            "urge": m(MEM_URGE) == 1,
            "dead": dead, "game": None, "hour": device(MEM_HOUR) % 24,
            "clock": "%02d:%02d" % (device(MEM_HOUR) % 24, device(MEM_MINUTE) % 60),
            # what only this one has
            "slot": self.slot() if slot is None else slot,
            "petName": self.pet_name(slot) if kind else "", "stageName": rules.STAGES.get(stage, "–"),
            "fear": m(MEM_FEAR), "mine": m(MEM_MINE),
            "iq": m(MEM_IQ), "body": m(MEM_BODY), "deed": m(MEM_DEED),
            "egg": m(MEM_EGG) if kind else None,
            "awards": [bool(m(MEM_AWARD + which)) for which in CONTESTS] if kind else [False] * 3,
            "contested": bool(m(MEM_CONTESTED)),
        }

    def way(self, st):
        """The way to the goal, if this pet can still go it: (teenager, selfishness from, to,
        "iq" or "body"), or None."""
        goal = self.goals[st["slot"]]
        if goal is None or not rules.open_to(goal, st["stage"], st["mine"]):
            return None
        return rules.WAYS[goal]

    def growth(self, st):
        if not st["stage"] or st["dead"]:
            return {"forecast": [], "reachable": list(rules.GOALS), "plan": None, "wanted": None,
                    "names": rules.NAMES, "goals": list(rules.GOALS)}
        way, goal = self.way(st), self.goals[st["slot"]]
        return {
            "forecast": rules.forecast(st["stage"], st["fear"], st["mine"], st["iq"], st["body"]),
            "reachable": [g for g in rules.GOALS if rules.open_to(g, st["stage"], st["mine"])],
            "plan": [way[0], rules.MASKUTCHI, goal] if way and goal == rules.BILL
            else [way[0], goal] if way else None,
            "wanted": {"selfish": [way[1], way[2]], "more": way[3],
                       "stress": way[0] == rules.KUCHITAMATCHI} if way else None,
            # for the page, which has no chart of this game: the names and the goals
            "names": rules.NAMES, "goals": list(rules.GOALS),
        }

    def pets(self):
        """The three places, for the page: each pet with all that is known of it."""
        here, out = self.slot(), []
        for slot in range(PETS):
            st = self.status(slot)
            alive = bool(st["stage"]) and not st["dead"]
            growth = self.growth(st)
            out.append({key: st[key] for key in (
                "slot", "stage", "name", "petName", "stageName", "age", "hunger", "happy", "weight",
                "poop", "asleep", "light", "sick", "sickness", "scold", "dead", "iq", "body", "deed",
                "fear", "mine", "awards", "contested")} | {
                "shown": slot == here, "egg": self.pet(slot)(MEM_TYPE) == 1,
                "goal": self.goals[slot], "wish": self.wishes[slot],
                "open": self.goals[slot] is None or not st["stage"]
                or rules.open_to(self.goals[slot], st["stage"], st["mine"]),
                "forecast": growth["forecast"] if alive else [],
                "wanted": growth["wanted"] if alive else None})
        return out

    # -- primitives ---------------------------------------------------------

    def press(self, btn, pause=PAUSE):
        self.held = btn
        self.tama.button(btn, True)
        yield HOLD
        self.tama.button(btn, False)
        self.held = None
        yield pause

    def home(self):
        """Back to the pet's screen out of a menu."""
        m = self.tama.memory
        for _ in range(6):
            if m(MEM_SCREEN) in (MAIN, INTRO, TITLE, WELCOME, NAME_ENTRY):
                break
            yield from self.press(BTN_B, 1.0)
        return m(MEM_SCREEN) == MAIN

    def icon(self, wanted):
        """Open one of the eight icons of the main screen."""
        m = self.tama.memory
        if not (yield from self.home()):
            return False
        for _ in range(12):
            at = m(MEM_ICON) - 4
            if at < 0:                  # in the row of the pets (the user went there): down again
                yield from self.press(BTN_DOWN, 0.4)
                continue
            if at == wanted:
                yield from self.press(BTN_A, 1.0)
                return True
            yield from self.press(BTN_RIGHT if at < wanted or at > 7 else BTN_LEFT, 0.3)
        return False

    def entry(self, wanted, per_row=None):
        """Move a menu's hand to an entry (the food menu has three to a row)."""
        m = self.tama.memory
        for _ in range(8):
            at = m(MEM_CURSOR)
            if at == wanted:
                return True
            if per_row and at // per_row != wanted // per_row:
                yield from self.press(BTN_DOWN if at < wanted else BTN_UP, 0.3)
            else:
                yield from self.press(BTN_RIGHT if at < wanted else BTN_LEFT, 0.3)
        return m(MEM_CURSOR) == wanted

    def request(self, icon):
        if hasattr(icon, "__next__"):
            self.stop()
            self.task, self.manual = icon, True

    def resume(self):
        self.stop()

    # -- actions -------------------------------------------------------------
    # (m reads the program's cells, p the record of the pet on the screen)

    def show(self, slot):
        """Bring another pet onto the screen: up into the row of the pets, and A on it."""
        m = self.tama.memory
        if not (yield from self.home()):
            return
        for _ in range(3):
            if m(MEM_ICON) <= PETS:
                break
            yield from self.press(BTN_UP, 0.4)
        for _ in range(PETS):
            if m(MEM_ICON) == slot + 1:
                break
            yield from self.press(BTN_RIGHT, 0.4)
        if m(MEM_ICON) == slot + 1:
            yield from self.press(BTN_A, 3.0)
        if m(MEM_ICON) <= PETS:
            yield from self.press(BTN_DOWN, 0.4)

    def light(self, on, why=None):
        p = self.pet()
        if (yield from self.icon(ICON_LIGHT)):
            yield 2.0
            if bool(p(MEM_LIGHT_OFF)) != on:
                self.note("Licht an" if on else "Licht aus")

    def heal(self):
        m, p = self.tama.memory, self.pet()
        kind = p(MEM_SICK)
        if not (yield from self.icon(ICON_MEDICINE)) or m(MEM_SCREEN) != MEDICINE_MENU:
            return
        if not (yield from self.entry(SHOT if kind == 2 else PILL)):
            return
        yield from self.press(BTN_A, 12.0)
        if not p(MEM_SICK):
            self.note("Medizin: %s, gesund" % ("Spritze" if kind == 2 else "Tablette"))

    def clean(self):
        p = self.pet()
        heaps = p(MEM_POOP)
        if (yield from self.icon(ICON_TOILET)):
            yield 8.0
            if not p(MEM_POOP):
                self.note("Toilette (%d Haufen)" % heaps)

    def potty(self):
        """The toilet icon while the pet is about to: it sits down on the potty. No droppings
        then, and it wants to be praised for it (plan() does that next)."""
        p = self.pet()
        if (yield from self.icon(ICON_TOILET)):
            yield 9.0                   # (until it has got up again: no menu opens before)
            if not p(MEM_POOP):
                self.note("Töpfchen")

    def feed(self, food=None):
        m, p = self.tama.memory, self.pet()
        if food is None:
            food = rules.favourite(p(MEM_TYPE))
        before = p(MEM_LIFE)
        if not (yield from self.icon(ICON_FOOD)) or m(MEM_SCREEN) != FOOD_MENU:
            return
        if not (yield from self.entry(food, per_row=3)):
            yield from self.home()
            return
        yield from self.press(BTN_A, 9.0)
        yield from self.home()
        if p(MEM_LIFE) > before:
            self.note("Füttern: %s (Hunger %d/%d)" % (rules.FOODS[food], p(MEM_LIFE), FULL))
        elif p(MEM_SCOLD):
            self.note("Will nicht essen")

    def play(self):
        """The smile game: which way will it look? Five rounds; three right ones cheer it."""
        m, p = self.tama.memory, self.pet()
        before = p(MEM_FUN)
        if not (yield from self.icon(ICON_GAME)) or m(MEM_SCREEN) != GAME_MENU:
            return
        if not (yield from self.entry(0)):
            yield from self.home()
            return
        yield from self.press(BTN_A, 6.0)
        if m(MEM_SCREEN) != SMILE_GAME:
            if p(MEM_SCOLD):
                self.note("Will nicht spielen")
            return
        # which way it will look is told beforehand by a bit in the game's memory (measured:
        # 240 rounds of 240, from six different states). One round in ten is answered
        # wrongly all the same.
        for _ in range(8):
            if m(MEM_SCREEN) != SMILE_GAME:
                break
            left = not (m(MEM_CHANCE) ^ (random.random() < SMILE_LOST)) & 1
            yield from self.press(BTN_LEFT if left else BTN_RIGHT, SMILE_ROUND)
        if m(MEM_WINS) > m(MEM_LOSSES):
            self.note("Spiel %d:%d gewonnen (Glück %d/%d)" % (m(MEM_WINS), m(MEM_LOSSES), p(MEM_FUN), FULL))
        else:
            self.note("Spiel %d:%d verloren" % (m(MEM_WINS), m(MEM_LOSSES)))

    def scold(self, why="Schimpfen"):
        m, p = self.tama.memory, self.pet()
        before = p(MEM_DEED)
        if not (yield from self.icon(ICON_SCOLD)) or m(MEM_SCREEN) != SCOLD_MENU:
            return
        if not (yield from self.entry(SCOLD)):
            yield from self.home()
            return
        yield from self.press(BTN_A, 8.0)
        self.note(why if p(MEM_DEED) > before or not p(MEM_SCOLD) else why + " (zu spät)")

    def praise(self, why="Loben"):
        m, p = self.tama.memory, self.pet()
        before = p(MEM_FEAR)
        if not (yield from self.icon(ICON_SCOLD)) or m(MEM_SCREEN) != SCOLD_MENU:
            return
        if not (yield from self.entry(PRAISE)):
            yield from self.home()
            return
        yield from self.press(BTN_A, 8.0)
        if not p(MEM_PRAISE):
            self.note("%s (Stress %d → %d)" % (why, before, p(MEM_FEAR)) if p(MEM_FEAR) < before else why)

    def game(self, which, level_screen, game_screen, level=0):
        """Into one of the two games with levels (0: level A); True once it runs."""
        m = self.tama.memory
        if not (yield from self.icon(ICON_GAME)) or m(MEM_SCREEN) != GAME_MENU:
            return False
        if not (yield from self.entry(which)):
            yield from self.home()
            return False
        yield from self.press(BTN_A, 2.0)
        if m(MEM_SCREEN) != level_screen:
            if self.pet()(MEM_SCOLD):
                self.note("Will nicht spielen")
            return False
        if not (yield from self.entry(level)):
            yield from self.home()
            return False
        yield from self.press(BTN_A, 1.5)
        return m(MEM_SCREEN) == game_screen

    def study(self, level=0):
        """The study game: three sums, and the pet goes to the answer it believes in. There
        is nothing to do but to go on; the cleverer it is, the better it does."""
        m, p = self.tama.memory, self.pet()
        before = p(MEM_IQ)
        self.trained = self.tama.seconds
        if not (yield from self.game(STUDY, STUDY_LEVEL, STUDY_GAME, level)):
            return
        for _ in range(40):
            if m(MEM_SCREEN) != STUDY_GAME:
                break
            yield from self.press(BTN_A, 2.0)
        yield 3.0
        self.note("Lernspiel: IQ %d" % p(MEM_IQ) if p(MEM_IQ) > before else "Lernspiel: nichts gelernt")

    def in_honour(self):
        """The game shows the hall of its honorary members: the end of a pet that has won all
        three contests."""
        return self.tama.memory(MEM_SCREEN) == HONOUR

    def honour(self):
        """Let the hall be seen for a while (and its picture be taken), then go on to the
        album."""
        self.log("%s ist Ehrenmitglied in der Hall of Fame des Spiels" % (self.pet_name() or "Das Tier"))
        yield 6.0
        yield from self.press(BTN_A, 3.0)

    def contest(self, which):
        """Into one of the contests and through it. The race is run without a key; the other
        two only want A to go on."""
        m, p = self.tama.memory, self.pet()
        before, name = p(MEM_AWARD + which), CONTESTS[which]
        if not (yield from self.icon(ICON_LAB)) or m(MEM_SCREEN) != LAB:
            yield from self.home()
            return
        if not (yield from self.entry(LAB_TEST, per_row=1)):
            yield from self.home()
            return
        yield from self.press(BTN_A, 1.5)               # "Which one?"
        if not (yield from self.entry(which, per_row=1)):
            yield from self.home()
            return
        yield from self.press(BTN_A, 1.5)               # "Go for it!"
        yield from self.press(BTN_A, 1.0)
        if m(MEM_SCREEN) != CONTEST_SCREENS[which]:     # (not today, or not at its age)
            yield from self.home()
            return
        for _ in range(900):
            if m(MEM_SCREEN) != CONTEST_SCREENS[which]:
                break
            if which == RACE and m(MEM_PHASE) < 3:
                yield 0.2
            else:
                yield from self.press(BTN_A, 2.0)
        yield 3.0
        won = p(MEM_AWARD + which) and not before
        self.note("Wettbewerb %s: %s" % (name, "gewonnen – Auszeichnung!" if won else
                                         "gewonnen" if p(MEM_AWARD + which) else "nicht gewonnen"))

    def sprites(self):
        """Sports game: where the pet stands and where the ball is, (x, y) each or None."""
        m = self.tama.memory
        pet, ball = None, None
        for i in range(SPRITES):
            y, x = m(OAM + 4 * i), m(OAM + 4 * i + 1)
            if not (0 < y < 160 and 0 < x < 168):
                continue
            tile = m(OAM + 4 * i + 2)
            if tile in BALL_TILES:
                ball = (x, y) if ball is None else (min(x, ball[0]), y)
            elif tile in PET_TILES:
                pet = (x, y) if pet is None else (min(x, pet[0]), max(y, pet[1]))
        return pet, ball

    def sports(self, level=0):
        """The sports game: ten balls fall onto five places, and the pet has to stand where
        one comes down. A direction held and A make it hop one place that way."""
        m, p = self.tama.memory, self.pet()
        before = p(MEM_BODY)
        self.trained = self.tama.seconds
        if not (yield from self.game(SPORTS, SPORTS_LEVEL, SPORTS_GAME, level)):
            return
        last, caught = None, 0
        for _ in range(4000):
            if m(MEM_SCREEN) != SPORTS_GAME:
                break
            caught = max(caught, m(MEM_CAUGHT))     # (cleared when the game is over)
            pet, ball = self.sprites()
            # under the ball; between two balls back to the middle, two hops from everywhere
            goal = ball[0] if ball else MIDDLE
            if pet and pet == last and abs(pet[0] + 8 - goal) > HOP:
                way = BTN_RIGHT if pet[0] + 8 < goal else BTN_LEFT
                self.held = (way, BTN_A)
                self.tama.button(way, True)
                yield 0.05
                self.tama.button(BTN_A, True)
                yield HOLD
                self.tama.button(BTN_A, False)
                self.tama.button(way, False)
                self.held = None
            else:
                yield 0.05
            last = pet
        yield 3.0
        self.note("Sportspiel: %d von 10 gefangen, Körper %d" % (caught, p(MEM_BODY))
                  if p(MEM_BODY) > before else "Sportspiel: %d von 10 gefangen" % caught)

    def bury(self):
        """It has died. A key brings the album ("Save?"): keep it there, in a free place, or
        where the last but seven lies."""
        m, p = self.tama.memory, self.pet()
        taken = {entry["place"] for entry in self.album()}
        free = [place for place in range(ALBUM_PLACES) if place not in taken]
        place = free[0] if free else self.album_next % ALBUM_PLACES
        if m(MEM_SCREEN) == MAIN:
            yield from self.press(BTN_A, 3.0)
        if m(MEM_SCREEN) == ALBUM and p(MEM_TYPE):
            yield from self.press(BTN_A, 3.0)       # "Yes"; now: "Location?"
            # the places are two to a row, counted row by row
            for _ in range(6):
                at = m(MEM_CURSOR)
                if at == place:
                    break
                if at // 2 != place // 2:
                    yield from self.press(BTN_DOWN if at < place else BTN_UP, 0.4)
                else:
                    yield from self.press(BTN_RIGHT if at < place else BTN_LEFT, 0.4)
            yield from self.press(BTN_A, 3.0)
            if not p(MEM_TYPE):
                self.album_next = place + 1
        for _ in range(4):                      # the album's page, then the laboratory
            if m(MEM_SCREEN) != ALBUM or p(MEM_TYPE):
                break
            yield from self.press(BTN_A, 3.0)

    def type_name(self, name):
        m = self.tama.memory
        for letter in name[:6]:
            index = ord(letter.upper()) - 65
            if not 0 <= index < 26:
                continue
            x, y = index % 7 + (0 if letter.isupper() else NAME_LOWER), index // 7
            if not (yield from self.name_cursor(x, y)):
                return False
            typed = m(MEM_CURSOR)
            yield from self.press(BTN_A, 0.5)
            if m(MEM_CURSOR) == typed < 5 and m(MEM_SCREEN) == NAME_ENTRY:
                return False            # (the sixth letter leaves the count at five)
        if m(MEM_SCREEN) == NAME_ENTRY:
            if not (yield from self.name_cursor(*NAME_END)):
                return False
            yield from self.press(BTN_A, 3.0)
        return m(MEM_SCREEN) != NAME_ENTRY

    def fresh_name(self):
        """A name by lot that no pet has had yet, and whose child the pet is. One that follows a
        dead pet bears the last three letters of its name and three new ones (Anaris, Risome);
        the first of a line, or one whose forebear's name cannot be carried on, gets a name of
        the list. Once all have had their turn, they start anew."""
        about = {self.last_name} | {self.pet_name(slot) for slot in range(PETS)}
        taken = about | set(self.used) | {entry["name"] for entry in self.album()}
        parent = self.heirs[0] if self.heirs else None
        for known in (taken, about):
            names = [n for n in rules.heir(parent, known) if n not in known]
            if names:
                return random.choice(names), parent
        free = [n for n in rules.PET_NAMES if n not in taken]
        if not free:
            self.used = []
            free = [n for n in rules.PET_NAMES if n not in about]
        # (rather one that can be carried on)
        return random.choice([n for n in free if rules.heir(n)] or free), None

    def name_cursor(self, x, y):
        m = self.tama.memory
        for _ in range(NAME_COLUMNS + 6):
            have_x, have_y = m(MEM_NAME_X), m(MEM_NAME_Y)
            if (have_x, have_y) == (x, y):
                return True
            if have_y != y:
                yield from self.press(BTN_DOWN if have_y < y else BTN_UP, 0.25)
            else:
                yield from self.press(BTN_RIGHT if have_x < x else BTN_LEFT, 0.25)
        return (m(MEM_NAME_X), m(MEM_NAME_Y)) == (x, y)

    def note(self, text):
        """Into the log, with the pet's name when there is more than one."""
        self.log((self.pet_name() + ": " if len(self.living()) > 1 else "") + text)

    def in_view(self, slot):
        """Whether this pet can be seen as it is: on the screen, in its room, awake, the
        light on and alive."""
        st = self.status(slot)
        return slot == self.slot() and self.tama.memory(MEM_SCREEN) == MAIN and st["stage"] \
            and not st["dead"] and not st["asleep"] and st["light"]

    def at_ease(self, slot):
        """Whether this pet can be seen alone and at rest, for its picture: nothing being
        done, nothing lying about, and the screen not fading."""
        st = self.status(slot)
        return self.in_view(slot) and self.task is None and not st["poop"] and not st["sick"] \
            and (self.tama.memory(MEM_SHADES), self.tama.memory(MEM_SHADES + 1)) == SHADES

    def album(self):
        """What the game itself remembers: the pets in its album, by place."""
        m, out = self.tama.memory, []
        for place in range(ALBUM_PLACES):
            at = ALBUM_AT + RECORD * place - MEM_TYPE
            kind = m(at + MEM_TYPE)
            if kind not in rules.NAMES:
                continue
            name = "".join(LETTER_OF.get(m(at + MEM_NAME + i), "") for i in range(6)
                           if m(at + MEM_NAME + i) not in (0, 0xFF))
            out.append({"place": place, "name": name, "character": kind, "characterName": rules.NAMES[kind],
                        "age": m(at + MEM_DAY), "weight": m(at + MEM_WEIGHT),
                        "data": {"hunger": m(at + MEM_LIFE), "happy": m(at + MEM_FUN), "iq": m(at + MEM_IQ),
                                 "body": m(at + MEM_BODY), "deed": m(at + MEM_DEED),
                                 "fear": m(at + MEM_FEAR), "mine": m(at + MEM_MINE)}})
        return out

    def memory_picture(self):
        """The game's own page of its album ("Memory", behind OPTION on the title): its picture,
        packed as the screen is. The game goes on as if nothing had been: its state is put
        aside, the machine switched off and on, and the state brought back. None if the page
        could not be reached."""
        t = self.tama
        if self.held is not None:
            return None
        keep, picture = t.save(), None
        try:
            t.reset()
            t.run(int(8 * TICK_HZ))
            for btn, pause, screen in ((BTN_START, 2, TITLE), (BTN_DOWN, 1, TITLE), (BTN_DOWN, 1, TITLE),
                                       (BTN_A, 1.5, OPTION), (BTN_DOWN, 1, OPTION), (BTN_A, 2, ALBUM)):
                t.button(btn, True)
                t.run(int(0.15 * TICK_HZ))
                t.button(btn, False)
                t.run(int(pause * TICK_HZ))
                if t.memory(MEM_SCREEN) != screen:
                    return None
            picture = t.packed() or None
        finally:
            t.load(keep)
        return picture

    def egg_picture(self):
        """Keep the picture of the egg under the hand, cut out of the egg room (20 dots a side,
        packed as the screen is). The hand hides it, so in a copy of the game the hand goes
        to another egg first; with the last egg it stays in the picture."""
        t = self.tama
        egg, keep = t.memory(MEM_HAND), t.save()
        try:
            for btn in (BTN_RIGHT, BTN_DOWN, BTN_LEFT):
                t.button(btn, True)
                t.run(int(0.15 * TICK_HZ))
                t.button(btn, False)
                t.run(int(0.6 * TICK_HZ))
                if t.memory(MEM_HAND) != egg:
                    break
            packed = t.packed()
        finally:
            t.load(keep)
        if packed and egg < EGGS:
            x, y = (48 + 24 * (egg % 4)) // 4, 46 + 32 * (egg // 4)
            self.egg_pictures[egg] = b"".join(packed[row * 40 + x:row * 40 + x + 5] for row in range(y, y + 20))

    def eggs_left(self):
        return max(0, EGGS - self.tama.memory(MEM_EGGS_USED))

    def living(self):
        """The places that hold a pet (or an egg about to hatch)."""
        return [slot for slot in range(PETS) if self.pet(slot)(MEM_TYPE)]

    def begin(self):
        """A new pet: through the title and the laboratory to an egg, and give it a name."""
        m = self.tama.memory
        had = len(self.living())
        self.no_egg = self.tama.seconds + 600       # if this comes to nothing, not again at once
        for _ in range(40):
            screen = m(MEM_SCREEN)
            if len(self.living()) > had:
                return
            if screen in (INTRO, TITLE):
                yield from self.press(BTN_START, 2.0)
            elif screen == EGG_ROOM:
                self.egg_picture()
                yield from self.press(BTN_A, 3.0)       # the egg under the hand
            elif screen in (WELCOME, LAB, NO_EGGS):
                yield from self.press(BTN_A, 3.0)       # "Choose egg" and the egg under the hand
            elif screen == MAIN:
                yield from self.icon(ICON_LAB)
                yield 2.0
            elif screen == NAME_ENTRY:
                break
            else:
                yield from self.press(BTN_B, 1.5)
        if m(MEM_SCREEN) != NAME_ENTRY:
            return
        if m(MEM_CURSOR):                       # letters of an attempt that went wrong
            for _ in range(6):
                yield from self.press(BTN_B, 0.4)
        name, parent = self.fresh_name()
        if (yield from self.type_name(name)):
            self.last_name = name
            self.used.append(name)
            if self.heirs:
                del self.heirs[0]       # (one whose name could not be carried on has no heir)
            self.no_egg = 0.0
            self.log("Neues Ei: %s%s" % (name, " (folgt auf %s)" % parent if parent else ""))
            if self.reborn and not had:
                self.reborn()
            yield 20.0                          # it hatches

    # -- the plan -----------------------------------------------------------

    def watch(self, slot, st):
        """Write down what has become of a pet."""
        seen = (st["stage"], st["asleep"], st["sickness"], st["dead"], st["petName"])
        before = self.seen.get(slot)
        self.seen[slot] = seen
        if before is not None and st["stage"] and not before[0]:
            self.log("%s: %s geschlüpft" % (st["petName"], st["name"]))
            if self.wishes[slot] == RANDOM:
                self.goals[slot] = self.draw()
                self.log("%s, Ziel ausgelost: %s" % (st["petName"], rules.NAMES[self.goals[slot]]))
            return
        if before is None or seen == before or before[4] != seen[4]:
            return
        who = st["petName"] + ": " if len(self.living()) > 1 else ""
        kind, asleep, sick, dead = before[:4]
        if st["dead"] and not dead:
            self.log("%s ist gestorben (%d Tage alt)" % (st["petName"] or st["name"], st["age"]))
            self.died = (self.tama.seconds, st["petName"] or st["name"])
            if st["petName"]:
                self.heirs.append(st["petName"])    # the next egg is named after it
        elif st["stage"] != kind and st["stage"] and kind:
            self.log("%sEntwickelt: %s (%s)" % (who, st["name"], st["stageName"]))
        if st["asleep"] != asleep and not st["dead"] and st["stage"]:
            self.log(who + ("Schläft" if st["asleep"] else "Wach"))
        if st["sickness"] and not sick:
            self.log(who + "Krank")

    def food(self, st, way):
        """What to feed: the meal that calms it most at the weight it has (its favourite, unless
        that would bring it to a full ten pounds). A child that is to become Kuchitamatchi is
        to stay stressed and gets what it dislikes."""
        if way and way[0] == rules.KUCHITAMATCHI and st["stage"] == rules.MARUTCHI:
            return rules.CHARACTERS[st["stage"]][3]
        return rules.meal(st["stage"], st["weight"])

    def wants(self, st):
        """What a pet needs done: (name of the method that does it, arguments), or None."""
        if not st["stage"]:
            return None
        if st["dead"]:
            return ("bury",) if self.restart else None
        way = self.way(st)
        kind = rules.stage(st["stage"])
        stressing = bool(way) and way[0] == rules.KUCHITAMATCHI and st["stage"] == rules.MARUTCHI
        if st["asleep"]:
            return ("light", False) if st["light"] else None
        if not st["light"]:
            return ("light", True)
        if st["urge"] and kind >= rules.TEEN and st["slot"] == self.slot():
            return ("potty",)           # (at once: there are five seconds for it)
        if st["sick"]:
            return ("heal",)
        if st["scold"]:
            # selfishness comes from refusals that go unscolded. It begins at 0 again with
            # every new character, so only the teenager's counts for the adult.
            least = way[1] if way and kind == rules.TEEN else 0
            if st["mine"] >= least:
                if way or self.discipline:
                    return ("scold",)
            elif self.passed != (st["stage"], st["mine"]):
                self.passed = (st["stage"], st["mine"])
                self.log("%s: Verweigerung bleibt ungeschimpft (Egoismus %d, Ziel %d)"
                         % (st["petName"], st["mine"], least))
        if st["praise"] and not stressing:
            return ("praise",)
        if st["poop"] and not (stressing and st["fear"] < STRESS_HIGH and st["hour"] < TIDY_FROM):
            # (droppings left lying stress it, eight an hour for four. Not into the night with
            # them: nothing can be cleaned while it sleeps, and it wakes with a stress of 100)
            return ("clean",)
        if st["hunger"] < FULL:
            return ("feed", self.food(st, way))
        if st["happy"] < self.play_below:
            return ("play",)
        if st["fear"] >= UNEASY and not stressing and kind >= rules.CHILD \
                and self.tama.seconds - self.trained >= CALM_EVERY * self.slower():
            # a game it wins is praised, and praise calms it. (At 100 the stress kills.)
            clever = bool(way) and way[3] == rules.CLEVER
            return ("study",) if clever and st["hour"] in STUDY_HOURS else None if clever else ("sports",)
        if self.contests and kind == rules.ADULT and not all(st["awards"]) \
                and st["hour"] in CONTEST_HOURS and st["hunger"] == FULL:
            # A contest a day, one it has not won yet: happy into the beauty contest, and with
            # what Body or IQ the day's games have given it into the race or the test of
            # knowledge (those two by turns).
            open_ = [which for which in (RACE, KNOWLEDGE) if not st["awards"][which]]
            which = BEAUTY if not st["awards"][BEAUTY] else open_[st["age"] % len(open_)]
            if not st["contested"]:
                if which == BEAUTY:
                    return ("contest", BEAUTY) if st["happy"] == FULL else ("play",)
                if st[SKILL[which]] >= SKILLED or not self.trainable(st, which):
                    return ("contest", which)
            if self.tama.seconds - self.trained >= READY_EVERY * self.slower():
                for which in sorted(open_, key=lambda w: w != which):
                    if self.trainable(st, which) and (which == RACE or st["hour"] in STUDY_HOURS):
                        return self.training(st, which)
        if (st["weight"] % 10 >= HEAVY or st["weight"] >= rules.HEAVIEST - 2) and not stressing \
                and kind >= rules.CHILD and not (kind == rules.TEEN and way and way[3] == rules.CLEVER) \
                and self.tama.seconds - self.trained >= CALM_EVERY * self.slower():
            # the next full ten pounds are near, and reaching them would stress it: the sports
            # game takes two off. (Not with a teenager that is to be the cleverer kind.)
            return ("sports",)
        if way and kind == rules.TEEN and self.tama.seconds - self.trained >= TRAIN_EVERY * self.slower():
            more, less = (st["iq"], st["body"]) if way[3] == rules.CLEVER else (st["body"], st["iq"])
            if more < less + ENOUGH:
                if way[3] == rules.STRONG:
                    return ("sports",)
                if st["hour"] in STUDY_HOURS:
                    return ("study",)
        return None

    def trainable(self, st, which):
        """Whether a game for the Body (RACE) or the IQ could still add to it today."""
        day, games = self.trainings.get((st["slot"], which), (None, 0))
        return st[SKILL[which]] < SKILLED and (day != st["age"] or games < GAMES_A_DAY)

    def training(self, st, which):
        """The game that adds to it, at the level that still does: level A brings it to 2,
        the higher ones further."""
        day, games = self.trainings.get((st["slot"], which), (None, 0))
        self.trainings[(st["slot"], which)] = (st["age"], games + 1 if day == st["age"] else 1)
        have = st[SKILL[which]]
        if which == RACE:
            return ("sports", 0 if have < 2 else 2)
        return ("study", 0 if have < 1 else 1 if have < 3 else 2)

    def urgency(self, st, want):
        """How badly a pet needs what it wants done (0: nothing)."""
        if not want:
            return 0
        what = want[0]
        if what == "potty":
            return 95
        if what in ("bury", "heal", "light"):
            return 90
        if what == "feed":
            return 80 if st["hunger"] == 0 else 30 + 5 * (FULL - st["hunger"])
        if what in ("scold", "praise"):
            return 60                                   # there is only a while for these
        if what == "clean":
            return 50
        if what == "play":
            return 70 if st["happy"] == 0 else 20
        return 10                                       # the games for IQ, Body and weight

    def slower(self):
        """How much longer than at medium pace the game's time takes."""
        return (self.pace + 1) / 2

    def set_pace(self):
        """The game's own setting (OPTION on the title) is one cell; a new game puts it back."""
        if self.tama.memory(MEM_PACE) != self.pace:
            self.tama.poke(MEM_PACE, self.pace)

    def plan(self):
        m = self.tama.memory
        screen = m(MEM_SCREEN)
        self.set_pace()
        states = {slot: self.status(slot) for slot in range(PETS)}
        for slot, st in states.items():
            self.watch(slot, st)
        # An egg that is there again: the pet that has just died has laid it
        eggs = self.eggs_left()
        if self.eggs_seen is not None and eggs == self.eggs_seen + 1:     # (a new game brings all eight)
            self.egg_back = self.tama.seconds
        self.eggs_seen = eggs
        if self.egg_back is not None and self.died is not None and abs(self.egg_back - self.died[0]) < 60:
            self.log("%s hat ein Ei hinterlassen (Eier übrig: %d von %d)" % (self.died[1], eggs, EGGS))
            self.egg_back = self.died = None
        living = self.living()
        if not living:
            return self.begin() if self.restart and self.tama.seconds >= self.no_egg else None
        if screen in (INTRO, TITLE):
            return self.press(BTN_START, 2.0)           # "Continue"
        if screen == NO_EGGS:
            return self.press(BTN_A, 3.0)
        if screen == HONOUR:
            return self.honour()
        if screen == ALBUM and states[self.slot()]["dead"] and self.restart:
            # "Save?" is already asked (a key of the user's, or the bot was held up on its
            # way): B does not leave this page, so go on from here
            return self.bury()
        if screen in (NAME_ENTRY, WELCOME):
            # an egg taken by hand (or the bot was held up there): B does not lead back, name it
            return self.begin()
        if screen != MAIN:
            return self.home()
        here = self.slot()
        wants = {slot: self.wants(st) if st["stage"] else None for slot, st in states.items()}
        # Of several the one that needs it most comes first, not the one on the screen until
        # it has everything: an empty stomach or no joy at all stresses a grown pet by 20
        # every time, and the others must not wait for a game to be won.
        need = {slot: self.urgency(states[slot], want) for slot, want in wants.items()}
        worst = max(need, key=lambda slot: (need[slot], slot == here))
        if worst != here and (need[worst] >= need[here] + PATIENCE or not states[here]["stage"]) \
                and states[worst]["stage"]:
            return self.show(worst)
        want = wants[here]
        if want:
            return getattr(self, want[0])(*want[1:])
        for slot, st in states.items():                 # (a place left empty on the screen)
            if slot != here and not states[here]["stage"] and st["stage"]:
                return self.show(slot)
        if len(living) < self.keep and self.restart and self.eggs_left() \
                and self.tama.seconds >= self.no_egg:
            return self.begin()
        return None
