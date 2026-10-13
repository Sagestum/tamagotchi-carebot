"""The Tamagotchi game for the Game Boy (1997): what is known of its pets.

A day of the game takes 48 minutes (an hour of it two), so a life is over within a real day
or two. All the characters of the first two Tamagotchi are in it. Which one a pet becomes is
decided by two values the game hides, "Fear" (stress) and "Mine" (selfishness), and at the
last step by whether it is cleverer or stronger (the chart follows the Tamagotchi Wiki,
tamagotchi.fandom.com/wiki/Tamagotchi_(GB)/Character_list; the numbers of the characters
and what is said of stress below are measured):

- a baby becomes Marutchi with a stress below 10, Tonmarutchi otherwise;
- Marutchi becomes Tamatchi (stress below 40, selfishness 0 or 1), Tongaritchi (below 40,
  2 or more), Kuchitamatchi (40 or more, 0 or 1) or Hashitamatchi; Tonmarutchi the same
  with a stress of 10 in place of 40;
- of the adults, each teenager has a pair for every band of stress and selfishness: the
  cleverer one (IQ above Body) and the stronger one.

Stress: its favourite food takes 2 away and praise after a game it has won 5; the food it
dislikes adds 1, ice cream 2, cake 4, an illness 10, and every hour with droppings lying
about, with an empty stomach or without any fun adds 8 to 10. At 100 the pet dies. Selfishness: one more for every
refusal that is not scolded. The study game raises the IQ by one when it goes well (the pet
answers by itself), the sports game the Body by one for five balls caught of ten.
"""
BREAD, MEAT, CARROT, ICE_CREAM, CAKE = range(5)     # as the food menu counts them
FOODS = {BREAD: "Brot", MEAT: "Fleisch", CARROT: "Karotte", ICE_CREAM: "Eis", CAKE: "Kuchen"}

# number of the character: (name, stage, favourite food, food it dislikes)
BABY, CHILD, TEEN, ADULT, SPECIAL = 1, 2, 3, 4, 5
CHARACTERS = {
    2: ("Babytchi", BABY, BREAD, CARROT), 3: ("ShiroBabytchi", BABY, BREAD, MEAT),
    4: ("Marutchi", CHILD, BREAD, CARROT), 5: ("Tonmarutchi", CHILD, BREAD, MEAT),
    6: ("Tamatchi", TEEN, BREAD, CARROT), 7: ("Tongaritchi", TEEN, CARROT, MEAT),
    8: ("Kuchitamatchi", TEEN, BREAD, MEAT), 9: ("Hashitamatchi", TEEN, MEAT, BREAD),
    10: ("Mametchi", ADULT, BREAD, None), 11: ("Mimitchi", ADULT, CARROT, None),
    12: ("Ginjirotchi", ADULT, BREAD, MEAT), 13: ("Pochitchi", ADULT, MEAT, CARROT),
    14: ("Maskutchi", ADULT, BREAD, None), 15: ("Zuccitchi", ADULT, MEAT, None),
    16: ("Kuchipatchi", ADULT, BREAD, CARROT), 17: ("Hashizotchi", ADULT, MEAT, CARROT),
    18: ("Nyorotchi", ADULT, MEAT, CARROT), 19: ("Kusatchi", ADULT, MEAT, CARROT),
    20: ("Tarakotchi", ADULT, MEAT, CARROT), 21: ("Takotchi", ADULT, MEAT, BREAD),
    22: ("Oyajitchi", SPECIAL, CARROT, BREAD), 23: ("Sekitoritchi", SPECIAL, MEAT, CARROT),
    24: ("Bill", SPECIAL, MEAT, CARROT),
}
NAMES = {number: c[0] for number, c in CHARACTERS.items()}
STAGES = {BABY: "Baby", CHILD: "Kind", TEEN: "Teenager", ADULT: "Erwachsener", SPECIAL: "Geheim"}
MAMETCHI, MIMITCHI, GINJIROTCHI, POCHITCHI, MASKUTCHI, ZUCCITCHI = 10, 11, 12, 13, 14, 15
KUCHIPATCHI, HASHIZOTCHI, NYOROTCHI, KUSATCHI, TARAKOTCHI, TAKOTCHI, BILL = 16, 17, 18, 19, 20, 21, 24
MARUTCHI, TONMARUTCHI, TAMATCHI, TONGARITCHI, KUCHITAMATCHI, HASHITAMATCHI = 4, 5, 6, 7, 8, 9
GOALS = (MAMETCHI, MIMITCHI, GINJIROTCHI, POCHITCHI, MASKUTCHI, ZUCCITCHI, KUCHIPATCHI,
         HASHIZOTCHI, NYOROTCHI, KUSATCHI, TARAKOTCHI, TAKOTCHI, BILL)
