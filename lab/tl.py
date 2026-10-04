import pickle, sys
names, lim = sys.argv[1], float(sys.argv[2])
cells = [int(x,16) for x in sys.argv[3].split(",")]
for n in names:
    hist,counts,logs,att,stages,_ = pickle.load(open("exp2_%s.pkl" % n, "rb"))
    print("=====", n)
    ev = [(s, "%02x %x->%x" % (a,o,v)) for s,a,o,v in hist if a in cells]
    ev += [(s, "LOG " + m) for s,m in logs if not m.startswith("Sauber")]
    ev += [(x[0], "ATT %s hu=%d ha=%d asleep=%s light=%s" % tuple(x[1:])) for x in att]
    ev.sort()
    for s,m in ev:
        if s/86400 < lim: print("%6.3f %s" % (s/86400, m))
