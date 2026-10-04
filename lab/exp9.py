from lab import *
def snaps(t, n=8, gap=7):
    out = []
    for _ in range(n):
        run(t, None, gap); out.append(ram(t))
    return out
def stable(ss):
    return {a: ss[0][a] for a in range(0x280) if all(s[a] == ss[0][a] for s in ss)}
t, b = new_lab(discipline=False)
run(t, b, 0.075 * 86400); b.stop(); run(t, None, 20)
base = t.save()
# no call
none = stable(snaps(t))
# hunger call
t.load(base); poke(t, 0x40, 0); run(t, None, 13 * 60); assert t.frame()[1][7]
hung = stable(snaps(t))
# happy call
t.load(base); poke(t, 0x41, 0); run(t, None, 25 * 60); assert t.frame()[1][7]
happ = stable(snaps(t))
# discipline call: continue with the bot until one starts
t.load(base)
def each():
    st = b.status()
    return st["attention"] and st["hunger"] > 0 and st["happy"] > 0 and not st["asleep"]
assert run(t, b, 86400, each, every=1.0)
print("discipline call at day", t.seconds / 86400, b.status())
b.stop(); run(t, None, 30)
pre = [t.memory(a) for a in (0x40, 0x41)]
disc = stable(snaps(t))
run(t, None, 16 * 60)
print("after timeout: att", t.frame()[1][7], "0x51", t.memory(0x51))
after = stable(snaps(t))
def show(name, x, ref):
    print(name, " ".join("%03x:%x>%x" % (a, ref[a], x[a]) for a in sorted(x) if a in ref and x[a] != ref[a]))
show("hunger vs none", hung, none)
show("happy  vs none", happ, none)
show("disc   vs none", disc, none)
show("disc   vs after", disc, after)
