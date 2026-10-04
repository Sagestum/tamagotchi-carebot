import sys
from lab import *
name = sys.argv[1]
cfg = {"A": {}, "B": {"discipline": False}, "C": {"neglect": 1000},
       "D": {"lights": False}, "E": {"neglect": 1000, "neglect_what": ("hunger",)},
       "F": {"neglect": 1000, "neglect_what": ("happy",)},
       "G": {"neglect": 1000, "discipline": False}}[name]
days = float(sys.argv[2]) if len(sys.argv) > 2 else 7
t, b = new_lab(**cfg)
prev = None; hist = []; counts = {}; att = []
stages = []
def each():
    global prev
    r = [t.memory(a) for a in range(0x280)]
    st = b.status()
    if prev:
        for a in range(0x280):
            if r[a] != prev[a]:
                counts[a] = counts.get(a, 0) + 1
                if counts[a] < 400: hist.append((t.seconds, a, prev[a], r[a]))
    if not att or att[-1][1] != st["attention"]:
        att.append((t.seconds, st["attention"], st["hunger"], st["happy"], st["asleep"], st["light"]))
    if not stages or stages[-1][1] != st["stage"]:
        stages.append((t.seconds, st["stage"], ascii_frame(t.frame()[0])))
    prev = r
    return st["dead"] and t.seconds > 3600
run(t, b, days * 86400, each, every=5.0)
pickle.dump((hist, counts, b.logs, att, stages, t.save()), open("exp2_%s.pkl" % name, "wb"))
print(name, "end", t.seconds / 86400, b.status(), [(round(s/86400,2), g) for s, g, _ in stages])
