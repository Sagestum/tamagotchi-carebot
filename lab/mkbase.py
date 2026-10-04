from lab import *
t, b = new_lab(discipline=False)
run(t, b, 2.080 * 86400)
open("base_child.sav", "wb").write(t.save())
print(b.status(), [hex(t.memory(a)) for a in (0x42, 0x43, 0x51, 0x54)])
