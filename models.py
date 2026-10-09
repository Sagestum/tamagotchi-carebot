"""The ROMs this project knows, and what differs between them.

The P1, its Japanese edition and the P2 are the same program with other
pictures and, in the P2, another game: the RAM cells (carebot.py) and the
growth rules (growth.py) were measured on all three dumps and are identical.
What does differ is collected here.
"""
import hashlib
import zlib

import growth
import growth_angel
import growth_digimon
import growth_genjin
import growth_morino
import growth_mothra
import growth_umino


P1_CLOCK_M = ("........", ".##.###.", ".#.#.##.", ".#.#.##.")
P1_ICONS = ("food", "light", "game", "medicine", "toilet", "status", "discipline", "attention")


class Model:
    def __init__(self, id, name, source, size, sha1, crc32, names, dead, game,
                 icons=P1_ICONS, care=True, tap=False, unit="oz", goals=True,
                 clock_m=P1_CLOCK_M, rules=growth, icon_pins=None, hold=0.1,
                 rattle=0, lcd=None):
        self.id = id
        self.name = name
        self.source = source    # where the dump is known from, for the settings page
        self.size = size
        self.sha1 = sha1
        self.crc32 = crc32
        self.names = names      # character by the number in RAM 0x5D
        self.dead = dead        # what the lower right of the LCD shows once the pet has died
        self.game = game        # "direction": guess left/right, "number": guess higher/lower
        self.icons = icons      # what the eight LCD icons mean, in LCD order
        self.care = care        # the Care-Bot knows how to look after this one
        self.tap = tap          # has a tap sensor (a fourth button)
        self.unit = unit        # what RAM 0x46/0x47 counts: weight or Angel Power
        self.goals = goals      # the growth rules are known: a character can be chosen
        self.growth = rules     # the module with its growth rules (growth.py, growth_angel.py)
        self.clock_m = clock_m # the "M" of AM/PM in the clock view, LCD rows 12-15 from column 2
        self.icon_pins = icon_pins  # [(segment, common)] where the LCD wires its icons unlike the P1
        self.hold = hold        # seconds a button has to be held for the ROM to take it
        self.rattle = rattle    # pulses of 5 ms a tap on the case is made of (0: one press)
        self.lcd = lcd          # (column of every segment, row of every common) if unlike the P1

    def stage_name(self, stage):
        return self.names.get(stage, "Erwachsen" if self.goals else "Stufe %d" % stage)

    def icon(self, what):
        return self.icons.index(what)

    def describe(self):
        return {"id": self.id, "name": self.name, "source": self.source,
                "size": self.size, "sha1": self.sha1, "crc32": self.crc32}


P1 = Model(
    "p1", "Tamagotchi P1", "tama.b aus dem MAME-Romset „tama“",
    12288, "4b4979cf92dc9d2fb6d7295a38f209f3da144f72", "5c864cb1",
    {0: "Ei", 1: "Babytchi", 2: "Marutchi", 3: "Tamatchi", 4: "Kuchitamatchi",
     5: "Mametchi", 6: "Ginjirotchi", 7: "Maskutchi", 8: "Kuchipatchi",
     9: "Nyorotchi", 10: "Tarakotchi", 11: "Oyajitchi"},
    # The angel flaps its wings: three pictures
    ((".#...#..", "#....#..", ".###.#..", "..#.#...",
      ".##.....", "#.#.....", "#.......", "........"),
     ("........", ".#...#..", "...#....", "..#.#...",
      "...#....", ".#...#..", "........", "........"),
     ("........", "........", ".#.#.#.#", ".#.#.##.",
      ".#.#.#..", "..##.#..", "...#.#..", ".##.....")),
    "direction")

