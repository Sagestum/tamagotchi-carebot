"""Growth chart of the Mothra (Mothra no Tamagotch, 1997).

The character is the number in RAM 0x0B. Two counters decide what comes next: the care
mistakes (RAM 0x37, they begin again at 0 with every change) and the Justice (RAM 0x3B, 0 to
4, a quarter for every time it is told off while it attacks the tower).

  Baby Mothra    after an hour                              Mothra Larva
  Mothra Larva   up to 2 care mistakes                      Mothra Grub
                 3 or more                                  Batora Grub
  either grub    spins a cocoon; what comes out of it is settled then (RAM 0x63)

  Mothra Grub    Justice full:   0 mistakes Mothra Leo, 1 to 3 Fairy, more Mayura
                 Justice half:   up to 3 Fairy, more Mayura
                 Justice less:   up to 2 Fairy, more Mayura
  Batora Grub    Justice full:   0 or 1 Fairy, 2 to 4 Batora, more Mayura
                 Justice half:   up to 4 Batora, more Mayura
                 Justice less:   up to 3 Batora, more Mayura

  Fairy          no mistake, Justice full                   Ghogo
  Mayura         no mistake, Justice full                   Godzilla

Mothra Larva calls three times to be told off; with two of them answered the grub begins
at half Justice. Every other character calls as often as its Justice has room.

The twins take generations. RAM 0x16 counts them and is kept when a new egg is begun:

  Mothra Leo after 75 waking hours, with no care mistake and a weight of 70 to 79 t:
      counter 0       stays Mothra Leo, counter 1
      counter 1 to 3  becomes Moll & Lora, counter one more
      counter 4       becomes Lucky Haka-Kun (the fifth generation in a row), counter 5
  and if it weighs something else or a mistake has been made, the counter is 0 again.

The counter only outlives a death that leaves an egg: the pet must be old enough (RAM 0x76
is 2: Mothra Leo after 75 waking hours, Moll & Lora after 56) and then die of five care
mistakes. One that is left hungry earlier dies after 15 mistakes, and the counter is 0.
"""
BABY, LARVA, MOTHRA_GRUB, BATORA_GRUB, COCOON = 1, 2, 3, 4, 5
LEO, FAIRY, BATORA, MAYURA = 7, 8, 9, 10      # 6 is not a character of its own
GHOGO, GODZILLA, MOLL_LORA, HAKA = 11, 12, 13, 14
CHILD = LARVA
LUCKY = None
DEAD = 15           # RAM 0x0B once it has died

NAMES = {
    0: "Ei", BABY: "Baby Mothra", LARVA: "Mothra Larva", MOTHRA_GRUB: "Mothra Grub",
    BATORA_GRUB: "Batora Grub", COCOON: "Kokon", LEO: "Mothra Leo", FAIRY: "Fairy",
    BATORA: "Batora", MAYURA: "Mayura", MOLL_LORA: "Moll & Lora", GHOGO: "Ghogo",
    GODZILLA: "Godzilla", HAKA: "Lucky Haka-Kun",
}
GOALS = (LEO, FAIRY, BATORA, MAYURA, GHOGO, GODZILLA, MOLL_LORA, HAKA)
GENERATIONS = (MOLL_LORA, HAKA)     # goals that take more than one life
ADULTS = (LEO, FAIRY, BATORA, MAYURA)
TEENS = (MOTHRA_GRUB, BATORA_GRUB)
FULL = 4            # the Justice meter when it is full
METER_STEP = 1      # what RAM 0x3B goes up by for every telling off
CALLING = (8, 9)    # RAM 0x0C while it attacks the tower
TWIN_WEIGHT = (70, 79)  # t: what Mothra Leo has to weigh after 75 waking hours
HAKA_AT = 4         # the generation counter at which Mothra Leo becomes Lucky Haka-Kun

# Illness: about once a day the ROM decides whether it falls ill, and the fourth illness as
# the same character is its death. The chance depends on the snacks eaten as this character
# (RAM 0x62 counts them in threes): it rises with them, but at one exact count there is none
# at all, and one step further it is as high as it gets. Measured over 12 days for every
# count: both grubs 10, Mothra Leo 13, Fairy, Batora, Godzilla, Moll & Lora and Lucky
# Haka-Kun 11, Ghogo 7. That is 14 less the character's own number in RAM 0x6B, which is
# what the bot goes by (carebot_mothra.py); Mayura's number is 15, so it has no such count.
# The Tamagotchi wiki calls it immortality.


def teen(mistakes):
    return MOTHRA_GRUB if mistakes <= 2 else BATORA_GRUB


