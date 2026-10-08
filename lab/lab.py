import sys, os, pickle
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, P)
from tama import Tama, ascii_frame, BTN_A, BTN_B, BTN_C
import carebot, models
from carebot import CareBot

CHUNK = 1024
MEMLEN = 550
LABLIB = os.path.dirname(os.path.abspath(__file__)) + "/libtamalab.so"
ROM = os.environ.get("TAMA_ROM", P + "/tama/tama.b")   # another dump: TAMA_ROM=...
MODEL = models.identify(open(ROM, "rb").read()) or models.P1

def new(log=None):
    t = Tama(ROM, LABLIB)
    logs = []
    def lg(msg):
        logs.append((t.seconds, msg))
        if log: log(msg)
    b = CareBot(t, lg, model=MODEL)
    b.realtime = False
    b.logs = logs
    return t, b

def ram(t):
    s = t.save()[-MEMLEN:]
    return [(s[n // 2] >> (4 * (n % 2))) & 0xF for n in range(0x280)]

def poke(t, addr, val):
    t.lib.tama_set_memory(addr, val)

def run(t, b, seconds, each=None, every=1.0):
    """Run for emulated seconds; call each() every `every` emulated seconds."""
    end = t.seconds + seconds
    nxt = t.seconds
    while t.seconds < end:
        t.run(CHUNK)
        if b is not None:
            b.step()
        if each and t.seconds >= nxt:
            nxt += every
            if each():
                return True
    return False

class LabBot(CareBot):
    """CareBot with switches for experiments."""
    lights = True         # switch the light off at night
    neglect = 0           # seconds to ignore an empty meter (0 = care early)
    neglect_what = ("hunger", "happy")
    def plan(self):
        st = self.status(); now = self.tama.seconds
        if st["dead"] or st["stage"] == 0:
            return CareBot.plan(self)
        if not self.lights:
            if not st["light"]:
                return self.light(True)
            if st["asleep"]:
                return None
        if self.neglect:
            empty = [k for k in self.neglect_what if st[k] == 0]
            if not st["asleep"] and st["light"] and not st["poop"] and not st["sick"]:
                low = [k for k in self.neglect_what if st[k] < 3]
                if low and not empty:
                    self.empty_since = None
                    # let it run empty (other meter is cared for normally)
                    other = [k for k in ("hunger", "happy") if k not in self.neglect_what and st[k] < 3]
                    if other:
                        return self.feed() if other[0] == "hunger" else self.play()
                    return None
                if empty:
                    if getattr(self, "empty_since", None) is None:
                        self.empty_since = now
                    if now - self.empty_since < self.neglect:
                        return None
                    self.empty_since = None
                    self.log("NEGLECT done " + ",".join(empty))
                    return self.feed() if "hunger" in empty else self.play()
        return CareBot.plan(self)

def new_lab(**kw):
    t = Tama(ROM, LABLIB)
    logs = []
    b = LabBot(t, lambda m: logs.append((t.seconds, m)), model=MODEL)
    b.realtime = False
    b.logs = logs
    for k, v in kw.items(): setattr(b, k, v)
    return t, b
