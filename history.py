"""The history of all the pets, kept for good: every life with the characters it went through,
and every line of the logs. One SQLite file next to the states (history.sqlite).

The pets run in processes of their own and only tell what happens (engine.Engine.tracks); the
server is the one that writes.
"""
import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS lives (
    key TEXT PRIMARY KEY,       -- given by the pet's process when the life begins
    pet TEXT NOT NULL,          -- the tab's id
    tab TEXT,                   -- and its name at the time
    model TEXT NOT NULL,
    place INTEGER NOT NULL DEFAULT 0,   -- Game Boy: which of the three places
    name TEXT,                  -- the pet's own name, if it has one
    began REAL,                 -- real time; NULL for a life from before this file
    ended REAL,
    ending TEXT,                -- "gestorben", "verabschiedet", "neu begonnen"
    goal TEXT,                  -- what the bot was raising, by name
    character INTEGER,          -- what it was last
    character_name TEXT
);
CREATE TABLE IF NOT EXISTS stages (
    life TEXT NOT NULL REFERENCES lives(key),
    at REAL,
    character INTEGER NOT NULL,
    character_name TEXT,
    data TEXT                   -- JSON: hearts, weight and whatever else the model counts
);
CREATE INDEX IF NOT EXISTS stages_life ON stages(life);
CREATE TABLE IF NOT EXISTS log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pet TEXT NOT NULL,
    at REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS log_pet ON log(pet, id);
CREATE TABLE IF NOT EXISTS album (      -- the Game Boy game's own album, entry by entry
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pet TEXT NOT NULL,
    tab TEXT,
    seen REAL NOT NULL,         -- when the entry was first found there
    place INTEGER,              -- which of its eight places
    name TEXT,
    character INTEGER,
    character_name TEXT,
    age INTEGER,
    weight INTEGER,
    data TEXT,                  -- JSON: hearts and the other values it had at the end
    UNIQUE (pet, name, character, age, weight)
);
"""


class History:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock, self.db:
            self.db.executescript(SCHEMA)

    def write(self, pet, tab, model, events):
        """What a pet's process has told: a list of tuples, the kind first."""
        with self.lock, self.db:
            for event in events:
                kind, rest = event[0], event[1:]
                if kind == "log":
                    self.db.execute("INSERT INTO log (pet, at, text) VALUES (?, ?, ?)", (pet,) + tuple(rest))
                elif kind == "begin":
                    key, at, place, name, goal = rest
                    self.db.execute(
                        "INSERT OR IGNORE INTO lives (key, pet, tab, model, place, name, began, goal) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (key, pet, tab, model, place, name, at, goal))
                elif kind == "stage":
                    key, at, number, number_name, name, goal, data = rest
                    self.db.execute("INSERT INTO stages (life, at, character, character_name, data) "
                                    "VALUES (?, ?, ?, ?, ?)", (key, at, number, number_name, json.dumps(data)))
                    self.db.execute("UPDATE lives SET character = ?, character_name = ?, goal = ?, "
                                    "name = COALESCE(?, name) WHERE key = ?",
                                    (number, number_name, goal, name, key))
                elif kind == "label":
                    key, name, goal = rest
                    self.db.execute("UPDATE lives SET goal = ?, name = COALESCE(?, name) WHERE key = ?",
                                    (goal, name, key))
                elif kind == "album":
                    at, entries = rest
                    for a in entries:
                        self.db.execute(
                            "INSERT OR IGNORE INTO album (pet, tab, seen, place, name, character, "
                            "character_name, age, weight, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (pet, tab, at, a["place"], a["name"], a["character"], a["characterName"],
                             a["age"], a["weight"], json.dumps(a["data"])))
                elif kind == "end":
                    key, at, how = rest
                    self.db.execute("UPDATE lives SET ended = ?, ending = ? WHERE key = ? AND ended IS NULL",
                                    (at, how, key))
                elif kind == "old":
                    self.take_old(pet, tab, model, rest[0])

    def take_old(self, pet, tab, model, lives):
        """The lives a pet's chronicle held before there was this file: they have their
        characters, but not when each of them came."""
        for i, life in enumerate(lives):
            key = "old-%s-%d" % (pet, int(life.get("began") or i))
            done = self.db.execute("SELECT 1 FROM lives WHERE key = ?", (key,)).fetchone()
            if done or not life.get("stages"):
                continue
            last = life["stages"][-1]
            self.db.execute(
                "INSERT INTO lives (key, pet, tab, model, began, ended, ending, character, character_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (key, pet, tab, model, life.get("began"), life.get("ended"), life.get("end"), last[0], last[1]))
            for number, name in life["stages"]:
                self.db.execute("INSERT INTO stages (life, at, character, character_name, data) "
                                "VALUES (?, NULL, ?, ?, NULL)", (key, number, name))

    # -- reading -----------------------------------------------------------

    def lives(self, pet=None, limit=200):
        """The lives, the newest first, each with its characters in order."""
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM lives WHERE (? IS NULL OR pet = ?) "
                "ORDER BY COALESCE(began, 0) DESC, rowid DESC LIMIT ?", (pet, pet, limit)).fetchall()
            out = []
            for row in rows:
                life = dict(row)
                life["stages"] = [
                    {"at": s["at"], "character": s["character"], "name": s["character_name"],
                     "data": json.loads(s["data"]) if s["data"] else None}
                    for s in self.db.execute("SELECT * FROM stages WHERE life = ? ORDER BY rowid", (row["key"],))]
                out.append(life)
        return out

    def log(self, pet, before=None, limit=200):
        """Lines of a pet's log, the newest first; before: the id to go on from."""
        with self.lock:
            rows = self.db.execute(
                "SELECT id, at, text FROM log WHERE pet = ? AND (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",
                (pet, before, before, limit)).fetchall()
        return [dict(row) for row in rows]

    def seen(self):
        """Of every model the characters there have been: how often and when first."""
        with self.lock:
            rows = self.db.execute(
                "SELECT l.model AS model, s.character AS character, s.character_name AS name, "
                "COUNT(DISTINCT s.life) AS times, MIN(COALESCE(s.at, l.began)) AS first "
                "FROM stages s JOIN lives l ON l.key = s.life GROUP BY l.model, s.character "
                "ORDER BY l.model, s.character").fetchall()
        out = {}
        for row in rows:
            out.setdefault(row["model"], []).append(
                {"character": row["character"], "name": row["name"], "times": row["times"], "first": row["first"]})
        return out

    def album(self, pet=None):
        """The entries of the Game Boy game's album that have been seen, the newest first."""
        with self.lock:
            rows = self.db.execute("SELECT * FROM album WHERE (? IS NULL OR pet = ?) ORDER BY id DESC",
                                   (pet, pet)).fetchall()
        return [dict(row, data=json.loads(row["data"]) if row["data"] else None) for row in rows]

    def counts(self):
        with self.lock:
            return {table: self.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                    for table in ("lives", "stages", "log", "album")}

    def close(self):
        with self.lock:
            self.db.close()


def stamp(at):
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(at)) if at else "–"
