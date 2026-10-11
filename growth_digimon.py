"""Growth charts of the Digimon (Digital Monster Ver. 1 to 3, 1997/98).

The three devices run the same program with other characters. The character is the number
in RAM 0x0B, and the numbers mean the same place in the chart on all three: 1 and 2 the
babies, 3 and 4 the two of the third stage, 5 to 11 the seven of the fourth, 12 to 14 the
three of the last. The rules are those of the charts at humulos.com/digimon/dm, and they
were read off the devices themselves: a moment before a change the counters were set in
the RAM and the outcome was read (lab/digimon/grid.py, every mix of the four counters for
each of the six characters of the third stage).

What counts begins again at 0 with every change (the fights and the score of wins are kept):

  care mistakes (RAM 0x31)   a call for food or strength was left alone for 19 minutes
  training (RAM 0x34/0x35)   Ver. 1: +2 for every training, won or not; Ver. 2 and 3: +1
                             for every training that was won
  overfeeding (RAM 0x32)     meat until it turns it down (its fill goes up to 24)
  disturbances (RAM 0x33)    it was woken from its sleep: it wakes when it is fed or trained
  battles (RAM 0x99)         needed for the last stage only, counted up to 15
  score of wins (RAM 0x98)   one more for a fight won, one less for one lost, 0 to 15

The second stage becomes the first of the third with up to 3 care mistakes, the other one
with 4 or more. What the third stage becomes is in the tables below (ROWS): with up to 3
care mistakes only the training counts, with 4 or more also overfeeding and disturbances.
Whoever fits no row becomes the one that nobody wants (Numemon, Vegimon, Scumon).
The numbers of the charts mean the training counter of the device, so on Ver. 1, which
counts in twos, half as many trainings do (Greymon from 16). And two lines of Ver. 2 and 3
are not as the charts on that page have them: the second rookie becomes Yukidarumon or
Bakemon with a counter of 8 to 15 (not 8 to 31), Whamon or Drimogemon from 16 (not 32).

The last stage takes 15 battles on the third stage and a score of 9 or more wins at both
changes; even then the device throws dice, once at each of the two changes and at best
with one chance in two, so one life in four stays what it is whatever is done.
"""
BABY1, BABY2, ROOKIE_A, ROOKIE_B = 1, 2, 3, 4
C, D, E, F, G, H, I = 5, 6, 7, 8, 9, 10, 11        # the fourth stage, as the charts letter it
J, K, L = 12, 13, 14                                # the last
MANY = 255


def row(to, mistakes, counter=(0, MANY), overfed=(0, MANY), disturbed=(0, MANY)):
    """One line of a chart: whoever has these counters (each a span, both ends included)
    becomes this character. mistakes is False for up to 3 and True for 4 or more. counter
    is the training counter as the device keeps it (Ver. 1 counts in twos)."""
    return {"to": to, "mistakes": mistakes, "counter": counter, "overfed": overfed,
            "disturbed": disturbed}


