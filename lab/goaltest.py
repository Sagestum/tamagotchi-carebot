import os, sys, collections
from multiprocessing import Pool
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, P)
from tama import Tama
from carebot import CareBot
import growth
def go(args):
    goal, days = args
    t = Tama(P + "/tama/tama.b", P + "/libtama.so")
    logs = []
    b = CareBot(t, lambda m: logs.append((round(t.seconds / 86400, 3), m)))
    b.realtime = False; b.goal = goal
    stages = []
    end = days * 86400; n = 0
    while t.seconds < end:
        t.run(1024); b.step(); n += 1
        if n % 320 == 0:
            st = b.status()
            if not stages or stages[-1][1] != st["stage"]:
                stages.append((round(t.seconds / 86400, 2), st["stage"], st["mistakes"], st["missed"]))
            if st["dead"]: break
    st = b.status()
    c = collections.Counter(m.split(" (")[0] for _, m in logs)
    return goal, stages, st["dead"], round(t.seconds / 86400, 2), dict(c), [l for l in logs if "Absicht" in l[1] or "gezählt" in l[1] or "verpasst" in l[1] or "Verwandelt" in l[1]]
if __name__ == "__main__":
    days = float(sys.argv[1])
    goals = [None] + list(growth.GOALS) if len(sys.argv) < 3 else [int(x) for x in sys.argv[2:]]
    with Pool(8) as p:
        for goal, stages, dead, end, c, ev in p.imap(go, [(g, days) for g in goals]):
            print("GOAL", growth.NAMES.get(goal), "->", growth.NAMES.get(stages[-1][1]), "OK" if stages[-1][1] == goal else "", stages, "dead" if dead else "", end)
            print("   ", c)
            for e in ev: print("     ", e)
