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

        with open(rom_path, "rb") as f:
            rom = f.read()
        if lib.tama_init(rom, len(rom)) != 0:
            raise RuntimeError("could not load ROM %s" % rom_path)

        self._frame = ctypes.create_string_buffer(LCD_W * LCD_H + ICONS)
        self._sound = (SoundEvent * 256)()
        self._state = ctypes.create_string_buffer(4096)

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
        self.lib.tama_get_frame(self._frame)
        raw = self._frame.raw
        return raw[:LCD_W * LCD_H], raw[LCD_W * LCD_H:]

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


def ascii_frame(pixels, icons=None):
    rows = []
    for y in range(LCD_H):
        rows.append("".join("#" if pixels[y * LCD_W + x] else "." for x in range(LCD_W)))
    if icons is not None:
        rows.append("icons: " + "".join(str(int(bool(i))) for i in icons))
    return "\n".join(rows)