CALM = 40           # the stress below which a child or teenager counts as calm
MOST = 9            # (no upper end to the selfishness)

# The way the bot takes to each adult: the teenager, the band of selfishness it has to be in
# when it grows up, and whether it has to be cleverer (IQ above Body) or stronger. The child
# is always Marutchi; Kuchitamatchi is a Marutchi that was stressed. Stress and selfishness
# begin at 0 again with every new character; within one, selfishness only ever rises.
CLEVER, STRONG = "iq", "body"
WAYS = {
    MAMETCHI: (TAMATCHI, 0, 0, CLEVER), MIMITCHI: (TAMATCHI, 0, 0, STRONG),
    GINJIROTCHI: (TAMATCHI, 1, 1, CLEVER), POCHITCHI: (TAMATCHI, 1, 1, STRONG),
    MASKUTCHI: (TAMATCHI, 2, MOST, CLEVER), ZUCCITCHI: (TAMATCHI, 2, MOST, STRONG),
    KUCHIPATCHI: (KUCHITAMATCHI, 0, 1, CLEVER), HASHIZOTCHI: (KUCHITAMATCHI, 0, 1, STRONG),
    KUSATCHI: (KUCHITAMATCHI, 2, 3, CLEVER), NYOROTCHI: (KUCHITAMATCHI, 2, 3, STRONG),
    TAKOTCHI: (KUCHITAMATCHI, 4, MOST, CLEVER), TARAKOTCHI: (KUCHITAMATCHI, 4, MOST, STRONG),
    BILL: (TAMATCHI, 2, MOST, CLEVER),          # by way of Maskutchi
}


def child(stress):
    return MARUTCHI if stress < 10 else TONMARUTCHI


def teen(number, stress, selfish):
    """What a child becomes."""
    calm = stress < (CALM if number == MARUTCHI else 10)
    if number == MARUTCHI:
        fine = selfish <= 1
    else:
        fine = selfish == 0 if calm else selfish <= 1
    return (TAMATCHI if fine else TONGARITCHI) if calm else (KUCHITAMATCHI if fine else HASHITAMATCHI)


def adult(number, stress, selfish, iq, body):
    """What a teenager becomes: the clever and the strong one of its pair. One of them if it
    is as clever as strong (the game draws lots then), else that one alone."""
    calm = stress < CALM
    if number == TAMATCHI and calm:
        pair = (MAMETCHI, MIMITCHI) if selfish == 0 else (GINJIROTCHI, POCHITCHI) if selfish == 1 \
            else (MASKUTCHI, ZUCCITCHI)
    elif number == TONGARITCHI and calm:
        pair = (GINJIROTCHI, POCHITCHI) if selfish == 0 else (KUCHIPATCHI, HASHIZOTCHI)
    elif number == TONGARITCHI:
        pair = (KUSATCHI, NYOROTCHI) if selfish <= 3 else (TAKOTCHI, TARAKOTCHI)
    elif number == HASHITAMATCHI:
        pair = (KUSATCHI, NYOROTCHI) if selfish <= 2 else (TAKOTCHI, TARAKOTCHI)
    elif number in (TAMATCHI, KUCHITAMATCHI):
        pair = (KUCHIPATCHI, HASHIZOTCHI) if selfish <= 1 else (KUSATCHI, NYOROTCHI) if selfish <= 3 \
            else (TAKOTCHI, TARAKOTCHI)
    else:
        return []
    return list(pair) if iq == body else [pair[0] if iq > body else pair[1]]


