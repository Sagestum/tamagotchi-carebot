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


P1_CLOCK_M = ("........", ".##.###.", ".#.#.##.", ".#.#.##.")
P1_ICONS = ("food", "light", "game", "medicine", "toilet", "status", "discipline", "attention")


class Model:
    def __init__(self, id, name, source, size, sha1, crc32, names, dead, game,
                 icons=P1_ICONS, care=True, tap=False, unit="oz", goals=True,
                 clock_m=P1_CLOCK_M, rules=growth):
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

MODELS = (P1, P1J, P2, ANGEL)
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