def adult(stage, mistakes, justice):
    """What this character would turn into now; None if it stays what it is."""
    if stage == BABY:
        return LARVA
    if stage == LARVA:
        return teen(mistakes)
    step = 2 if justice >= FULL else 1 if justice >= 2 else 0
    if stage == MOTHRA_GRUB:
        if step == 2 and mistakes == 0:
            return LEO
        return FAIRY if mistakes <= (3, 3, 2)[2 - step] else MAYURA
    if stage == BATORA_GRUB:
        if step == 2 and mistakes <= 1:
            return FAIRY
        return BATORA if mistakes <= (4, 4, 3)[2 - step] else MAYURA
    if stage == FAIRY and mistakes == 0 and justice >= FULL:
        return GHOGO
    if stage == MAYURA and mistakes == 0 and justice >= FULL:
        return GODZILLA
    return None


def forecast(stage, mistakes, justice):
    """The characters still to come if nothing more is counted."""
    way = []
    while True:
        nxt = adult(stage, mistakes, justice)
        if nxt is None:
            return way
        if stage in TEENS:
            way.append(COCOON)
        way.append(nxt)
        if nxt in (GHOGO, GODZILLA) or stage in TEENS:
            return way
        stage, mistakes = nxt, 0
        justice = 2 if justice >= 2 and stage in TEENS else 0


def before(goal):
    """The teenager a goal comes from, and the adult before a special one."""
    if goal == GHOGO:
        return MOTHRA_GRUB, FAIRY
    if goal == GODZILLA:
        return MOTHRA_GRUB, MAYURA
    if goal in GENERATIONS:
        return MOTHRA_GRUB, LEO
    return (BATORA_GRUB if goal == BATORA else MOTHRA_GRUB), goal


def flawless(stage, mistakes):
    """Whether this life can still be the Mothra Leo without a care mistake that the
    twins come from."""
    if stage == LARVA:
        return mistakes <= 2
    return stage in (0, BABY, COCOON) or (stage in (MOTHRA_GRUB, LEO) and mistakes == 0)


def reachable(stage, mistakes, justice):
    """All goals that can still be reached from here. The twins and Lucky Haka-Kun always
    can: if not in this life, then in the next."""
    return _reachable(stage, mistakes, justice) + list(GENERATIONS)


def _reachable(stage, mistakes, justice):
    if stage in (0, BABY):
        return list(GOALS[:6])
    if stage == LARVA:      # the mistakes made cannot be taken back: Batora Grub it is
        return list(GOALS[:6]) if mistakes <= 2 else [FAIRY, BATORA, MAYURA, GHOGO, GODZILLA]
    if stage == MOTHRA_GRUB:
        goals = [MAYURA, GODZILLA]
        if mistakes <= 3:
            goals += [FAIRY, GHOGO]
        return goals + [LEO] if mistakes == 0 else goals
    if stage == BATORA_GRUB:
        goals = [MAYURA, GODZILLA]
        if mistakes <= 4:
            goals.append(BATORA)
        return goals + [FAIRY, GHOGO] if mistakes <= 1 else goals
    if stage == COCOON:
        return []
    if stage == FAIRY:
        return [FAIRY, GHOGO] if mistakes == 0 else [FAIRY]
    if stage == MAYURA:
        return [MAYURA, GODZILLA] if mistakes == 0 else [MAYURA]
    return [stage] if stage in GOALS[:6] else []


def plan(goal, stage, mistakes, justice):
    """How to get from here to the goal: (care mistakes to reach as this character, the
    characters still to come). The Justice is always filled: no goal needs less. None if
    the goal is out of reach."""
    if goal in GENERATIONS:
        # this life has to be a Mothra Leo without a care mistake; what follows is the
        # bot's business (carebot_mothra.py)
        if stage in (MOLL_LORA, HAKA) or not flawless(stage, mistakes):
            return mistakes, ([] if stage == goal else [goal])
        way = plan(LEO, stage, mistakes, justice)
        return (0, [goal]) if stage in (LEO, COCOON) or way is None else (way[0], way[1] + [goal])
    if goal not in GOALS or stage == COCOON or goal not in reachable(stage, mistakes, justice):
        return None
    grub, grown = before(goal)
    tail = [grown] if grown == goal else [grown, goal]
    if stage in (0, BABY):
        return 0, [LARVA, grub, COCOON] + tail
    if stage == LARVA:
        if mistakes > 2:
            grub = BATORA_GRUB
        return (3 if grub == BATORA_GRUB else mistakes), [grub, COCOON] + tail
    if stage in TEENS:
        if grown == LEO:
            want = 0
        elif grown == FAIRY:        # from Mothra Grub one mistake, from Batora Grub none
            want = max(mistakes, 1) if stage == MOTHRA_GRUB else mistakes
        elif grown == BATORA:
            want = max(mistakes, 2)
        else:                       # Mayura
            want = max(mistakes, 4 if stage == MOTHRA_GRUB else 5)
        return want, [COCOON] + tail
    return mistakes, ([] if stage == goal else [goal])