def forecast(number, stress, selfish, iq, body):
    """The characters it becomes next if nothing changes."""
    kind = stage(number)
    if kind == BABY:
        return [child(stress)]
    if kind == CHILD:
        return [teen(number, stress, selfish)]
    if kind == TEEN:
        return adult(number, stress, selfish, iq, body)
    return [BILL] if number in (MASKUTCHI, ZUCCITCHI) else []


def open_to(goal, number, selfish):
    """Whether this pet can still become the goal, as far as its character and its
    selfishness (which never falls) tell."""
    if goal not in WAYS:
        return False
    wanted, low, high, _ = WAYS[goal]
    kind = stage(number)
    if number == goal or (goal == BILL and number in (MASKUTCHI, ZUCCITCHI)):
        return True
    if kind == BABY:
        return True
    if kind == CHILD:
        return number == MARUTCHI and selfish <= 1
    if kind == TEEN:
        return number == wanted and selfish <= high
    return False


def stage(number):
    return CHARACTERS[number][1] if number in CHARACTERS else 0


# -- the chart, for the page ----------------------------------------------------------------
# The eggs as they stand in the egg room, 1 to 8, and the baby in each (measured: forty
# hatchings of every egg, none another way)
EGGS = {2: (2, 4, 5, 8), 3: (1, 3, 6, 7)}
# Two characters only the Japanese edition has (after the Wiki; ours is the international one,
# in which Maskutchi and Zuccitchi become Bill at once)
ABSENT = {
    22: "Nur in der japanischen Fassung des Spiels (laut Wiki: aus Maskutchi mit Stress unter 20 oder aus "
        "Zuccitchi mit Stress über 20). In unserer internationalen Fassung werden beide stattdessen zu Bill.",
    23: "Nur in der japanischen Fassung des Spiels (laut Wiki: aus Maskutchi mit Stress über 20 oder aus "
        "Zuccitchi mit Stress unter 20). In unserer internationalen Fassung werden beide stattdessen zu Bill.",
}
STUDY_FROM, STUDY_TO = 10, 17       # the hours of the game's day the study game does not stress in


def span(low, high, most, what):
    """A band of a value in words: "Egoismus 0 oder 1"; nothing if it is all of them."""
    if low == 0 and high == most:
        return ""
    if low == high:
        return "%s %d" % (what, low)
    if high == most:
        return "%s %d oder mehr" % (what, low)
    if low == 0 and what == "Stress":
        return "Stress unter %d" % (high + 1)
    return "%s %d %s %d" % (what, low, "oder" if high == low + 1 else "bis", high)


def branches(number):
    """Where a character goes from here: [(the characters, the condition in words)], read off
    the rules above by trying every stress and selfishness."""
    kind = stage(number)
    if kind == BABY:
        then = lambda stress, selfish: (child(stress),)
    elif kind == CHILD:
        then = lambda stress, selfish: (teen(number, stress, selfish),)
    elif kind == TEEN:
        then = lambda stress, selfish: tuple(adult(number, stress, selfish, 0, 0))
    else:
        return [((BILL,), "ohne weitere Bedingung")] if number in (MASKUTCHI, ZUCCITCHI) else []
    # bands of stress within which the selfishness alone decides
    bands = []
    for stress in range(100):
        column = [then(stress, selfish) for selfish in range(MOST + 1)]
        if bands and bands[-1][2] == column:
            bands[-1][1] = stress
        else:
            bands.append([stress, stress, column])
    out = []
    for low, high, column in bands:
        start = 0
        for selfish in range(1, MOST + 2):
            if selfish > MOST or column[selfish] != column[start]:
                words = [span(low, high, 99, "Stress"), span(start, selfish - 1, MOST, "Egoismus")]
                out.append((column[start], ", ".join(w for w in words if w)))
                start = selfish
    return out


