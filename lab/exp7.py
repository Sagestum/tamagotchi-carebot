from multiprocessing import Pool
from lab import *
from exp4 import hold_run
def go(args):
    name, dm = args
    t, b = new_lab(discipline=False)
    assert t.load(open(name, "rb").read())
    hold_run(t, b, {0x42: 0, 0x51: dm}, 0.06 * 86400, 3)
    out = [(round(t.seconds / 86400, 3), t.memory(0x5d), t.memory(0x50))]
    last = [t.memory(0x5d)]
    def each():
        s = t.memory(0x5d)
        if s != last[0]:
            last[0] = s
            out.append((round(t.seconds / 86400, 3), s, t.memory(0x50), t.memory(0x54)))
        return b.status()["dead"]
    run(t, b, 30 * 86400, each, every=10.0)
    return name, dm, out, [t.memory(a) for a in (0x42, 0x51, 0x54)]
if __name__ == "__main__":
    with Pool(6) as p:
        for r in p.map(go, [("teen_3_2.sav", 2), ("teen_3_3.sav", 3), ("teen_3_2.sav", 0), ("teen_3_2.sav", 1)]):
            print(r, flush=True)
