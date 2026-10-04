from lab import *
t, b = new_lab(discipline=False)
run(t, b, 0.075 * 86400)
b.stop(); run(t, None, 20)
base = t.save()
print(b.status(), [t.memory(a) for a in (0x40, 0x41, 0x42, 0x51)])
def trial(hu, ha, minutes=40):
    assert t.load(base)
    poke(t, 0x40, hu); poke(t, 0x41, ha)
    log = []; last = [None]
    def each():
        s = (bool(t.frame()[1][7]), t.memory(0x40), t.memory(0x41), t.memory(0x42), t.memory(0x51))
        if s != last[0]:
            last[0] = s; log.append((round((t.seconds) / 60 - 108, 1),) + s)
    run(t, None, minutes * 60, each, every=2.0)
    return log
for hu, ha in ((0, 15), (1, 15), (2, 15), (3, 15), (15, 0), (15, 1), (15, 2), (15, 3), (0, 0)):
    print("hunger=%d happy=%d:" % (hu, ha), trial(hu, ha))