def steps(number):
    """What the bot does to get to this character: a (heading, text) for every stage of the
    way. None for a character it does not steer for."""
    egg = ("Ei", "Der Bot wählt nicht aus: Er nimmt das Ei, auf dem die Hand steht. Das Ei entscheidet "
           "über das Baby (Ei 1, 3, 6 und 7: ShiroBabytchi; Ei 2, 4, 5 und 8: Babytchi).")
    baby = ("Baby", "Gut pflegen, damit der Stress unter 10 bleibt: mit Brot satt füttern (das Lieblingsessen "
            "nimmt 2 Stress), Haufen gleich wegräumen, Krankheiten behandeln, bei zu wenig Glück spielen. "
            "Nach 5 Spielstunden (ShiroBabytchi) oder 6 (Babytchi) wird es Marutchi.")
    calm = ("Kind (Marutchi)", "Weiter gut pflegen: den Stress unter %d halten und jede Verweigerung schimpfen, "
            "damit der Egoismus bei 0 oder 1 bleibt. Ab Stress 30 spielt er ein Spiel um das Lob (Lob nimmt "
            "5 Stress). So wird es Tamatchi." % CALM)
    stressed = ("Kind (Marutchi)", "Absichtlich stressen, bis der Stress bei %d oder mehr liegt: Er füttert "
                "%s (mag Marutchi nicht), lobt nicht und lässt Haufen liegen – aber nur bis Stress 48 und nie "
                "nach 18 Uhr, denn bei Stress 100 stirbt das Tier, und im Schlaf lässt sich nicht putzen. "
                "Verweigerungen schimpft er weiter (Egoismus 0 oder 1). So wird es Kuchitamatchi."
                % (CALM, FOODS[CHARACTERS[MARUTCHI][3]]))
    if number in EGGS:
        return [egg]
    if number == MARUTCHI:
        return [egg, baby]
    if number in (TAMATCHI, KUCHITAMATCHI):
        return [egg, baby, calm if number == TAMATCHI else stressed]
    if number not in WAYS:
        return None
    wanted, low, high, more = WAYS[number]
    selfish = span(low, high, MOST, "Egoismus") or "Egoismus beliebig"
    text = ("Jede Verweigerung schimpfen" if low == 0 else
            "Die erste Verweigerung ungeschimpft durchgehen lassen, jede weitere schimpfen" if low == 1 else
            "Die ersten %d Verweigerungen ungeschimpft durchgehen lassen, jede weitere schimpfen" % low)
    text += " (Ziel beim Erwachsenwerden: %s). " % selfish
    text += ("Den Stress unter %d halten: gute Pflege und ab Stress 30 ein Spiel um das Lob. " % CALM
             if wanted == TAMATCHI else "Der Stress entscheidet hier nichts mehr; er pflegt gut, damit es nicht stirbt. ")
    pair = next(to for to, _ in branches(wanted) if (MASKUTCHI if number == BILL else number) in to)
    if more == CLEVER:
        text += ("Dazu das Lernspiel (nur zwischen %d und %d Uhr im Spiel, sonst stresst es), bis der IQ um 2 über "
                 "dem Körper-Wert liegt: Der Klügere des Paars wird %s, der Stärkere %s."
                 % (STUDY_FROM, STUDY_TO, NAMES[pair[0]], NAMES[pair[1]]))
    else:
        text += ("Dazu das Sportspiel, bis der Körper-Wert um 2 über dem IQ liegt: Der Stärkere des Paars wird "
                 "%s, der Klügere %s." % (NAMES[pair[1]], NAMES[pair[0]]))
    out = [egg, baby, calm if wanted == TAMATCHI else stressed, ("Teenager (%s)" % NAMES[wanted], text)]
    if number == BILL:
        out.append(("Erwachsener (Maskutchi)", "Nichts Besonderes mehr: In der internationalen Fassung des Spiels "
                    "wird nach dem Wiki jeder Maskutchi (und jeder Zuccitchi) zu Bill. Im Testlauf geschah das am "
                    "9. Spieltag."))
    return out


def way_to(number):
    """The characters on the bot's way to this one, itself the last; empty if it has none."""
    if steps(number) is None:
        return []
    if number in EGGS:
        return [number]
    if number == MARUTCHI:
        return [number]
    if number in (TAMATCHI, KUCHITAMATCHI):
        return [MARUTCHI, number]
    return [MARUTCHI, WAYS[number][0]] + ([MASKUTCHI] if number == BILL else []) + [number]