class Chart:
    """The growth rules of one version."""

    BABY, CHILD = BABY1, BABY2
    LUCKY = None
    COCOON = None
    DEAD = 15
    ROOKIES = (ROOKIE_A, ROOKIE_B)
    CHAMPIONS = (C, D, E, F, G, H, I)
    ULTIMATES = {J: (C, E, G), K: (D, F, H), L: (I,)}
    ADULTS = CHAMPIONS
    GENERATIONS = ()
    BATTLES = 15            # battles as a rookie for the last stage
    WINS = 9                # the score of wins to have at both changes (it runs from 0 to 15)
    FIGHTERS = ROOKIES + CHAMPIONS      # who can fight at all
    FULL, METER_STEP, CALLING = 4, 1, ()     # for carebot_mothra.py: nothing calls to be told off
    MISTAKES = 4            # care mistakes from which the other half of a chart holds
    OVERFED_AT = 24         # its fill when it turns the meat down

    def __init__(self, version, names, rows, training, step):
        self.VERSION = version
        self.NAMES = dict(enumerate(("Ei",) + tuple(names)))
        self.TRAINING = training        # the game: "shadow", "bar" or "mash"
        self.TRAINING_STEP = step       # what the training counter goes up by for one training
        # {rookie: [row, ...]}, the first that fits holds. "trainings" is the span of the
        # counter in trainings: the least and the most that keep the counter inside it
        self.ROWS = {rookie: [dict(r, trainings=(
            -(-r["counter"][0] // step), MANY if r["counter"][1] == MANY else r["counter"][1] // step))
            for r in lines] for rookie, lines in rows.items()}
        self.GOALS = self.CHAMPIONS + (J, K, L)

    # -- what the device does ---------------------------------------------------

    def adult(self, stage, mistakes, trainings=0, overfed=0, disturbed=0):
        """What this character would turn into now; None if it stays what it is."""
        if stage == BABY1:
            return BABY2
        if stage == BABY2:
            return ROOKIE_A if mistakes < self.MISTAKES else ROOKIE_B
        if stage in self.ROOKIES:
            have = {"trainings": trainings, "overfed": overfed, "disturbed": disturbed}
            for r in self.ROWS[stage]:
                if r["mistakes"] == (mistakes >= self.MISTAKES) \
                        and all(r[k][0] <= have[k] <= r[k][1] for k in have):
                    return r["to"]
            return I
        return None

    def forecast(self, stage, mistakes, trainings=0, overfed=0, disturbed=0):
        way = []
        while len(way) < 4:
            nxt = self.adult(stage, mistakes, trainings, overfed, disturbed)
            if nxt is None:
                break
            way.append(nxt)
            stage, mistakes, trainings, overfed, disturbed = nxt, 0, 0, 0, 0
        return way

    # -- what the bot makes of it ------------------------------------------------

    def open_rows(self, rookie, champion, mistakes, trainings, overfed, disturbed):
        """The rows that still lead from this rookie to this champion: no counter is past
        what the row allows (they only ever go up)."""
        have = {"trainings": trainings, "overfed": overfed, "disturbed": disturbed}
        return [r for r in self.ROWS[rookie] if r["to"] == champion
                and (r["mistakes"] or mistakes < self.MISTAKES)
                and all(have[k] <= r[k][1] for k in have)
                and self.adult(rookie, *self.aim(r, mistakes, trainings, overfed, disturbed)) == champion]

    def aim(self, r, mistakes, trainings, overfed, disturbed):
        """The counters to have for this row, from the ones there are: each as low as the
        row lets it be, with a little to spare where the training has to be much."""
        lo, hi = r["trainings"]
        return (max(mistakes, self.MISTAKES) if r["mistakes"] else mistakes,
                max(trainings, min(lo + 2, hi) if lo else 0),
                max(overfed, r["overfed"][0]), max(disturbed, r["disturbed"][0]))

    def effort(self, r):
        """How much a row asks for: the bot takes the one that asks least."""
        return (r["mistakes"], r["overfed"][0] + r["disturbed"][0], r["trainings"][0])

    def champions(self, goal):
        return self.ULTIMATES.get(goal, (goal,))

    def reachable(self, stage, mistakes, trainings=0, overfed=0, disturbed=0):
        if stage in (0, BABY1):
            return list(self.GOALS)
        if stage == BABY2:
            rookies = self.ROOKIES if mistakes < self.MISTAKES else (ROOKIE_B,)
            return [g for g in self.GOALS if any(
                self.open_rows(r, c, 0, 0, 0, 0) for r in rookies for c in self.champions(g))]
        if stage in self.ROOKIES:
            return [g for g in self.GOALS if any(
                self.open_rows(stage, c, mistakes, trainings, overfed, disturbed)
                for c in self.champions(g))]
        if stage in self.CHAMPIONS:
            return [g for g in self.GOALS if g == stage or stage in self.ULTIMATES.get(g, ())]
        return [stage] if stage in self.GOALS else []

    def best(self, goal, rookie, mistakes, trainings, overfed, disturbed):
        """(champion, row) to go for from this rookie on the way to the goal, or None."""
        found = [(self.effort(r), n, c, r) for n, c in enumerate(self.champions(goal))
                 for r in self.open_rows(rookie, c, mistakes, trainings, overfed, disturbed)]
        return min(found, key=lambda f: f[:2])[2:] if found else None

    def plan(self, goal, stage, mistakes, trainings=0, overfed=0, disturbed=0):
        """How to get from here to the goal: a dict of what to reach as this character
        (care mistakes, trainings, overfeedings, disturbances, battles to fight), and the
        characters still to come under "way". None if the goal is out of reach."""
        if goal not in self.GOALS \
                or goal not in self.reachable(stage, mistakes, trainings, overfed, disturbed):
            return None
        last = goal in self.ULTIMATES
        idle = {"mistakes": mistakes, "trainings": 0, "overfed": 0, "disturbed": 0, "battles": 0}
        if stage in (0, BABY1, BABY2):
            # the rookie from which the goal asks least; the mistakes there are stay
            ways = [(self.best(goal, r, 0, 0, 0, 0), r) for r in self.ROOKIES
                    if r == ROOKIE_B or mistakes < self.MISTAKES]
            (champion, r), rookie = min((w for w in ways if w[0]),
                                        key=lambda w: (self.effort(w[0][1]), w[1]))
            way = ([BABY2] if stage != BABY2 else []) + [rookie, champion] + ([goal] if last else [])
            want = self.MISTAKES if rookie == ROOKIE_B and stage == BABY2 else mistakes
            return dict(idle, mistakes=max(mistakes, want), way=way)
        if stage in self.ROOKIES:
            champion, r = self.best(goal, stage, mistakes, trainings, overfed, disturbed)
            aim = self.aim(r, mistakes, trainings, overfed, disturbed)
            return {"mistakes": aim[0], "trainings": aim[1], "overfed": aim[2], "disturbed": aim[3],
                    "battles": self.BATTLES if last else 0,
                    "way": [champion] + ([goal] if last else [])}
        if stage in self.CHAMPIONS:
            return dict(idle, battles=1 if last and stage != goal else 0,
                        way=[goal] if stage != goal else [])
        return dict(idle, way=[])


NO, YES = False, True       # up to 3 care mistakes, 4 or more

V1 = Chart(1, (
    "Botamon", "Koromon", "Agumon", "Betamon", "Greymon", "Tyranomon", "Devimon", "Meramon",
    "Airdramon", "Seadramon", "Numemon", "Metal Greymon", "Mamemon", "Monzaemon"), {
    ROOKIE_A: [
        row(C, NO, (32, MANY)),
        row(E, NO, (0, 31)),
        row(D, YES, (5, 15), (3, MANY), (0, 4)),
        row(F, YES, (16, MANY), (3, MANY), (0, 6)),
        row(I, YES, (0, 4)),
        row(I, YES, overfed=(0, 2)),
    ],
    ROOKIE_B: [
        row(E, NO, (48, MANY)),
        row(F, NO, (0, 47)),
        row(G, YES, (8, 31), (0, 3), (9, MANY)),
        row(H, YES, (8, 31), (4, MANY), (0, 8)),
        row(I, YES, (0, 7)),
        row(I, YES, (32, MANY)),
    ],
}, "shadow", 2)

V2 = Chart(2, (
    "Punimon", "Tunomon", "Gabumon", "Elecmon", "Kabuterimon", "Garurumon", "Angemon",
    "Yukidarumon", "Birdramon", "Whamon", "Vegimon", "Skull Greymon", "Metal Mamemon",
    "Vademon"), {
    ROOKIE_A: [
        row(C, NO, (48, MANY)),
        row(E, NO, (0, 47)),
        row(D, YES, (5, 31), (3, MANY), (0, 4)),
        row(F, YES, (32, MANY), (3, MANY), (0, 6)),
        row(I, YES, (0, 4)),
        row(I, YES, overfed=(0, 2)),
    ],
    ROOKIE_B: [
        row(E, NO, (48, MANY)),
        row(G, NO, (0, 47)),
        row(F, YES, (8, 15), (0, 5), (5, MANY)),
        row(H, YES, (16, MANY), (6, MANY), (0, 4)),
        row(I, YES, (0, 7)),
        row(I, YES, (8, 15), (6, MANY)),
        row(I, YES, (16, MANY), (0, 5)),
    ],
}, "bar", 1)

V3 = Chart(3, (
    "Poyomon", "Tokomon", "Patamon", "Kunemon", "Unimon", "Centalmon", "Ogremon", "Bakemon",
    "Shellmon", "Drimogemon", "Scumon", "Andromon", "Giromon", "Etemon"), {
    ROOKIE_A: [
        row(C, NO, (48, MANY)),
        row(E, NO, (0, 47)),
        row(D, YES, (5, 31), (3, MANY), (0, 4)),
        row(F, YES, (32, MANY), (3, MANY), (0, 6)),
        row(I, YES, (0, 4)),
        row(I, YES, overfed=(0, 2)),
    ],
    ROOKIE_B: [
        row(E, NO, (48, MANY)),
        row(G, NO, (0, 47)),
        row(F, YES, (8, 15), (0, 5), (5, MANY)),
        row(H, YES, (16, MANY), (6, MANY), (0, 4)),
        row(I, YES, (0, 7)),
        row(I, YES, (8, 15), (6, MANY)),
        row(I, YES, (16, MANY), (0, 5)),
    ],
}, "mash", 1)
