"""Growth chart of the Tamagotchi Angel: which character it turns into, and why.

Found by experiment in the same way as growth.py: shortly before every
evolution the care mistakes (RAM 0x42) and the Angel Power (RAM 0x46/0x47)
were set to many values and the result was read from RAM 0x5D. The results
agree with the character list of the Tamagotchi wiki.

Other than on the P1, the care mistakes start again at 0 with every new
character, so each stage is decided on its own:

  Marutchi Angel   0-2 mistakes: Tamatchi Angel, else Takotchi Angel
  Tamatchi Angel   0-2 mistakes: Chestnut Angel, else Ginjirotchi Angel
  Takotchi Angel   Angel Power 40 or more: Chubby Angel, 30-39: Tarakotchi
                   Angel, less: Oyajitchi Angel (mistakes do not matter)
  Chestnut Angel   0-3 mistakes: Twin Angels, else it stays
  Chubby Angel     0-2 mistakes: Twin Angels, else it stays
  Tarakotchi Angel 0-3 mistakes: Cactus Angel, else it stays
  Oyajitchi Angel  0-4 mistakes: Shogun Angel, else it stays

An Angel that falls ill three times as the same character turns into Deviltchi
and is gone: the bad end. It falls ill when the light is switched off while
it is awake. That is offered as a goal too, under a number of its own.

Lucky Unchi-Kun takes four generations on the same device, each begun with A
and C together on the farewell screen of the one before (found by the
YouTuber Aibonnotamakatsunikki, confirmed here in the emulator):

  1  an Oyajitchi Angel that stays one, until it takes its leave
  2  the same again: this one takes its leave as a Lucky Unchi-Kun without a face
  3  a Ginjirotchi Angel, until it takes its leave
  4  the Ghost Jr that hatches now has another number (14), does not grow
     into a child and turns into Lucky Unchi-Kun after five days

An adult takes its leave (RAM 0x5E becomes 0xC, it cries) when it has lived
for some days and then makes further care mistakes.
"""
GHOST, MARUTCHI, TAMATCHI, TAKOTCHI = 1, 2, 3, 4
TWIN, CHESTNUT, GINJIROTCHI, CHUBBY, TARAKOTCHI, OYAJITCHI, SHOGUN = 5, 6, 7, 8, 9, 10, 11
LUCKY = 12          # Lucky Unchi-Kun
CACTUS = 13
GHOST_LUCKY = 14    # the Ghost Jr of the fourth generation, which grows into Lucky Unchi-Kun
DEVILTCHI = 20      # not a number of the ROM: the bad end, see below
CHILD = MARUTCHI

NAMES = {
    0: "Geist", GHOST: "Ghost Jr", MARUTCHI: "Marutchi Angel", TAMATCHI: "Tamatchi Angel",
    TAKOTCHI: "Takotchi Angel", TWIN: "Twin Angels", CHESTNUT: "Chestnut Angel",
    GINJIROTCHI: "Ginjirotchi Angel", CHUBBY: "Chubby Angel", TARAKOTCHI: "Tarakotchi Angel",
    OYAJITCHI: "Oyajitchi Angel", SHOGUN: "Shogun Angel", CACTUS: "Cactus Angel",
    DEVILTCHI: "Deviltchi", LUCKY: "Lucky Unchi-Kun", GHOST_LUCKY: "Ghost Jr",
}
GOALS = (CHESTNUT, GINJIROTCHI, CHUBBY, TARAKOTCHI, OYAJITCHI, TWIN, CACTUS, SHOGUN, DEVILTCHI,
         LUCKY)
# What to raise in each generation on the way to Lucky Unchi-Kun
GENERATIONS = {1: OYAJITCHI, 2: OYAJITCHI, 3: GINJIROTCHI}

MOST = 15       # a counter of care mistakes ends here
FULL = 99       # more Angel Power than any character can have

# What a character turns into: (most mistakes, least power, most power, the next one), the
# first line that fits counts. Characters that are not listed stay what they are.
RULES = {
    GHOST: ((MOST, 0, FULL, MARUTCHI),),
    MARUTCHI: ((2, 0, FULL, TAMATCHI), (MOST, 0, FULL, TAKOTCHI)),
    TAMATCHI: ((2, 0, FULL, CHESTNUT), (MOST, 0, FULL, GINJIROTCHI)),
    TAKOTCHI: ((MOST, 40, FULL, CHUBBY), (MOST, 30, 39, TARAKOTCHI), (MOST, 0, 29, OYAJITCHI)),
    CHESTNUT: ((3, 0, FULL, TWIN),),
    CHUBBY: ((2, 0, FULL, TWIN),),
    TARAKOTCHI: ((3, 0, FULL, CACTUS),),
    OYAJITCHI: ((4, 0, FULL, SHOGUN),),
}


def next_for(stage, mistakes, power):
    """The character this one turns into with these values, or None if it stays."""
    for most, low, high, new in RULES.get(stage, ()):
        if mistakes <= most and low <= power <= high:
            return new
    return None


def forecast(stage, mistakes, power):
    """Characters still to come if it is cared for without further mistakes."""
    path = []
    while True:
        stage = next_for(stage, mistakes, power)
        if stage is None:
            return path
        path.append(stage)
        mistakes = 0        # they start again with every character


def plan(goal, stage, mistakes):
    """How to get to the goal from here.

    Returns None if it is out of reach, else a list of steps, one for each
    character on the way starting with the present one:
    (character, least mistakes, most mistakes, least power, most power).
    The last step is the goal itself and says how to keep it from evolving
    further. The Angel Power can still be brought anywhere, so it does not
    decide what is in reach.
    """
    if goal in (DEVILTCHI, LUCKY):  # possible at any time: nothing to prepare for this one
        return [(stage, 0, MOST, 0, FULL)]

    def ways(here, made):
        if here == goal:
            # Staying: more mistakes than the first rule that would move it on allows
            least = max((most + 1 for most, _, _, _ in RULES.get(here, ()) if most < MOST),
                        default=0)
            return [(here, least, MOST, 0, FULL)]
        for i, (most, low, high, new) in enumerate(RULES.get(here, ())):
            # the mistakes this line needs: more than the lines before it allow
            least = max([m + 1 for m, lo, hi, _ in RULES[here][:i] if lo <= low and high <= hi],
                        default=0)
            if made > most:
                continue
            rest = ways(new, 0)
            if rest:
                return [(here, least, most, low, high)] + rest
        return None

    return ways(stage, mistakes if stage >= CHILD else 0)


def reachable(stage, mistakes):
    """All goals that can still be reached."""
    return [g for g in GOALS if plan(g, stage, mistakes) is not None]