def chart():
    """All of it for the page of the chart."""
    return {
        "names": NAMES, "stageNames": STAGES, "foods": FOODS, "eggs": EGGS, "goals": list(GOALS),
        "characters": {n: {"stage": c[1], "likes": c[2], "dislikes": c[3]} for n, c in CHARACTERS.items()},
        "edges": [{"from": n, "to": list(to), "when": when} for n in CHARACTERS for to, when in branches(n)],
        "steps": {n: steps(n) for n in CHARACTERS},
        "way": {n: way_to(n) for n in CHARACTERS},
        "absent": ABSENT,
    }


# What a meal does, measured: the pounds it adds and what it does to the stress by itself.
# On top of that its favourite calms a pet by 2 and what it dislikes stresses it by 2 – and a
# meal that brings the weight to a full ten stresses it by 10, every meal at 99 pounds by 20.
# (That, not age, is what wears a pet down: one that eats bread grows a pound with every meal.)
MEALS = {BREAD: (1, 0), MEAT: (2, 2), CARROT: (0, -1)}
HEAVIEST = 99


def meal_stress(number, food, weight):
    """What this meal would do to the stress of this character at this weight."""
    gain, stress = MEALS[food]
    liked, disliked = CHARACTERS[number][2:] if number in CHARACTERS else (BREAD, None)
    stress += -2 if food == liked else 2 if food == disliked else 0
    if gain and weight + gain >= HEAVIEST:
        stress += 20
    elif (weight + gain) // 10 > weight // 10:
        stress += 10
    return stress


def meal(number, weight):
    """The meal that is best for its nerves; of two as good the lighter one."""
    return min(MEALS, key=lambda food: (meal_stress(number, food, weight), MEALS[food][0]))


def favourite(number):
    """The food that fills it and calms it; bread for one that is not known."""
    return CHARACTERS[number][2] if number in CHARACTERS else BREAD


# What a pet may be called: up to six letters
PET_NAMES = (
    "Adalie", "Adrian", "Agatha", "Alaric", "Aleida", "Alfred", "Alison", "Alyona", "Alyssa",
    "Amalia", "Amaris", "Amelia", "Amelie", "Anders", "Andrew", "Archer", "Arthur", "Ashley",
    "Ashton", "Astrid", "Audrey", "August", "Aurora", "Avidan", "Azalea", "Bailey", "Bennet",
    "Benton", "Bethan", "Blaire", "Blythe", "Bonnie", "Brenna", "Brinna", "Briony", "Britta",
    "Brogan", "Brynne", "Bryson", "Burton", "Callie", "Callum", "Calvin", "Carson", "Carter",
    "Cassie", "Cecily", "Cedric", "Charli", "Claire", "Connie", "Connor", "Dahlia", "Damien",
    "Daniel", "Daphne", "Darren", "Deanna", "Dexter", "Dianna", "Dorian", "Eartha", "Edmund",
    "Edward", "Elaina", "Elaine", "Eliana", "Elijah", "Elinor", "Elliot", "Elodie", "Eloise",
    "Elowen", "Emilia", "Emilio", "Emmett", "Ernest", "Esther", "Eudora", "Evelyn", "Finley",
    "Gatlin", "George", "Gerard", "Gideon", "Graham", "Hailey", "Hallie", "Hannah", "Harlan",
    "Harper", "Hayden", "Hector", "Helena", "Hudson", "Hunter", "Imogen", "Ingrid", "Isabel",
    "Isaiah", "Isidor", "Isobel", "Jasper", "Javier", "Jeremy", "Joella", "Jordan", "Joseph",
    "Joshua", "Josiah", "Julian", "Julien", "Juliet", "Keegan", "Kelley", "Kelsey", "Kieran",
    "Kilian", "Landon", "Laurel", "Lauren", "Leland", "Lenora", "Lenore", "Leonie", "Lilian",
    "Linden", "Lionel", "Louisa", "Louise", "Lucine", "Maddie", "Maisie", "Margot", "Marina",
    "Marion", "Marley", "Marlow", "Martin", "Melina", "Melody", "Millie", "Miriam", "Mollie",
    "Morgan", "Naomi", "Nathan", "Nation", "Newton", "Noelle", "Odessa", "Oliver", "Olivia",
    "Parker", "Payton", "Peyton", "Philip", "Phoebe", "Porter", "Rafael", "Ramona", "Regina",
    "Reuben", "Robert", "Rowena", "Ruben", "Ryland", "Sabine", "Samara", "Samuel", "Sawyer",
    "Shanna", "Shelby", "Shiloh", "Sidney", "Skyler", "Sloane", "Sophie", "Stella", "Sutton",
    "Sylvan", "Sylvia", "Talbot", "Tallis", "Taylor", "Teagan", "Teresa", "Thalia", "Thomas",
    "Tucker", "Verity", "Victor", "Violet", "Vivian", "Warren", "Waylon", "Wesley", "Weston",
    "Wilbur", "Willow", "Winter", "Xander", "Xavier", "Zander",
)


