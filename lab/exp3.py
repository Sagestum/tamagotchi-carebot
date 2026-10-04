from lab import *
base = open("base_child.sav", "rb").read()
t, b = new_lab(discipline=False)
def trial(cm, disc, d51):
    assert t.load(base)
    b.stop()
    poke(t, 0x42, cm); poke(t, 0x43, disc); poke(t, 0x51, d51)
    start = t.seconds
    def each():
        return t.memory(0x5d) != 2
    run(t, b, 0.05 * 86400, each, every=5.0)
    when = t.seconds
    run(t, b, 30)
    return t.memory(0x5d), (when - start), [t.memory(a) for a in (0x42, 0x43, 0x51, 0x50)]
for d51 in (0, 9):
    for disc in (0, 4, 8, 12):
        print("d51=%d disc=%2d:" % (d51, disc), " ".join("%x" % trial(cm, disc, d51)[0] for cm in range(16)))
print(trial(0, 12, 0), trial(5, 12, 0))
