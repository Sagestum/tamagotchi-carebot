import sys
from multiprocessing import Pool
from lab import *

def hold_run(t, b, vals, seconds, stage):
    def each():
        if t.memory(0x5d) != stage:
            return True
        for a, v in vals.items(): poke(t, a, v)
    return run(t, b, seconds, each, every=5.0)

def mkbase(cm):
    t, b = new_lab(discipline=False)
    assert t.load(open("base_child.sav", "rb").read())
    poke(t, 0x42, cm)
    run(t, b, 0.03 * 86400)
    stage = t.memory(0x5d)
    hold_run(t, b, {0x42: cm, 0x43: 0}, (4.03 - 2.11) * 86400, stage)
    open("base_teen%d.sav" % stage, "wb").write(t.save())
    return stage, t.seconds / 86400, b.status()

def trial(args):
    teen, cm, disc, d51 = args
    t, b = new_lab(discipline=False)
    assert t.load(open("base_teen%d.sav" % teen, "rb").read())
    hold_run(t, b, {0x42: cm, 0x43: disc, 0x51: d51}, 1.3 * 86400, teen)
    when = t.seconds / 86400
    run(t, b, 30)
    return args, t.memory(0x5d), round(when, 3), [t.memory(a) for a in (0x42, 0x43, 0x51, 0x50)]

if __name__ == "__main__":
    with Pool(16) as p:
        if sys.argv[1] == "base":
            print(p.map(mkbase, [0, 3]))
        else:
            jobs = [(teen, cm, disc, d51) for teen in (3, 4) for d51 in (0,) for disc in (0, 4, 8, 12) for cm in range(16)]
            jobs += [(teen, cm, disc, 9) for teen in (3, 4) for disc in (0, 12) for cm in (0, 2, 3, 6)]
            res = p.map(trial, jobs, chunksize=1)
            pickle.dump(res, open("exp4.pkl", "wb"))
            R = {r[0]: r for r in res}
            for teen in (3, 4):
                for disc in (0, 4, 8, 12):
                    print("teen %d disc %2d:" % (teen, disc), " ".join("%x" % R[(teen, cm, disc, 0)][1] for cm in range(16)))
            for r in res:
                if r[0][3] == 9 or r[0][1] in (0, 3, 15): print(r)
