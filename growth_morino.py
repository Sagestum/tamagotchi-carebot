"""Growth chart of the Morino (Mori de Hakken! Tamagotch): which insect it becomes, and why.

Measured in the emulator in the same way as growth.py and growth_angel.py: shortly
before a change the values were written into the RAM and the result was read from
RAM 0x5D. Everything agrees with the character list of the Tamagotchi wiki.

There are no care mistakes. Two eggs can be chosen. From the white one hatches
Babymotchi, which becomes Imotchi after 12 waking hours. Every 12 waking hours after
that the ROM looks at Imotchi (RAM 0x50 counts these looks, beginning at 1): if it
weighs 40 mg or more it spins a cocoon, Mayutchi, whose kind depends on the hidden
friendship (RAM 0x1D: +2 for every game played, -1 for every happy heart lost):

  look 1 or 2   friendship 10 or more: cocoon A, 7-9: cocoon B, less: cocoon C
  look 3        friendship 7 or more: cocoon B, less: cocoon C
  look 4        cocoon D, whatever it weighs

The cocoon lasts 24 hours. Its temperature (RAM 0x43) begins at 8 and moves by 1 or
2 about every two and a half hours, up or down as chosen on the meter screen. Only
the temperature at the end counts; 0 and 15 kill it.

  cocoon A   1-6: Tentotchi, 7-9: back to Imotchi, 10-14: Koganetchi, or
             Twinaritchi if the sweetness (RAM 0x1A, +1 for cherries or seeds, +2 for
             ice cream) leaves a rest of 3 when divided by 4
  cocoon B   1-7: Minotchi, 8-14: Chobitamatchi
  cocoon C   1-7: Gejitchi, 8-14: Mushibatchi
  cocoon D   4-12: Funkorogatchi, else Minotchi

An Imotchi that has come back out of cocoon A (RAM 0x51 is 15 then) is at look 3. If
it stays below 40 mg there, cocoon D follows at look 4 and Helmetchi comes out of it
at any temperature.

Imotchi hatches from the spotted egg directly. It spins a cocoon as soon as a look
finds 40 mg, at the fourth look in any case, and Kabutotchi comes out.
"""
BABYMOTCHI, IMOTCHI, CHOBITAMATCHI, MINOTCHI, KABUTOTCHI, KOGANETCHI = 1, 2, 3, 4, 5, 6
TENTOTCHI, FUNKOROGATCHI, TWINARITCHI, MUSHIBATCHI, GEJITCHI, HELMETCHI, MAYUTCHI = \
    7, 8, 9, 10, 11, 12, 13
CHILD = IMOTCHI
LUCKY = None        # no programme over generations here (the Angel has one)

NAMES = {
    0: "Ei", BABYMOTCHI: "Babymotchi", IMOTCHI: "Imotchi", CHOBITAMATCHI: "Chobitamatchi",
    MINOTCHI: "Minotchi", KABUTOTCHI: "Kabutotchi", KOGANETCHI: "Koganetchi",
    TENTOTCHI: "Tentotchi", FUNKOROGATCHI: "Funkorogatchi", TWINARITCHI: "Twinaritchi",
    MUSHIBATCHI: "Mushibatchi", GEJITCHI: "Gejitchi", HELMETCHI: "Helmetchi",
    MAYUTCHI: "Mayutchi",
}
GOALS = (KOGANETCHI, TENTOTCHI, CHOBITAMATCHI, MINOTCHI, MUSHIBATCHI, GEJITCHI, FUNKOROGATCHI,
         TWINARITCHI, HELMETCHI, KABUTOTCHI)
ADULTS = GOALS

# The kinds of cocoon, as RAM 0x50 holds them while it is one
A, B, C, D, SPOTTED = 10, 11, 12, 13, 14
COCOONS = {9: "A", A: "A", B: "B", C: "C", D: "D", SPOTTED: "gefleckt"}
WEIGHT = 40             # mg at which Imotchi spins its cocoon
COLDEST, HOTTEST = 1, 14    # beyond that the cocoon dies
BACK = 15               # RAM 0x51 once an Imotchi has come back out of cocoon A

