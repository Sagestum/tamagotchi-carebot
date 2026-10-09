"""Growth chart of the Genjintch (Genjintch no Tamagotch, 1997).

The program is the Mothra's with other characters (carebot_mothra.py looks after both). The
character is the number in RAM 0x0B. What comes next is decided by the care mistakes (RAM
0x37, they begin again at 0 with every change) and by the Evolution meter (RAM 0x3B: 2 more
for every time it is praised while it makes pottery, full from 14 on. Dotetchi begins at 6
and Ukitchi at 4).

  DNAtchi        after an hour                               Kuromarutchi
  Kuromarutchi   up to 2 care mistakes                       Dotetchi
                 3 or more                                   Ukitchi
  Dotetchi       meter full and up to 1 mistake              Genjintchi
                 4 or more mistakes                          Hanitchi
                 else                                        GenjinGaltchi
  Ukitchi        meter full and no mistake                   Dotetchi (it catches up)
                 4 or more mistakes                          Hanitchi
                 else                                        Manmotchi
  Genjintchi     meter full and no mistake                   Ibatchi
                 meter full, a mistake, exactly 60 kg        Gaikotchi
                 no mistake and never praised (meter 6)      back to Ukitchi
                 anything else                               it leaves in its rocket
  Hanitchi       meter full and up to 1 mistake              Dogutchi

Genjintchi is the only one whose time runs out: about five days after it has grown up it
changes or it is gone. Going back to Ukitchi is the way to keep it: Ukitchi catches up to
Dotetchi, Dotetchi becomes Genjintchi again, and so on for as long as one likes.

All of it measured in the emulator (lab/genjin/grid.py: care mistakes 0 to 6, the meter and
the weight written into the RAM shortly before the change), and it agrees with the character
list of the Tamagotchi wiki, which does not mention the rocket.
"""
DNATCHI, KUROMARUTCHI, DOTETCHI, UKITCHI = 1, 2, 3, 4
GENJINTCHI, GALTCHI, MANMOTCHI, HANITCHI = 5, 6, 7, 8
IBATCHI, GAIKOTCHI, DOGUTCHI = 9, 10, 11
BABY, CHILD = DNATCHI, KUROMARUTCHI
LUCKY = None
COCOON = None       # there is none here (the Mothra has one)
DEAD = 15

NAMES = {
    0: "Ei", DNATCHI: "DNAtchi", KUROMARUTCHI: "Kuromarutchi", DOTETCHI: "Dotetchi",
    UKITCHI: "Ukitchi", GENJINTCHI: "Genjintchi", GALTCHI: "GenjinGaltchi",
    MANMOTCHI: "Manmotchi", HANITCHI: "Hanitchi", IBATCHI: "Ibatchi", GAIKOTCHI: "Gaikotchi",
    DOGUTCHI: "Dogutchi",
}
GOALS = (GENJINTCHI, GALTCHI, MANMOTCHI, HANITCHI, IBATCHI, GAIKOTCHI, DOGUTCHI)
ADULTS = (GENJINTCHI, GALTCHI, MANMOTCHI, HANITCHI)
TEENS = (DOTETCHI, UKITCHI)
GENERATIONS = ()    # no goal takes more than one life
FULL = 14           # RAM 0x3B from which the Evolution meter counts as full
METER_STEP = 2      # what RAM 0x3B goes up by for every praise
CALLING = (13, 14)  # RAM 0x0C while it makes pottery
SKELETON_WEIGHT = 60    # kg: what Genjintchi has to weigh to become Gaikotchi (it begins there)
UNPRAISED = 6           # the meter of a Genjintchi that has never been praised
GONE = DEAD             # what a Genjintchi turns into whose time has run out
STAY_BY_MISTAKES = True     # a goal that would change again is held by care mistakes



def adult(stage, mistakes, meter, weight=0):
    """What this character would turn into now; None if it stays what it is."""
    full = meter >= FULL
    if stage == DNATCHI:
        return KUROMARUTCHI
    if stage == KUROMARUTCHI:
        return DOTETCHI if mistakes <= 2 else UKITCHI
    if stage == DOTETCHI:
        if mistakes >= 4:
            return HANITCHI
        return GENJINTCHI if full and mistakes <= 1 else GALTCHI
    if stage == UKITCHI:
        if mistakes >= 4:
            return HANITCHI
        return DOTETCHI if full and mistakes == 0 else MANMOTCHI
    if stage == GENJINTCHI:
        if full:
            if mistakes == 0:
                return IBATCHI
            return GAIKOTCHI if weight == SKELETON_WEIGHT else GONE
        return UKITCHI if mistakes == 0 and meter == UNPRAISED else GONE
    if stage == HANITCHI and full and mistakes <= 1:
        return DOGUTCHI
    return None


