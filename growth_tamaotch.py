"""Growth chart of the Tamaotch (Tamaotch, 1998).

The character is the number in RAM 0x1D8. What it turns into is decided by three things,
all of them as they stand at the moment of the change:

  care        good with up to 2 care mistakes as this character, bad with 3 or more
              (RAM 0x1F7; a meter empty for a quarter of an hour is one, and one more for
              every further quarter)
  the game    which of the three training games has been won most often: Ad-lib, Dance or
              Acting (RAM 0x1E8, 0x1E6, 0x1E7, each less the least of the three)
  popularity  high from 2 on (RAM 0x1E9: one less at midnight, more for a knock on the case
              while it gets its shot)

  Ashitchi (a day)        good care and Acting, or bad care and Ad-lib    AsaDoratchi
                          else                                            Mochimotchi

  AsaDoratchi (a day)     good: Acting unpopular, or Dance popular        Tamaotchi
                          popular: good and Ad-lib, or bad and Dance      Mochimotchi (older)
                          else                                            Kakuretchi
  Mochimotchi (37 hours)  good, Acting, popular                           Tamaotchi
                          popular: good and Dance, or bad and Acting      AsaDoratchi (older)
                          else                                            Kakuretchi

  The third change leads to Baradorutchi, Hariutchi, an older Tamaotchi, an older Kakuretchi
  or, if nothing fits, Tabakotchi; the table is THIRD below. Baradorutchi becomes TamaOtchi
  with good care, the older Kakuretchi becomes Sendatchi with bad care.

The rules are those of the character list of the Tamagotchi wiki, which go back to the data
read out of the ROM (rhubarbtart.neocities.org/file/tamaotch_stats.txt). The first two
changes have been run here in the emulator for every game, popular or not, with good and
with bad care (lab/tamaotch/botsim.py), and came out as the list says.
"""
ADLIB, DANCE, ACTING = 0, 1, 2      # the training games, in the order of the menu
GAMES = ("Ad-lib", "Tanz", "Schauspiel")
GOOD = 2                # care mistakes up to which the care is good
POPULAR = 2             # the popularity from which it is high

ASHITCHI, ASADORATCHI, MOCHIMOTCHI, TAMAOTCHI, KAKURETCHI = 1, 2, 3, 4, 5
HARIUTCHI, BARADORUTCHI, TABAKOTCHI, STAR, SENDATCHI = 6, 7, 8, 9, 10
ASADORATCHI_2, MOCHIMOTCHI_2, TAMAOTCHI_2, KAKURETCHI_2 = 11, 12, 13, 14
BABY, CHILD = ASHITCHI, ASHITCHI
LUCKY = None
DEAD = None

NAMES = {
    0: "Ei", ASHITCHI: "Ashitchi", ASADORATCHI: "AsaDoratchi", MOCHIMOTCHI: "Mochimotchi",
    TAMAOTCHI: "Tamaotchi", KAKURETCHI: "Kakuretchi", BARADORUTCHI: "Baradorutchi",
    HARIUTCHI: "Hariutchi", TABAKOTCHI: "Tabakotchi", STAR: "TamaOtchi", SENDATCHI: "Sendatchi",
    ASADORATCHI_2: "AsaDoratchi", MOCHIMOTCHI_2: "Mochimotchi", TAMAOTCHI_2: "Tamaotchi",
    KAKURETCHI_2: "Kakuretchi",
}
GOALS = (TAMAOTCHI, KAKURETCHI, BARADORUTCHI, HARIUTCHI, TABAKOTCHI, STAR, SENDATCHI)
GENERATIONS = ()

# (care is good, game, popular) -> what comes next; None stands for any
A, D, C = ADLIB, DANCE, ACTING
FIRST = {ASHITCHI: (((True, C, None), ASADORATCHI), ((False, A, None), ASADORATCHI),
                    ((None, None, None), MOCHIMOTCHI))}
