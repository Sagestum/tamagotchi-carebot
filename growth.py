"""Growth chart of the P1 and P2 ROMs: which character the pet turns into, and why.

Found by experiment (see DOKUMENTATION.md): shortly before an evolution the
two counters were set to every combination and the result was read from RAM.
Only two things count:

  mistakes  RAM 0x42  care mistakes: a call for food or play ignored for
                      15 minutes, or the light left on for an hour of sleep
  missed    RAM 0x51  discipline calls that were not answered by scolding

Both only ever go up (to 15) and are kept for the pet's whole life. The
discipline meter itself (RAM 0x43) plays no part.

The constants carry the names of the P1 characters. The P2 ROM gave the same
tables in the same experiments; its characters have the same numbers and
other names (models.py).
"""
from functools import lru_cache

EGG, BABY, CHILD = 0, 1, 2
TAMATCHI, KUCHITAMATCHI = 3, 4
MAMETCHI, GINJIROTCHI, MASKUTCHI, KUCHIPATCHI, NYOROTCHI, TARAKOTCHI, OYAJITCHI = range(5, 12)

GOALS = (MAMETCHI, GINJIROTCHI, MASKUTCHI, KUCHIPATCHI, NYOROTCHI, TARAKOTCHI, OYAJITCHI)

# RAM 0x50 tells the two kinds of each teenager apart: the second kind had
# missed three or more discipline calls as a child.
SECRET_KIND = 6     # RAM 0x50 of a Maskutchi that will become Oyajitchi


def teen_for(mistakes, missed):
    """(stage, kind) a child turns into."""
    stage = TAMATCHI if mistakes <= 2 else KUCHITAMATCHI
    return stage, (2 if stage == TAMATCHI else 4) + (1 if missed >= 3 else 0)


def adult_for(kind, mistakes, missed):
    """Adult a teenager of the given kind (RAM 0x50) turns into."""
    if kind == 2:       # Tamatchi
        if mistakes <= 2:
            return MAMETCHI if missed == 0 else GINJIROTCHI if missed == 1 else MASKUTCHI
        return KUCHIPATCHI if missed <= 1 else NYOROTCHI if missed <= 3 else TARAKOTCHI
    if kind == 3:       # Tamatchi, second kind
        if mistakes <= 3:
            return GINJIROTCHI if missed <= 1 else MASKUTCHI
        return NYOROTCHI if missed <= 7 else TARAKOTCHI
    if kind == 4:       # Kuchitamatchi
        return KUCHIPATCHI if missed <= 1 else NYOROTCHI if missed == 2 else TARAKOTCHI
    return NYOROTCHI if missed <= 5 else TARAKOTCHI     # Kuchitamatchi, second kind


def _end(teen_kind, adult):
    """Last character of the line: only this Maskutchi becomes Oyajitchi."""
    return OYAJITCHI if adult == MASKUTCHI and teen_kind == 3 else adult


def forecast(stage, kind, mistakes, missed):
    """Characters still to come if both counters stay as they are."""
    if stage <= CHILD:
        teen, teen_kind = teen_for(mistakes, missed)
        adult = adult_for(teen_kind, mistakes, missed)
        path = [teen, adult]
    elif stage in (TAMATCHI, KUCHITAMATCHI):
        teen_kind = kind
        adult = adult_for(kind, mistakes, missed)
        path = [adult]
    else:
        return [OYAJITCHI] if stage == MASKUTCHI and kind == SECRET_KIND else []
    if _end(teen_kind, adult) != adult:
        path.append(OYAJITCHI)
    return path


@lru_cache(maxsize=4096)
def plan(goal, stage, kind, mistakes, missed):
    """How to get to the goal from here with the fewest extra mistakes.

    Returns None if the goal is out of reach, else (mistakes, missed, path):
    the counter values to have at the next evolution and the characters to
    come. Mistakes are made as early as possible, that leaves the most time.
    """
    best = None
    if stage <= CHILD:
        if stage < CHILD:
            mistakes = missed = 0       # nothing counts before the child stage
        for cm1 in range(mistakes, 16):
            for dm1 in range(missed, 16):
                teen, teen_kind = teen_for(cm1, dm1)
                for cm2 in range(cm1, 16):
                    for dm2 in range(dm1, 16):
                        adult = adult_for(teen_kind, cm2, dm2)
                        if _end(teen_kind, adult) != goal:
                            continue
                        key = (cm2 + dm2, cm2, -cm1 - dm1)
                        if best is None or key < best[0]:
                            path = [teen, adult] + ([OYAJITCHI] if goal != adult else [])
                            best = (key, cm1, dm1, path)
    elif stage in (TAMATCHI, KUCHITAMATCHI):
        for cm2 in range(mistakes, 16):
            for dm2 in range(missed, 16):
                adult = adult_for(kind, cm2, dm2)
                if _end(kind, adult) != goal:
                    continue
                key = (cm2 + dm2, cm2)
                if best is None or key < best[0]:
                    best = (key, cm2, dm2, [adult] + ([OYAJITCHI] if goal != adult else []))
    elif stage == goal:
        return mistakes, missed, []
    elif goal == OYAJITCHI and stage == MASKUTCHI and kind == SECRET_KIND:
        return mistakes, missed, [OYAJITCHI]
    return best[1:] if best else None


def reachable(stage, kind, mistakes, missed):
    """All goals that can still be reached."""
    return [g for g in GOALS if plan(g, stage, kind, mistakes, missed) is not None]