def forecast(stage, mistakes, meter, weight=0):
    """The characters still to come if nothing more is counted."""
    way = []
    while len(way) < 4:
        nxt = adult(stage, mistakes, meter, weight)
        if nxt in (None, GONE):
            break
        way.append(nxt)
        stage, mistakes = nxt, 0
    return way


def reachable(stage, mistakes, meter):
    """All goals that can still be reached from here."""
    if stage in (0, DNATCHI, KUROMARUTCHI, UKITCHI):
        # Ukitchi can catch up to Dotetchi, so nothing is lost before the teenager is over
        goals = list(GOALS)
        if stage == UKITCHI and mistakes > 0:
            goals = [MANMOTCHI, HANITCHI, DOGUTCHI]
            if mistakes >= 4:
                goals.remove(MANMOTCHI)
        return goals
    if stage == DOTETCHI:
        if mistakes >= 4:
            return [HANITCHI, DOGUTCHI]
        goals = [GALTCHI, HANITCHI, DOGUTCHI]
        return [GENJINTCHI, IBATCHI, GAIKOTCHI] + goals if mistakes <= 1 else goals
    if stage == GENJINTCHI:
        # with a mistake it can only become Gaikotchi; kept without one it goes round again
        return [GAIKOTCHI] if mistakes else list(GOALS)
    if stage == HANITCHI:
        return [HANITCHI] + ([DOGUTCHI] if mistakes <= 1 else [])
    return [stage] if stage in GOALS else []


def before(goal):
    """The adult a goal is, or comes from."""
    return {IBATCHI: GENJINTCHI, GAIKOTCHI: GENJINTCHI, DOGUTCHI: HANITCHI}.get(goal, goal)


def plan(goal, stage, mistakes, meter):
    """How to get from here to the goal: (care mistakes to reach as this character, the
    characters still to come). The meter is always filled. None if out of reach."""
    if goal not in GOALS or goal not in reachable(stage, mistakes, meter):
        return None
    grown = before(goal)
    tail = [grown] if grown == goal else [grown, goal]
    # the teenager it takes: Manmotchi comes from Ukitchi only, the others from Dotetchi
    teen = UKITCHI if grown == MANMOTCHI else DOTETCHI
    if stage in (0, DNATCHI):
        return 0, [KUROMARUTCHI, teen] + tail
    if stage == KUROMARUTCHI:
        if mistakes > 2:
            # Ukitchi it will be; without a mistake and with a full meter it becomes Dotetchi
            return mistakes, ([UKITCHI] if teen == UKITCHI else [UKITCHI, DOTETCHI]) + tail
        return (3 if teen == UKITCHI else mistakes), [teen] + tail
    if stage == UKITCHI:
        if grown == MANMOTCHI:
            return max(mistakes, 1), tail
        if grown == HANITCHI:
            return max(mistakes, 4), tail
        return 0, [DOTETCHI] + tail         # catch up first
    if stage == DOTETCHI:
        want = {GENJINTCHI: mistakes, GALTCHI: max(mistakes, 2), HANITCHI: max(mistakes, 4)}[grown]
        return want, tail
    if stage == GENJINTCHI:
        if goal == GAIKOTCHI:
            return max(mistakes, 1), [GAIKOTCHI]
        if goal == IBATCHI:
            return 0, [IBATCHI]
        if goal == GENJINTCHI:      # to stay one it has to go round: never praised
            return 0, [UKITCHI, DOTETCHI, GENJINTCHI]
        # anything else: back to Ukitchi and on from there
        return 0, [UKITCHI] + plan(goal, UKITCHI, 0, 0)[1]
    if stage == HANITCHI:
        # as the goal it must not go on to Dogutchi: two mistakes
        return (max(mistakes, 2) if goal == HANITCHI else mistakes), ([] if goal == stage else [goal])
    return mistakes, []


def weight_goal(goal, stage):
    """The weight to hold: (weight, wanted)."""
    if stage == GENJINTCHI and goal == GAIKOTCHI:
        return SKELETON_WEIGHT, True
    return None


def answer(goal, stage):
    """Whether to praise the pottery. A Genjintchi that is to go back to Ukitchi must
    never be praised; with any other goal the meter is filled."""
    return not (stage == GENJINTCHI and goal not in (IBATCHI, GAIKOTCHI, None))