# -- names that tell the descent ------------------------------------------------------------
# A pet that follows one that died bears the last three letters of that one's name, and three
# new ones behind them: Anaris, Risome, Omekel. So that the names can be spoken, the new
# letters are a syllable of one of four shapes, and the two halves have to go together.
VOWELS = "aeiou"
ONSETS = "bdfghklmnprstvz"              # consonants a syllable may begin with
CODAS = "dklmnrst"                      # and end with
SOFT = "lmnrs"                          # the ones another consonant may follow
PAIRS = ("ia", "io", "ea", "eo", "ei", "ai", "au", "ie")    # two vowels in a row
ENDS = ("nd", "ld", "rt", "nt", "rn", "rd", "st", "rk")
# nothing a pet should be called, in German or in English
UNFIT = ("ars", "ass", "cum", "fag", "fck", "fic", "fik", "fuc", "fuk", "fut", "hur", "jud", "kak", "kot", "nig",
         "nut", "pim", "pis", "sau", "sex", "tit", "tot", "wix", "nazi", "anal", "anus", "homo", "sado", "dildo")


def speakable(text):
    """Whether these letters can be said: never three vowels or three consonants in a row,
    two vowels only as one of the known pairs, and two consonants inside only after a soft
    one. (A y counts as a vowel: it comes with the names of old.)"""
    text = text.lower()
    if not text.isalpha() or any(bad in text for bad in UNFIT):
        return False
    vowel = [c in VOWELS + "y" for c in text]
    for i in range(len(text) - 1):
        a, b = text[i], text[i + 1]
        if i + 2 < len(text) and vowel[i] == vowel[i + 1] == vowel[i + 2]:
            return False
        if vowel[i] and vowel[i + 1] and a + b not in PAIRS:
            return False
        if not vowel[i] and not vowel[i + 1] and (a == b or (a not in SOFT and (i == 0 or a + b not in ENDS))):
            return False
    return not (len(text) > 1 and not vowel[0] and not vowel[1])    # nor two consonants in front


SYLLABLES = tuple(s for s in sorted(set(
    [c + v + d for c in ONSETS for v in VOWELS for d in CODAS]              # kel, ris
    + [v + c + w for v in VOWELS for c in ONSETS for w in "aeio"]           # ome, ana
    + [c + p for c in ONSETS for p in PAIRS]                                # lia, neo
    + [v + e for v in "aeio" for e in ENDS])) if speakable(s))              # and, ert


def pleasant(name):
    """Whether a name of two syllables also sounds like one: no letter three times, no two
    letters twice, and vowels in a row or consonants at the end only in one of its halves."""
    name = name.lower()
    twos = [name[i:i + 2] for i in range(len(name) - 1)]
    vowel = [c in VOWELS + "y" for c in name]
    doubled = sum(vowel[i] and vowel[i + 1] for i in range(len(name) - 1))
    return max(name.count(c) for c in name) < 3 and len(set(twos)) == len(twos) and doubled < 2 \
        and not (name[1:3] in ENDS and name[-2:] in ENDS)


def heir(parent, taken=()):
    """The names a child of this one may bear: its last three letters and a new syllable that
    none of the taken names ends with. Empty if the parent's end cannot begin a name."""
    head = (parent or "")[-3:].lower()
    if len(head) < 3 or not speakable(head):
        return []
    gone = {name[-3:].lower() for name in taken if name}
    return [(head + new).capitalize() for new in SYLLABLES
            if new != head and new not in gone and speakable(head + new) and pleasant(head + new)]