SECOND = {
    ASADORATCHI: (((True, C, False), TAMAOTCHI), ((True, D, True), TAMAOTCHI),
                  ((True, A, True), MOCHIMOTCHI_2), ((False, D, True), MOCHIMOTCHI_2),
                  ((None, None, None), KAKURETCHI)),
    MOCHIMOTCHI: (((True, C, True), TAMAOTCHI),
                  ((True, D, True), ASADORATCHI_2), ((False, C, True), ASADORATCHI_2),
                  ((None, None, None), KAKURETCHI)),
}
THIRD = {
    TAMAOTCHI: (((False, A, True), BARADORUTCHI),
                ((True, C, False), HARIUTCHI), ((True, D, True), HARIUTCHI),
                ((True, A, False), KAKURETCHI_2), ((True, C, True), KAKURETCHI_2),
                ((False, C, False), KAKURETCHI_2), ((False, D, True), KAKURETCHI_2),
                ((None, None, None), TABAKOTCHI)),
    ASADORATCHI_2: (((True, D, True), BARADORUTCHI), ((True, A, True), HARIUTCHI),
                    ((True, A, False), TAMAOTCHI_2), ((True, C, True), TAMAOTCHI_2),
                    ((True, D, False), KAKURETCHI_2),
                    ((None, None, None), TABAKOTCHI)),
    MOCHIMOTCHI_2: (((True, A, True), BARADORUTCHI), ((True, D, True), HARIUTCHI),
                    ((True, D, False), TAMAOTCHI_2), ((True, C, True), TAMAOTCHI_2),
                    ((False, A, None), TAMAOTCHI_2),
                    ((True, C, False), KAKURETCHI_2),
                    ((None, None, None), TABAKOTCHI)),
    KAKURETCHI: (((True, D, None), TAMAOTCHI_2), ((True, C, None), TAMAOTCHI_2),
                 ((None, None, None), TABAKOTCHI)),
}
LAST = {BARADORUTCHI: (((True, None, None), STAR),),
        KAKURETCHI_2: (((False, None, None), SENDATCHI),)}
RULES = {**FIRST, **SECOND, **THIRD, **LAST}
SAME = {ASADORATCHI_2: ASADORATCHI, MOCHIMOTCHI_2: MOCHIMOTCHI, TAMAOTCHI_2: TAMAOTCHI,
        KAKURETCHI_2: KAKURETCHI}


def lead(games):
    """The game won most often, or None while two share the lead."""
    best = max(games)
    return games.index(best) if list(games).count(best) == 1 else None


def adult(stage, mistakes, games, popularity):
    """What this character would turn into now; None if it stays what it is."""
    good, game, popular = mistakes <= GOOD, lead(games), popularity >= POPULAR
    for (care, which, liked), nxt in RULES.get(stage, ()):
        if care in (None, good) and which in (None, game) and liked in (None, popular):
            return nxt
    return None


def ways(stage):
    """Every way on from this character: [(next, care is good, game, popular)], the
    catch-all of the table spelled out with a combination that fits nothing else."""
    out = []
    rows = RULES.get(stage, ())
    for good in (True, False):
        for game in (A, D, C):
            for popular in (False, True):
                for (care, which, liked), nxt in rows:
                    if care in (None, good) and which in (None, game) and liked in (None, popular):
                        out.append((nxt, good, game, popular))
                        break
    return out


# What a way costs, so that the planner takes the ones the bot can keep up: popularity is
# won by falling ill and being cured, which takes as many snacks as the character has hours
# of good health (HEALTH), and it only goes away by one a night
HEALTH = {ASHITCHI: 18, ASADORATCHI: 48, MOCHIMOTCHI: 24, TAMAOTCHI: 120, KAKURETCHI: 72,
          BARADORUTCHI: 24, HARIUTCHI: 72, TABAKOTCHI: 24, STAR: 48, SENDATCHI: 48}


def route(goal, stage, game=None, popular=False):
    """The easiest way to the goal from here: [(character, care is good, game, popular)],
    what to do as each character on the way. [] if this is the goal, None if out of reach.
    game and popular say how things stand now."""
    import heapq
    if SAME.get(stage, stage) == goal:
        return []
    best, heap, n = {}, [(0, 0, stage, game, popular, [])], 0
    while heap:
        cost, _, here, played, liked, path = heapq.heappop(heap)
        if SAME.get(here, here) == goal:
            return path
        if best.get((here, played, liked), 1e9) <= cost:
            continue
        best[(here, played, liked)] = cost
        for nxt, good, which, pop in ways(here):
            step = 10 + (0 if good else 2) + (0 if played in (None, which) else 3)
            if pop:
                step += HEALTH.get(SAME.get(here, here), 48) // 12
            elif liked:
                step += 25              # it would have to be forgotten within one stage
            n += 1
            heapq.heappush(heap, (cost + step, n, nxt, which, pop, path + [(here, good, which, pop)]))
    return None


def stay(stage):
    """How to keep this character from changing again: (care is good, game, popular), or
    None if nothing does (or nothing is needed)."""
    if stage not in RULES:
        return None
    for good in (True, False):
        for game in (A, D, C):
            for popular in (False, True):
                if not any(care in (None, good) and which in (None, game) and liked in (None, popular)
                           for (care, which, liked), _ in RULES[stage]):
                    return good, game, popular
    return None


def reachable(stage, mistakes=0, games=(0, 0, 0), popularity=0):
    return [g for g in GOALS if route(g, stage) is not None]


def forecast(stage, mistakes, games, popularity):
    way = []
    while len(way) < 5:
        nxt = adult(stage, mistakes, games, popularity)
        if nxt is None:
            break
        way.append(nxt)
        stage, mistakes = nxt, 0
    return way
