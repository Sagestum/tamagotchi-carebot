"""The Tamaotch (Tamaotch, 1998): what is known of it so far.

Another program once more. It keeps its state in the upper half of the RAM, wants a
button held for a third of a second before it takes it, and its training games are
answered by tapping the case. There is no Care-Bot for it yet: this class only reads the
values that have been found, so that the page can show them.
"""
from carebot import CareBot

# RAM cells of the Tamaotch ROM (found by experiment, one 4-bit value each)
MEM_MIN_LO, MEM_MIN_HI = 0x104, 0x105   # clock minutes, BCD
MEM_HOUR_LO, MEM_HOUR_HI = 0x106, 0x107  # clock hours, 0 to 11: bit 0 of the high cell is
                                        # the ten, bit 3 says afternoon
MEM_WEIGHT_LO, MEM_WEIGHT_HI = 0x154, 0x155  # BCD, grams
MEM_HUNGER, MEM_HAPPY = 0x1E0, 0x1E1    # hearts, 0 to 4


class TamaotchBot(CareBot):
    def status(self):
        m = self.tama.memory
        weight = m(MEM_WEIGHT_HI) * 10 + m(MEM_WEIGHT_LO)
        stage = 1 if weight else 0          # the egg weighs nothing
        hour = (m(MEM_HOUR_HI) & 1) * 10 + m(MEM_HOUR_LO) + (12 if m(MEM_HOUR_HI) & 8 else 0)
        return {
            "stage": stage,
            "away": False, "praying": False, "sickness": 0, "leaving": False, "thanked": False,
            "generation": None,
            "name": "Ei" if stage == 0 else "Tamaotch",
            "hunger": m(MEM_HUNGER),
            "happy": m(MEM_HAPPY),
            "weight": weight,
            "poop": 0, "mistakes": 0, "missed": 0, "training": 0, "kind": 0,
            "sick": False, "asleep": False, "attack": False,
            "cocoon": False, "temperature": None, "friendship": None, "sweetness": None,
            "look": None, "back": False,
            "light": True, "attention": False, "scold": False, "dead": False,
            "game": None,
            "clock": "%02d:%d%d" % (hour, m(MEM_MIN_HI), m(MEM_MIN_LO)),
        }

    def growth(self, st):
        return None

    def plan(self):
        return None             # nothing yet: it is played by hand
