"""ctypes binding for libtama.so (TamaLIB + src/tama_core.c)."""
import ctypes
import os

HERE = os.path.dirname(os.path.abspath(__file__))

TICK_HZ = 32768
LCD_W, LCD_H, ICONS = 32, 16, 8
BTN_A, BTN_B, BTN_C, BTN_TAP = 0, 1, 2, 3    # the tap sensor exists on the Angel only


class SoundEvent(ctypes.Structure):
    _fields_ = [("tick", ctypes.c_uint64), ("freq", ctypes.c_uint32)]


class Tama:
    """One emulated Tamagotchi. Not thread-safe: guard it with a lock."""

    def __init__(self, rom_path, lib_path=os.path.join(HERE, "libtama.so")):
        self.lib = lib = ctypes.CDLL(lib_path)
        lib.tama_init.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.tama_run.argtypes = [ctypes.c_uint32]
        lib.tama_run.restype = None
        lib.tama_ticks.restype = ctypes.c_uint64
        lib.tama_button.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.tama_button.restype = None
        lib.tama_get_frame.argtypes = [ctypes.c_char_p]
        lib.tama_get_frame.restype = None
        lib.tama_get_memory.argtypes = [ctypes.c_uint32]
        lib.tama_get_memory.restype = ctypes.c_uint8
        lib.tama_drain_sound.argtypes = [ctypes.POINTER(SoundEvent), ctypes.c_uint32]
        lib.tama_drain_sound.restype = ctypes.c_uint32
        lib.tama_save.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.tama_save.restype = ctypes.c_uint32
        lib.tama_load.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.tama_reset.restype = None
        lib.tama_link_edges.argtypes = [ctypes.POINTER(ctypes.c_uint32),
                                        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
        lib.tama_link_edges.restype = ctypes.c_uint32
        lib.tama_link_wave.argtypes = [ctypes.POINTER(ctypes.c_uint32),
                                       ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
        lib.tama_link_wave.restype = None

        with open(rom_path, "rb") as f:
            rom = f.read()
        if lib.tama_init(rom, len(rom)) != 0:
            raise RuntimeError("could not load ROM %s" % rom_path)

        self._frame = ctypes.create_string_buffer(LCD_W * LCD_H + ICONS)
        self._sound = (SoundEvent * 256)()
        self._state = ctypes.create_string_buffer(4096)
        self._edge_ticks = (ctypes.c_uint32 * 512)()
        self._edge_values = (ctypes.c_uint8 * 512)()
        # [(segment, common)] of the eight icons on a model that wires them unlike the P1
        self.icon_pins = None
        # (column of every segment, row of every common) of an LCD wired unlike the P1's
        self.lcd = None

    def run(self, ticks):
        self.lib.tama_run(ticks)

    @property
    def ticks(self):
        return self.lib.tama_ticks()

    @property
    def seconds(self):
        return self.lib.tama_ticks() / TICK_HZ

    def button(self, btn, pressed):
        self.lib.tama_button(btn, 1 if pressed else 0)

    def frame(self):
        """Returns (pixels, icons): 512 bytes row by row, and 8 icon bytes."""
        if self.lcd:
            cols, rows = self.lcd
            pixels = bytearray(LCD_W * LCD_H)
            for seg, col in enumerate(cols):
                if col is None:
                    continue
                for half, base in ((0, 0xE00), (8, 0xE80)):
                    for k in (0, 1):
                        nibble = self.memory(base + 2 * seg + k)
                        for bit in range(4):
                            if nibble >> bit & 1:
                                pixels[rows[half + 4 * k + bit] * LCD_W + col] = 1
            return bytes(pixels), bytes(self.lit(seg, com) for seg, com in self.icon_pins)
        self.lib.tama_get_frame(self._frame)
        raw = self._frame.raw
        if self.icon_pins:
            return raw[:LCD_W * LCD_H], bytes(self.lit(seg, com) for seg, com in self.icon_pins)
        return raw[:LCD_W * LCD_H], raw[LCD_W * LCD_H:]

    def lit(self, seg, com):
        """One LCD segment, read from the display memory (0xE00: commons 0-7, 0xE80: 8-15)."""
        nibble = (0xE00 if com < 8 else 0xE80) + 2 * seg + (com % 8) // 4
        return self.memory(nibble) >> (com % 4) & 1

    def memory(self, addr):
        return self.lib.tama_get_memory(addr)

    def drain_sound(self):
        n = self.lib.tama_drain_sound(self._sound, len(self._sound))
        return [(self._sound[i].tick, self._sound[i].freq) for i in range(n)]

    def save(self):
        n = self.lib.tama_save(self._state, len(self._state))
        if n == 0:
            raise RuntimeError("state buffer too small")
        return self._state.raw[:n]

    def load(self, data):
        return self.lib.tama_load(data, len(data)) == 0

    def reset(self):
        self.lib.tama_reset()

    def link_edges(self):
        """The changes of what the link port (P2) puts out since the last call:
        [(tick, state of its four pins)]."""
        n = self.lib.tama_link_edges(self._edge_ticks, self._edge_values, 512)
        return [(self._edge_ticks[i], self._edge_values[i]) for i in range(n)]

    def link_wave(self, wave):
        """Play [(ticks, state of the four pins)] to the link port, beginning now; after
        the last the pins are released."""
        n = len(wave)
        ticks = (ctypes.c_uint32 * n)(*[w[0] for w in wave])
        states = (ctypes.c_uint8 * n)(*[w[1] for w in wave])
        self.lib.tama_link_wave(ticks, states, n)


def ascii_frame(pixels, icons=None):
    rows = []
    for y in range(LCD_H):
        rows.append("".join("#" if pixels[y * LCD_W + x] else "." for x in range(LCD_W)))
    if icons is not None:
        rows.append("icons: " + "".join(str(int(bool(i))) for i in icons))
    return "\n".join(rows)
