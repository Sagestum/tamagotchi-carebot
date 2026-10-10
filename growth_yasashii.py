"""Growth chart of the Yasashii Tamagotch (1998).

The character is the number in RAM 0x0B. Only the care mistakes count (RAM 0x3D; they begin
again at 0 with every change), and for the adults the device throws a coin as well.

  Chikachikababytchi  after an hour                          Hoppetchi
  Hoppetchi (2 days)  0 or 1 care mistakes                   Meruhetchi, of the first kind
                      2 or 3                                 Meruhetchi, of the second kind
                      4 to 6                                 Mayumarutchi, of the first kind
                      7 or more                              Mayumarutchi, of the second kind

  the teenager (3 days), by its kind and its own care mistakes; each row is one of two,
  with even chances:

      mistakes   first kind                        second kind
      0-1        Oshamatchi or Jr. Mametchi        Jr. Mametchi or Tamabetchi
      2-4        Jr. Mametchi or Tamabetchi        Tamabetchi or Pantarotchi
      5-7        Tamabetchi or Pantarotchi         Pantarotchi or Jr. Ginjirotchi
      8-10       Pantarotchi or Jr. Ginjirotchi    Jr. Ginjirotchi or Kabuto Oyajitchi
      11+        Jr. Ginjirotchi or Kabuto Oyaj.   Kabuto Oyajitchi or Micheltchi

The rules are those of the character list of the Tamagotchi wiki. Run here in the emulator
(lab/yasashii/botsim.py): the teenagers by the child's mistakes, and the adults that come
from a teenager without mistakes.
"""
BABY, CHILD, MERUHETCHI, MAYUMARUTCHI = 1, 2, 3, 4
OSHAMATCHI, MAMETCHI, TAMABETCHI, PANTAROTCHI, GINJIROTCHI, KABUTO, MICHELTCHI = 5, 6, 7, 8, 9, 10, 11
LUCKY = None
DEAD = None

NAMES = {
    0: "Ei", BABY: "Chikachikababytchi", CHILD: "Hoppetchi", MERUHETCHI: "Meruhetchi",
    MAYUMARUTCHI: "Mayumarutchi", OSHAMATCHI: "Oshamatchi", MAMETCHI: "Jr. Mametchi",
    TAMABETCHI: "Tamabetchi", PANTAROTCHI: "Pantarotchi", GINJIROTCHI: "Jr. Ginjirotchi",
    KABUTO: "Kabuto Oyajitchi", MICHELTCHI: "Micheltchi",
}
TEENS = (MERUHETCHI, MAYUMARUTCHI)
ADULTS = (OSHAMATCHI, MAMETCHI, TAMABETCHI, PANTAROTCHI, GINJIROTCHI, KABUTO, MICHELTCHI)
GOALS = ADULTS
GENERATIONS = ()
# care mistakes of the teenager -> the two adults, by its kind (1 or 2)
BANDS = ((0, 1), (2, 4), (5, 7), (8, 10), (11, 15))
LADDER = (OSHAMATCHI, MAMETCHI, TAMABETCHI, PANTAROTCHI, GINJIROTCHI, KABUTO, MICHELTCHI)


def teen(mistakes):
    """(teenager, kind) a child with this many care mistakes becomes."""
    if mistakes <= 1:
        return MERUHETCHI, 1
    if mistakes <= 3:
        return MERUHETCHI, 2
    return (MAYUMARUTCHI, 1) if mistakes <= 6 else (MAYUMARUTCHI, 2)


def adults(kind, mistakes):
    """The two adults a teenager of this kind may become with this many care mistakes."""
    band = next(i for i, (lo, hi) in enumerate(BANDS) if mistakes <= hi)
    return LADDER[band + kind - 1], LADDER[band + kind]


def plan(goal, stage, kind=1):
    """What to do as this character for the goal: (care mistakes to reach, the characters
    still to come, the chance that it comes out), or None if it is out of reach. The
    way with the fewest mistakes is taken."""
    if goal not in GOALS:
        return None
    best = None
    if stage in (0, BABY, CHILD):
        for child, k in ((0, 1), (2, 2)):          # Meruhetchi of either kind is enough
            for lo, hi in BANDS:
                if goal in adults(k, lo) and (best is None or child + lo < best[0] + best[3]):
                    best = (child, [teen(child)[0], goal], 0.5, lo)
        if best is None:
            return None
        way = ([CHILD] if stage != CHILD else []) + best[1]
        return (best[0] if stage == CHILD else 0), way, best[2]
    if stage in TEENS:
        for lo, hi in BANDS:
            if goal in adults(kind, lo):
                return lo, [goal], 0.5
        return None
    return (0, [], 1.0) if stage == goal else None


def reachable(stage, kind=1):
    return [g for g in GOALS if plan(g, stage, kind)]


def forecast(stage, mistakes, kind=1):
    if stage in (0, BABY):
        return [CHILD, MERUHETCHI]
    if stage == CHILD:
        return [teen(mistakes)[0]]
    return []
