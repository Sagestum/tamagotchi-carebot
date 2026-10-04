from lab import *
t, b = new_lab(discipline=False)
run(t, b, 0.075 * 86400); b.stop(); run(t, None, 20)
base = t.save()
def vals(): return dict(att=t.frame()[1][7], hu=t.memory(0x40), ha=t.memory(0x41), cm=t.memory(0x42), disc=t.memory(0x43), dm=t.memory(0x51))
def do(gen):
    b.task = gen
    while b.task is not None:
        t.run(CHUNK); b.step() if t.seconds >= b.wake else None
        if b.task is None: break
# scold with no call at all
t.load(base); b.stop(); print("no call, before", vals())
b.task = b.scold(); run(t, b, 30) ; print("no call, after scold", vals())
# scold during a hunger call
t.load(base); b.stop(); poke(t, 0x40, 0); run(t, None, 13 * 60); print("hunger call", vals())
class NB(LabBot):
    def plan(self): return None
b.__class__ = NB
b.task = b.scold(); run(t, b, 30); print("after scold", vals())
run(t, b, 15 * 60); print("15 min later", vals())
