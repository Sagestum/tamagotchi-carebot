from multiprocessing import Pool
from lab import *
from exp4 import hold_run

def mkbase(args):
    cm, d51 = args
    t, b = new_lab(discipline=False)
    child = open("base_child.sav", "rb").read()
    def go(until=None):
        assert t.load(child); b.stop()
        poke(t, 0x42, cm); poke(t, 0x51, d51)
        run(t, b, 0.03 * 86400)
        stage = t.memory(0x5d)
        sub = t.memory(0x50)
        hold_run(t, b, {0x42: cm, 0x43: 0, 0x51: d51}, ((until or 9) - 2.11) * 86400, stage)
        return stage, sub
    stage, sub = go()
    T = t.seconds / 86400
    go(T - 0.008)
    name = "teen_%d_%d.sav" % (stage, sub)
    open(name, "wb").write(t.save())
    return name, stage, sub, round(T, 3), t.memory(0x5d)

def row(args):
    name, stage, cm = args
    t, b = new_lab(discipline=False)
    base = open(name, "rb").read()
    out = []
    for d51 in range(16):
        assert t.load(base); b.stop()
        hold_run(t, b, {0x42: cm, 0x51: d51}, 0.06 * 86400, stage)
        run(t, b, 30)
        out.append((t.memory(0x5d), t.memory(0x43), t.memory(0x50)))
    return out

if __name__ == "__main__":
    with Pool(16) as p:
        bases = p.map(mkbase, [(0, 0), (0, 3), (3, 0), (3, 3)])
        print(bases)
        for name, stage, sub, T, _ in bases:
            res = p.map(row, [(name, stage, cm) for cm in range(16)])
            print(name, "evolves at day", T, "(rows: care mistakes, columns: 0x51 0..15)")
            for cm, r in enumerate(res):
                print("  cm=%2d: " % cm + " ".join("%x" % x[0] for x in r) + "   disc after: " + " ".join("%x" % x[1] for x in r) + "   0x50: " + " ".join("%x" % x[2] for x in r))