# How to get each adult: the egg, the cocoon, the temperature at its end, and for
# the white egg the friendship to hold while Imotchi is weighed
WAYS = {
    KOGANETCHI: ("white", A, 10, 14, 10, 15),
    TWINARITCHI: ("white", A, 10, 14, 10, 15),
    TENTOTCHI: ("white", A, 1, 6, 10, 15),
    CHOBITAMATCHI: ("white", B, 8, 14, 7, 9),
    MINOTCHI: ("white", B, 1, 7, 7, 9),
    MUSHIBATCHI: ("white", C, 8, 14, 0, 6),
    GEJITCHI: ("white", C, 1, 7, 0, 6),
    FUNKOROGATCHI: ("white", D, 4, 12, 0, 15),
    HELMETCHI: ("white", A, 7, 9, 10, 15),      # then once more, see the text above
    KABUTOTCHI: ("spotted", SPOTTED, 1, 14, 0, 15),
}


def cocoon(look, weight, friendship):
    """The cocoon an Imotchi from the white egg spins at this look, or None if it stays."""
    if look >= 4:
        return D
    if weight < WEIGHT:
        return None
    if friendship >= 10 and look <= 2:
        return A
    return B if friendship >= 7 else C


def adult(kind, temperature, sweetness=0, back=False):
    """What comes out of a cocoon; None if it dies."""
    if not COLDEST <= temperature <= HOTTEST:
        return None
    if kind == SPOTTED:
        return KABUTOTCHI
    if kind == D:
        if back:
            return HELMETCHI
        return FUNKOROGATCHI if 4 <= temperature <= 12 else MINOTCHI
    if kind == B:
        return CHOBITAMATCHI if temperature >= 8 else MINOTCHI
    if kind == C:
        return MUSHIBATCHI if temperature >= 8 else GEJITCHI
    if temperature <= 6:
        return TENTOTCHI
    if temperature <= 9:
        return IMOTCHI
    return TWINARITCHI if back or sweetness % 4 == 3 else KOGANETCHI


def spotted(look):
    """Whether this value of RAM 0x50 belongs to an Imotchi from the spotted egg."""
    return 5 <= look <= 8


def reachable(stage, look, back, kind=None):
    """All goals that can still be reached from here."""
    if stage == 0:
        return list(GOALS)
    if stage in ADULTS:
        return [stage]
    if stage == MAYUTCHI:
        if kind == SPOTTED:
            return [KABUTOTCHI]
        if kind == D:
            return [HELMETCHI] if back else [FUNKOROGATCHI, MINOTCHI]
        if kind == B:
            return [CHOBITAMATCHI, MINOTCHI]
        if kind == C:
            return [MUSHIBATCHI, GEJITCHI]
        # out of cocoon A it can come back as Imotchi: everything after look 3 is open too
        return [KOGANETCHI, TENTOTCHI, TWINARITCHI, HELMETCHI, CHOBITAMATCHI, MINOTCHI,
                MUSHIBATCHI, GEJITCHI]
    if stage == IMOTCHI and spotted(look):
        return [KABUTOTCHI]
    if back:
        return [HELMETCHI, MUSHIBATCHI, GEJITCHI, CHOBITAMATCHI, MINOTCHI]
    goals = [g for g in GOALS if g != KABUTOTCHI]
    if stage == IMOTCHI and look >= 3:      # too late for cocoon A
        goals = [g for g in goals if WAYS[g][1] != A]
    if stage == IMOTCHI and look >= 4:
        goals = [FUNKOROGATCHI, MINOTCHI]
    return goals


def window(goal, kind, back=False):
    """The temperature to end the cocoon at: (lowest, highest). Without a goal, or when the
    cocoon is not the one the goal needs, whatever keeps it alive and an adult."""
    if goal in WAYS and WAYS[goal][1] in (kind, A if kind == 9 else kind):
        if goal == HELMETCHI and back:
            return 4, 12
        return WAYS[goal][2], WAYS[goal][3]
    if goal == HELMETCHI and kind == D:
        return 4, 12
    if goal == MINOTCHI and kind == D:
        return 1, 3
    if kind in (9, A):
        return 10, 14
    if kind == D:
        return 4, 12
    return 8, 14
