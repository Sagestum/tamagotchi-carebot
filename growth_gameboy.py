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
