"""The link between two Digimon.

They are joined by one wire, their pins P20, which rests HIGH. Whoever sends pulls it LOW
for 64 ms and then sends a word of 16 bits, the most significant first, each as a HIGH and a
LOW: a short HIGH and a long LOW is a 0, a long HIGH and a short LOW a 1. The times below are
ticks of 1/32768 s, read off the pin of the emulated device with the core's log of its
changes; they agree with BrickEmuPy's CON_DGM.

A fight is four words: the one who presses the button sends a word about itself, the other
answers with its own, then the first sends the outcome and the other confirms it. The low
byte of every word is the high byte inverted.
"""
START = 2099            # LOW before a word
LEAD = (66, 31)         # a HIGH and a LOW that carry nothing
BIT = ((33, 107), (90, 55))     # (HIGH, LOW) of a 0 and of a 1
REST = 1000             # a HIGH this long: whatever comes next is a new word
ANSWER = 100            # ticks between a word and the answer to it (300 is still taken, 1000 not)
HIGH, LOW = 0xF, 0xE    # the four pins of the port with P20 high and low


class Reader:
    """Puts the words together that a device sends: feed it Tama.link_edges()."""

    def __init__(self):
        self.level, self.since = 1, 0
        self.high, self.periods, self.word = 0, 0, 0

    def feed(self, edges):
        words = []
        for tick, pins in edges:
            level = pins & 1
            if level == self.level:
                continue
            length = (tick - self.since) & 0xFFFFFFFF
            if level:                       # a LOW is over
                self.periods += 1
                if self.periods > 2:        # after the LOW of the start and the lead
                    self.word = (self.word << 1 | (self.high > length)) & 0xFFFF
                    if self.periods == 18:
                        words.append(self.word)
                        self.periods = 0
            else:                           # a HIGH is over
                if length > REST:
                    self.periods = 0
                self.high = length
            self.level, self.since = level, tick
        return words


def wave(word, wait=ANSWER):
    """What to play to a device (Tama.link_wave) so that it reads this word."""
    out = [(wait, HIGH), (START, LOW), (LEAD[0], HIGH), (LEAD[1], LOW)]
    for i in range(15, -1, -1):
        high, low = BIT[word >> i & 1]
        out += [(high, HIGH), (low, LOW)]
    return out


def framed(byte):
    """A word from its high byte: the low byte is the high one inverted."""
    return (byte & 0xFF) << 8 | (~byte & 0xFF)


class Sparring:
    """An opponent that is not there: it answers the word a Digimon sends about itself with
    a word of its own, and the outcome with the other outcome."""

    LOST, WON = 0x40, 0x80          # the high byte of the outcome a device sends (the one
                                    # that sends 0x40 goes on to show skulls)

    def __init__(self, tama, about=None, log=None):
        self.tama = tama
        self.about = about          # the word about the opponent; None: the same as ours
        self.reader = Reader()
        self.words = []             # what the device has sent in this fight
        self.log = log

    def step(self):
        """Call often (after every slice of emulation). Returns "won" or "lost" once the
        device has sent the outcome of a fight, else None."""
        for word in self.reader.feed(self.tama.link_edges()):
            self.words.append(word)
            byte = word >> 8
            if len(self.words) % 2:         # the word about itself
                self.tama.link_wave(wave(self.about if self.about is not None else word))
            else:                           # the outcome: answer with the other one
                other = self.LOST if byte == self.WON else self.WON
                self.tama.link_wave(wave(framed(other)))
                return "won" if byte == self.WON else "lost"
        return None
