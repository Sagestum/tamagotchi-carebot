"""Growth chart of the Umino (Umi de Hakken! Tamagotch, the Tamagotchi Ocean).

Measured in the emulator in the same way as the other growth modules: a few minutes
before a change the values were written into the RAM and the result was read from
RAM 0xC6. It agrees with the care sheet of Gotchi Garden and the Tamagotchi wiki.

Two counters decide, both begin again at 0 with every change:

  care mistakes (RAM 0x165)   a row of hearts was empty and stayed so; one more every
                              20 to 45 minutes
  missed calls (RAM 0x166)    it called although nothing was missing (RAM 0x71; it takes
                              neither food nor a game until it is told off) and nobody
                              answered. That takes a quarter of an hour, or two hours

  Planktontchi   after an hour                            Kuragetchi
  Kuragetchi     2 or more missed calls                   Kingyotchi
                 fewer                                    Otototchi
  Otototchi      no mistake, no missed call               Keropyontchi
                 4 mistakes, or a mistake and 2 missed    Kaitchi
                 else                                     Taiyakitchi
  Kingyotchi     4 missed calls or 4 mistakes             Kaitchi
                 else                                     Taiyakitchi
  either teen    99 g when it changes                     Kujiratchi
  Kingyotchi     the water black when it changes          Ashigyotchi
  Kaitchi        no missed call and exactly 10 g, which
                 is the least it can weigh                Ningyotchi

Kuragetchi lasts 22 waking hours, Otototchi 23, Kingyotchi 16. Kaitchi is looked at
again and again from about 25 hours on; one that never fits dies after two days.
"""
PLANKTONTCHI, KURAGETCHI, OTOTOTCHI, KINGYOTCHI, KUJIRATCHI, KAITCHI = 1, 2, 3, 4, 5, 6
KEROPYONTCHI, ASHIGYOTCHI, TAIYAKITCHI, NINGYOTCHI = 7, 8, 9, 10
CHILD = KURAGETCHI
LUCKY = None        # no programme over generations here (the Angel has one)

# RAM 0xC6 counts from 0 with the baby; the stages here are one more, so that 0 is the egg
NAMES = {
    0: "Ei", PLANKTONTCHI: "Planktontchi", KURAGETCHI: "Kuragetchi", OTOTOTCHI: "Otototchi",
    KINGYOTCHI: "Kingyotchi", KUJIRATCHI: "Kujiratchi", KAITCHI: "Kaitchi",
    KEROPYONTCHI: "Keropyontchi", ASHIGYOTCHI: "Ashigyotchi", TAIYAKITCHI: "Taiyakitchi",
    NINGYOTCHI: "Ningyotchi",
}
GOALS = (KEROPYONTCHI, TAIYAKITCHI, KAITCHI, NINGYOTCHI, KUJIRATCHI, ASHIGYOTCHI)
ADULTS = GOALS
TEENS = (OTOTOTCHI, KINGYOTCHI)

HEAVIEST = 99           # g: a teen that weighs this much becomes Kujiratchi
BLACK = 4               # the water at its worst: Kingyotchi becomes Ashigyotchi
MERMAID_WEIGHT = 10     # g: Kaitchi has to weigh exactly this, the least it can
WAKING_HOURS = {KURAGETCHI: 22, OTOTOTCHI: 23, KINGYOTCHI: 16}


def adult(stage, mistakes, missed, weight=0, water=0):
    """What this character would turn into now; None if it stays what it is."""
    if stage == PLANKTONTCHI:
        return KURAGETCHI
    if stage == KURAGETCHI:
        return KINGYOTCHI if missed >= 2 or (missed and mistakes >= 6) else OTOTOTCHI
    if stage in TEENS and weight >= HEAVIEST:
        return KUJIRATCHI
    if stage == OTOTOTCHI:
        if mistakes >= 4 or (mistakes and missed >= 2):
            return KAITCHI
        return TAIYAKITCHI if mistakes or missed else KEROPYONTCHI
    if stage == KINGYOTCHI:
        if water >= BLACK:
            return ASHIGYOTCHI
        return KAITCHI if missed >= 4 or mistakes >= 4 else TAIYAKITCHI
    if stage == KAITCHI and not missed and weight == MERMAID_WEIGHT:
        return NINGYOTCHI
    return None


