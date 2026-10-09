"""Growth chart of the Digimon (Digital Monster Ver. 1, 1997).

The character is the number in RAM 0x0B. The rules are those of the chart at
humulos.com/digimon/dm. The ways the bot goes have been run in the emulator (38 lives with
lab/digimon/botsim.py): every goal of the fourth stage came out each time, the last stage in
15 of 22 lives, which fits the chart's three in four. What counts begins again at 0 with
every change (the fights and the score of wins are kept):

  care mistakes (RAM 0x31)   a call for food or strength was left alone for 19 minutes
  training (RAM 0x34/0x35)   goes up by 2 with every training
  overfeeding (RAM 0x32)     meat until it turns it down
  battles (RAM 0x99)         needed for the last stage only, counted up to 15
  score of wins (RAM 0x98)   one more for a fight won, one less for one lost, 0 to 15

  Botamon    after an hour                                   Koromon
  Koromon    after 44 hours: up to 3 care mistakes           Agumon
                             4 or more                       Betamon
  Agumon     after 76 hours: up to 3 mistakes, 32+ trainings Greymon
                             up to 3 mistakes, fewer         Devimon
                             4+ mistakes, hardly trained     Numemon
  Betamon                    up to 3 mistakes, 48+ trainings Devimon
                             up to 3 mistakes, fewer         Meramon
                             4+ mistakes, hardly trained     Numemon
  (Tyranomon, Airdramon and Seadramon take 4+ mistakes together with overfeeding and
  waking it at night; the bot does not go for them yet.)

  Greymon, Devimon, Airdramon    15 battles as Agumon or Betamon and a      Metal Greymon
  Tyranomon, Meramon, Seadramon  score of 9 or more wins at both changes;   Mamemon
  Numemon                        even then it is a matter of luck           Monzaemon

The device throws dice for the last stage, once at each of the two changes before it and
at best with one chance in two, so one life in four stays what it is whatever is done.
"""
BOTAMON, KOROMON, AGUMON, BETAMON = 1, 2, 3, 4
GREYMON, TYRANOMON, DEVIMON, MERAMON, AIRDRAMON, SEADRAMON, NUMEMON = 5, 6, 7, 8, 9, 10, 11
METALGREYMON, MAMEMON, MONZAEMON = 12, 13, 14
BABY, CHILD = BOTAMON, KOROMON
LUCKY = None
COCOON = None
DEAD = 15

NAMES = {
    0: "Ei", BOTAMON: "Botamon", KOROMON: "Koromon", AGUMON: "Agumon", BETAMON: "Betamon",
    GREYMON: "Greymon", TYRANOMON: "Tyranomon", DEVIMON: "Devimon", MERAMON: "Meramon",
    AIRDRAMON: "Airdramon", SEADRAMON: "Seadramon", NUMEMON: "Numemon",
    METALGREYMON: "Metal Greymon", MAMEMON: "Mamemon", MONZAEMON: "Monzaemon",
}
ROOKIES = (AGUMON, BETAMON)
CHAMPIONS = (GREYMON, TYRANOMON, DEVIMON, MERAMON, AIRDRAMON, SEADRAMON, NUMEMON)
ULTIMATES = {METALGREYMON: (GREYMON, DEVIMON, AIRDRAMON), MAMEMON: (TYRANOMON, MERAMON, SEADRAMON),
             MONZAEMON: (NUMEMON,)}
GOALS = (GREYMON, DEVIMON, MERAMON, NUMEMON, METALGREYMON, MAMEMON, MONZAEMON)
ADULTS = CHAMPIONS
GENERATIONS = ()
TRAINING_STEP = 2       # what the training counter goes up by for one training
BATTLES = 15            # battles as a rookie for the last stage
WINS = 9                # the score of wins to have at both changes (it runs from 0 to 15)
FIGHTERS = ROOKIES + CHAMPIONS      # who can fight at all
FULL, METER_STEP, CALLING = 4, 1, ()     # for carebot_mothra.py: nothing calls to be told off


def adult(stage, mistakes, training):
    """What this character would turn into now, as far as mistakes and training decide it;
    None if it stays what it is or the chart needs more than these two."""
    trainings = training // TRAINING_STEP
    if stage == BOTAMON:
        return KOROMON
    if stage == KOROMON:
        return AGUMON if mistakes <= 3 else BETAMON
    if stage == AGUMON:
        if mistakes <= 3:
            return GREYMON if trainings >= 32 else DEVIMON
        return NUMEMON if trainings <= 4 else None
    if stage == BETAMON:
        if mistakes <= 3:
            return DEVIMON if trainings >= 48 else MERAMON
        return NUMEMON if trainings <= 7 else None
    return None


def forecast(stage, mistakes, training):
    way = []
    while len(way) < 4:
        nxt = adult(stage, mistakes, training)
        if nxt is None:
            break
        way.append(nxt)
        stage, mistakes, training = nxt, 0, 0
    return way


def champion(goal, rookie):
    """The champion to go for from this rookie on the way to the goal, or None."""
    wanted = ULTIMATES.get(goal, (goal,))
    order = {AGUMON: (GREYMON, DEVIMON, NUMEMON), BETAMON: (MERAMON, DEVIMON, NUMEMON)}[rookie]
    for c in order:
        if c in wanted:
            return c
    return None


def reachable(stage, mistakes, training):
    if stage in (0, BOTAMON):
        return list(GOALS)
    if stage == KOROMON:
        return list(GOALS)          # both rookies lead to every goal the bot knows
    if stage in ROOKIES:
        return [g for g in GOALS if champion(g, stage)]
    if stage in CHAMPIONS:
        return [g for g in GOALS if g == stage or stage in ULTIMATES.get(g, ())]
    return [stage] if stage in GOALS else []


def plan(goal, stage, mistakes, training):
    """How to get from here to the goal: a dict of what to reach as this character
    (care mistakes, trainings, battles to win), and the characters still to come under
    "way". None if the goal is out of reach."""
    if goal not in GOALS or goal not in reachable(stage, mistakes, training):
        return None
    last = goal in ULTIMATES
    if stage in (0, BOTAMON, KOROMON):
        # Agumon unless the goal is one of Betamon's own; keep the mistakes there are
        rookie = BETAMON if (goal in (MERAMON, MAMEMON) or mistakes > 3) else AGUMON
        c = champion(goal, rookie)
        way = ([KOROMON] if stage != KOROMON else []) + [rookie, c] + ([goal] if last else [])
        return {"mistakes": 4 if rookie == BETAMON and stage == KOROMON else mistakes,
                "trainings": 0, "battles": 0, "way": way}
    if stage in ROOKIES:
        c = champion(goal, stage)
        want = {GREYMON: (0, 36), DEVIMON: (0, 52) if stage == BETAMON else (0, 0),
                MERAMON: (0, 0), NUMEMON: (4, 0)}[c]
        return {"mistakes": max(mistakes, want[0]), "trainings": want[1],
                "battles": BATTLES if last else 0, "way": [c] + ([goal] if last else [])}
    if stage in CHAMPIONS:
        return {"mistakes": mistakes, "trainings": 0, "battles": 1 if last and stage != goal else 0,
                "way": [goal] if stage != goal else []}
    return {"mistakes": mistakes, "trainings": 0, "battles": 0, "way": []}
