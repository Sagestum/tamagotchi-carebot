"""What the Pocket Pikachu (1998) counts, read from its program and measured on it.

It does not grow. It keeps an account of affection, in watts:

- it begins at 1500 and holds 4000 at most;
- every hour takes 10 away;
- every watt walked (20 steps) adds 1, up to 250 a day;
- every watt given adds 1, up to 700 a day;
- walking while it sleeps (8 pm to 7 am) with the display on takes 200 away, disturbing it
  at play 20 or 100. With the display off the steps are counted and nothing is taken.

Once a day, at 8 in the morning, the account becomes the mood it shows: below 1000 it is
cross, from 1000 on at ease, from 2000 on it likes you, from 3000 on it loves you. An empty
account means it has left; shaking brings it back with 100.

The steps on the display are what it has seen of the world: at 150 000, 300 000 and
450 000 it begins to do new things (and goes to bed an hour later from 300 000 on), and
the counter ends at 999 999.
"""
START, MOST = 1500, 4000
HOURLY = 10
STEPS_PER_WATT = 20
WALKED_A_DAY, GIVEN_A_DAY = 250, 700
MOODS = {0: "weggelaufen", 1: "böse", 2: "zufrieden", 3: "mag dich", 4: "liebt dich"}
MOOD_FROM = {1: 1, 2: 1000, 3: 2000, 4: 3000}
UNLOCKS = (150000, 300000, 450000)
LAST = 999999

# The stages: what it has learnt by the steps, and the end of the counter
NAMES = {1: "Pikachu", 2: "Pikachu (150.000 Schritte)", 3: "Pikachu (300.000 Schritte)",
         4: "Pikachu (450.000 Schritte)", 5: "Pikachu (999.999 Schritte)",
         # The goals are ways of walking, not characters
         11: "Spaziergang: 3.000 Schritte am Tag", 12: "Wanderung: 10.000 Schritte am Tag",
         13: "Dauerlauf: Tag und Nacht"}
GOALS = (11, 12, 13)
DEFAULT = 5000                      # steps a day without a goal
PACE = {None: DEFAULT, 11: 3000, 12: 10000, 13: None}     # None: without pause
STEP = 0.5                          # seconds from step to step; faster ones are not all counted
MOST_A_DAY = int(86400 / STEP)


def stage(steps, unlock):
    return 5 if steps >= LAST else 1 + min(unlock, 3)


def mood(account):
    """The mood an account stands for (shown from the next morning on)."""
    return 0 if account <= 0 else 1 + min(account // 1000, 3)


def a_day(goal):
    """Steps a day the bot walks for this goal."""
    return PACE.get(goal, DEFAULT) or MOST_A_DAY


def balance(goal):
    """What a day changes on the account when the bot walks for this goal and gives
    away what it may: (walked, given, lost)."""
    watts = a_day(goal) // STEPS_PER_WATT
    return min(watts, WALKED_A_DAY), min(watts, GIVEN_A_DAY), 24 * HOURLY


def days_to(account, wanted, goal):
    """Days until the account has reached this much, or None if it never does."""
    walked, given, lost = balance(goal)
    gain = walked + given - lost
    if account >= wanted:
        return 0
    return None if gain <= 0 else -(-(wanted - account) // gain)


def days_to_steps(steps, wanted, goal):
    return 0 if steps >= wanted else -(-(wanted - steps) // a_day(goal))