P2 = Model(
    "p2", "Tamagotchi P2", "tamag2.bin aus dem MAME-Romset „tamag2“",
    12288, "09e5101b37636a314fc599d5d69b4846721b3c88", "9f97539e",
    {0: "Ei", 1: "Shirobabytchi", 2: "Tonmarutchi", 3: "Tongaritchi", 4: "Hashitamatchi",
     5: "Mimitchi", 6: "Pochitchi", 7: "Zuccitchi", 8: "Hashizotchi",
     9: "Kusatchi", 10: "Takotchi", 11: "Zatchi"},
    # A grave: with the age next to it, or (after C) with an angel
    (("........", ".....#..", ".######.", ".....#..",
      "...####.", "..#..#..", ".#...#..", "....##.."),
     ("###.....", "...#....", "##..#...", "....#...",
      "##..#...", "....#...", "######..", "........")),
    "number")

# The Japanese edition of the P1: same characters and game, the end screen of the P2
P1J = Model(
    "p1j", "Tamagotchi P1 Japan", "TamagotchiP1J.bin aus der Sammlung zu BrickEmuPy",
    12288, "15763f806c9c792f6a6458538dbd932a3c6668a3", "15647a14",
    P1.names, P2.dead, "direction")

# Tenshitchi no Tamagotchi. The same machine underneath: character, hunger, happiness, care
# mistakes, clock and light sit in the same RAM cells, 0x46/0x47 count Angel Power instead of
# weight. The menu is in another order, the game is another one and the care has more to it
# (praying, bats, strolls). Its growth rules are in growth_angel.py.
ANGEL = Model(
    "angel", "Tamagotchi Angel", "tamaang.bin aus dem MAME-Romset „tamaang“",
    16384, "f5899bb7717756ac581451cf16cf97d909961c5c", "87bcb59f",
    growth_angel.NAMES, (), "jump",
    icons=("status", "food", "game", "toilet", "praise", "medicine", "light", "attention"),
    tap=True, unit="AP", rules=growth_angel,
    clock_m=("........", "##.###..", "#.#.##..", "#.#.##.."))

# Mori de Hakken! Tamagotch, the one with the insects. The same machine once more: clock,
# hunger, happiness, weight and character sit in the cells of the P1. There are no care
# mistakes; weight, a hidden friendship and the temperature of the cocoon decide what it
# becomes (growth_morino.py). After the clock has been set it waits for an egg to be chosen:
# A or C changes between the white and the spotted one, B shows the clock, B once more begins.
MORINO = Model(
    "morino", "Tamagotchi Morino", "TamagotchiMorino.bin aus der Sammlung zu BrickEmuPy",
    16384, "4b578ea5dd328fd49fc7a664abeca79e35d573b2", "647ea772",
    growth_morino.NAMES, (), "hats",
    icons=("status", "food", "game", "toilet", "predator", "medicine", "light", "attention"),
    tap=True, unit="mg", rules=growth_morino)

# Umi de Hakken! Tamagotch, the Tamagotchi Ocean. Another program altogether: nothing sits
# where the P1 has it, so it has a bot of its own (carebot_umino.py). The water gets dirty by
# itself, a polar bear lies in wait, and two counters of mistakes decide what it becomes
# (growth_umino.py). The fifth icon is a calling box: it tells the pet off.
UMINO = Model(
    "umino", "Tamagotchi Umino", "TamagotchiUmino.bin aus der Sammlung zu BrickEmuPy",
    16384, "69d916819f8f4aa4be9194e6c78f099bf8199f37", "baae4199",
    growth_umino.NAMES, (), "ocean",
    icons=("status", "food", "game", "toilet", "discipline", "medicine", "light", "attention"),
    tap=True, unit="g", rules=growth_umino,
    clock_m=("........", "##.###..", "#.#.##..", "#.#.##.."),
    icon_pins=((8, 0), (17, 0), (18, 0), (19, 0), (39, 15), (38, 15), (37, 15), (28, 15)))