def forecast(stage, mistakes, missed, weight=0, water=0):
    """The characters still to come if nothing more is counted and nothing else changes."""
    way = []
    while True:
        stage = adult(stage, mistakes, missed, weight, water)
        if stage is None:
            return way
        way.append(stage)
        # the counters begin again; weight and water are whatever the care makes of them
        mistakes = missed = water = 0
        weight = MERMAID_WEIGHT if stage == KAITCHI else 20


def reachable(stage, mistakes, missed):
    """All goals that can still be reached from here."""
    if stage in (0, PLANKTONTCHI):
        return list(GOALS)
    if stage == KURAGETCHI:     # with two calls missed already it will be Kingyotchi
        bad = adult(stage, mistakes, missed) == KINGYOTCHI
        return [g for g in GOALS if not (bad and g == KEROPYONTCHI)]
    if stage == OTOTOTCHI:
        goals = [KUJIRATCHI, KAITCHI, NINGYOTCHI]
        if adult(stage, mistakes, missed) != KAITCHI:
            goals.append(TAIYAKITCHI)
        return goals + [KEROPYONTCHI] if not mistakes and not missed else goals
    if stage == KINGYOTCHI:
        goals = [KUJIRATCHI, ASHIGYOTCHI, KAITCHI, NINGYOTCHI]
        return goals if missed >= 4 or mistakes >= 4 else goals + [TAIYAKITCHI]
    if stage == KAITCHI:
        return [KAITCHI] if missed else [KAITCHI, NINGYOTCHI]
    return [stage]


def teen(goal):
    """The teenager to raise on the way to this goal. Only Ashigyotchi needs Kingyotchi,
    and with it two calls missed as Kuragetchi; everything else can come from Otototchi,
    where care mistakes do what would otherwise take missed calls. A missed call is a
    gamble (it takes a quarter of an hour or two hours, and the pet eats nothing until it
    is over), a care mistake is not."""
    return KINGYOTCHI if goal == ASHIGYOTCHI else OTOTOTCHI


def plan(goal, stage, mistakes, missed):
    """How to get from here to the goal: (care mistakes to reach as this character, missed
    calls to reach, weight to have when it changes or None, water to have when it changes
    or None, the characters still to come). None if the goal is out of reach."""
    if goal not in GOALS or goal not in reachable(stage, mistakes, missed):
        return None
    if stage == goal:
        return mistakes, missed, None, None, []
    if stage in (0, PLANKTONTCHI):
        return 0, 0, None, None, [KURAGETCHI, teen(goal)] + tail(goal)
    if stage == KURAGETCHI:
        bad = teen(goal) == KINGYOTCHI or adult(stage, mistakes, missed) == KINGYOTCHI
        return mistakes, (max(missed, 2) if bad else missed), None, None, \
            [KINGYOTCHI if bad else OTOTOTCHI] + tail(goal)
    if stage == KAITCHI:        # the goal is the mermaid
        return mistakes, 0, MERMAID_WEIGHT, None, [NINGYOTCHI]
    # a teenager
    if goal == KUJIRATCHI:
        return mistakes, missed, HEAVIEST, None, [KUJIRATCHI]
    if goal == ASHIGYOTCHI:
        return mistakes, missed, None, BLACK, [ASHIGYOTCHI]
    if goal in (KAITCHI, NINGYOTCHI):
        enough = adult(stage, mistakes, missed) == KAITCHI
        return (mistakes if enough else 4), missed, None, None, tail(goal)
    if goal == TAIYAKITCHI:
        return (mistakes if stage == KINGYOTCHI or mistakes or missed else 1), missed, \
            None, None, [TAIYAKITCHI]
    return 0, 0, None, None, [KEROPYONTCHI]


def tail(goal):
    return [KAITCHI, NINGYOTCHI] if goal == NINGYOTCHI else [goal]
