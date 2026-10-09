"""A model that runs but has not been measured: nothing is read from its RAM and nothing is
done for it. The page shows its screen and takes its buttons."""
from carebot import CareBot


class PlainBot(CareBot):
    def status(self):
        return {
            "stage": 0,
            "away": False, "praying": False, "sickness": 0, "leaving": False, "thanked": False,
            "generation": None,
            "name": self.model.name.replace("Tamagotchi ", ""),
            "hunger": 0, "happy": 0, "weight": 0,
            "poop": 0, "mistakes": 0, "missed": 0, "training": 0, "kind": 0,
            "sick": False, "asleep": False, "attack": False,
            "cocoon": False, "temperature": None, "friendship": None, "sweetness": None,
            "look": None, "back": False,
            "light": True, "attention": False, "scold": False, "dead": False,
            "game": None, "clock": "–",
        }

    def growth(self, st):
        return None

    def plan(self):
        return None