# Mothra no Tamagotch. The board of the Umino (the same wiring of the icons) and a program
# of its own again, with a bot of its own (carebot_mothra.py). It attacks a tower and wants
# to be told off for it; that fills the Justice, which decides with the care mistakes what
# comes out of the cocoon (growth_mothra.py). No tap sensor.
MOTHRA = Model(
    "mothra", "Tamagotchi Mothra", "tamamot.bin aus dem MAME-Romset „tamamot“",
    16384, "74c1f6761724b7cbda8bca3113db78586b786d2d", "85e4bee9",
    growth_mothra.NAMES, (), "mothra",
    icons=("status", "food", "game", "toilet", "discipline", "medicine", "light", "attention"),
    unit="t", rules=growth_mothra, icon_pins=UMINO.icon_pins)

# Genjintch no Tamagotch, the cave man. The program of the Mothra with other characters, so
# the same bot looks after it. It makes pottery and wants to be praised for it; that fills
# the Evolution meter (growth_genjin.py).
GENJIN = Model(
    "genjin", "Tamagotchi Genjintch", "TamagotchiGenjintch.bin aus der Sammlung zu BrickEmuPy",
    16384, "e317eac80c3360b766b92a2da253bda32fd50273", "bbf6b4fe",
    growth_genjin.NAMES, (), "mothra",
    icons=("status", "food", "game", "toilet", "praise", "medicine", "light", "attention"),
    unit="kg", rules=growth_genjin, icon_pins=UMINO.icon_pins)

# Tamaotch, after the actress Tamao Nakamura. A program of its own once more, with training
# games that are answered by tapping the case. No Care-Bot yet (carebot_tamaotch.py reads
# what is known), and no drawing of it in BrickEmuPy: web/shells/tamaotch.svg is ours.
TAMAOTCH = Model(
    "tamaotch", "Tamagotchi Tamaotch", "TamagotchiTamaotch.bin aus der Sammlung zu BrickEmuPy",
    16384, "d4ea15fa2abb16bd844c79e3b095a6f6cf21a98f", "a491fb55",
    {0: "Ei"}, (), "tamaotch",
    icons=("status", "food", "game", "training", "toilet", "medicine", "light", "discipline"),
    care=False, tap=True, unit="g", goals=False, icon_pins=UMINO.icon_pins, hold=0.35,
    rattle=400)

# Digital Monster, the first Digimon (1997). The same MCU as the Tamagotchis of its time
# with the LCD turned round: segments and commons run the other way. Two of them can be
# joined at a pin (P20) to fight. Its program is of the Mothra's family (carebot_digimon.py).
DIGIMON_LCD = ((None, 31, 30, 29, 28, 27, 26, 25, 24, None, None, None, 23, 22, 21, 20, 19, 18, 17,
                16, 0, 1, 2, 3, 4, 5, 6, 7, None, 8, 9, 10, 11, 12, 13, 14, 15, None, None, None),
               (15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0))
DIGIMON = Model(
    "digimon", "Digimon V1", "digimon.bin aus dem MAME-Romset „digimon“",
    16384, "1dde9b0aa81c8f4a1e22d3a79d4743833fc6cba7", "08ffac1b",
    growth_digimon.NAMES, (), "digimon",
    icons=("status", "food", "training", "battle", "toilet", "light", "medicine", "attention"),
    unit="G", rules=growth_digimon, lcd=DIGIMON_LCD,
    icon_pins=((28, 15), (37, 15), (38, 15), (39, 15), (11, 0), (10, 0), (9, 0), (0, 0)))

MODELS = (P1, P1J, P2, ANGEL, MORINO, UMINO, MOTHRA, GENJIN, TAMAOTCH, DIGIMON)
BY_ID = {m.id: m for m in MODELS}


def hashes(data):
    return {"size": len(data), "sha1": hashlib.sha1(data).hexdigest(),
            "crc32": "%08x" % zlib.crc32(data)}


def identify(data):
    """The model a ROM dump belongs to, or None."""
    sha1 = hashlib.sha1(data).hexdigest()
    for model in MODELS:
        if model.sha1 == sha1:
            return model
    return None
