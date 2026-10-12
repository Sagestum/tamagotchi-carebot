"""A Game Boy on Peanut-GB (src/gb_core.c, in libtama.so), for the Tamagotchi game of 1997.

It is handled like tama.Tama as far as that goes: run(ticks), button(), save() and load().
Its picture is another matter: 160 x 144 dots in four shades (shades()).
"""
import ctypes
import os

from tama import TICK_HZ

HERE = os.path.dirname(os.path.abspath(__file__))

WIDTH, HEIGHT = 160, 144
CART_RAM = 0x10000      # where memory() shows the battery-backed memory of the cartridge
# Numbered after engine.BUTTONS (A, B, then the Pocket Pikachu's pad and small keys); the
# value is the bit of the Game Boy's joypad
KEYS = {0: 0, 1: 1, 13: 2, 12: 3, 11: 4, 10: 5, 8: 6, 9: 7}
BTN_A, BTN_B, BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_START, BTN_SELECT = 0, 1, 8, 9, 10, 11, 12, 13


class GameBoy:
    """One emulated Game Boy with its cartridge. Not thread-safe: guard it with a lock."""

    icon_pins = None
    lcd = None

    def __init__(self, rom_path, lib_path=os.path.join(HERE, "libtama.so")):
        self.lib = lib = ctypes.CDLL(lib_path)
        lib.gameboy_init.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.gameboy_run.argtypes = [ctypes.c_uint32]
        lib.gameboy_run.restype = None
        lib.gameboy_ticks.restype = ctypes.c_uint64
        lib.gameboy_frames.restype = ctypes.c_uint64
        lib.gameboy_button.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.gameboy_button.restype = None
        lib.gameboy_get_frame.argtypes = [ctypes.c_char_p]
        lib.gameboy_get_packed.argtypes = [ctypes.c_char_p]
        lib.gameboy_get_memory.argtypes = [ctypes.c_uint32]
        lib.gameboy_get_memory.restype = ctypes.c_uint8
        lib.gameboy_set_memory.argtypes = [ctypes.c_uint32, ctypes.c_uint8]
        lib.gameboy_set_memory.restype = None
        lib.gameboy_save.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.gameboy_save.restype = ctypes.c_uint32
        lib.gameboy_load.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.gameboy_state_size.restype = ctypes.c_uint32
        lib.gameboy_reset.restype = None
        lib.gameboy_erase.restype = None

        with open(rom_path, "rb") as f:
            rom = f.read()
        if lib.gameboy_init(rom, len(rom)) != 0:
            raise RuntimeError("could not load ROM %s" % rom_path)
        self._frame = ctypes.create_string_buffer(WIDTH * HEIGHT)
        self._packed = ctypes.create_string_buffer(WIDTH * HEIGHT // 4)
        self._state = ctypes.create_string_buffer(lib.gameboy_state_size())

    def run(self, ticks):
        self.lib.gameboy_run(ticks)

    @property
    def ticks(self):
        return self.lib.gameboy_ticks()

    @property
    def seconds(self):
        return self.lib.gameboy_ticks() / TICK_HZ

    def button(self, btn, pressed):
        if btn in KEYS:
            self.lib.gameboy_button(KEYS[btn], 1 if pressed else 0)

    def frame(self):
        """What a Tamagotchi has: none of it. (The picture is shades().)"""
        return b"", bytes(8)

    def shades(self):
        """The picture, WIDTH x HEIGHT bytes from 0 (lightest) to 3, row by row; None while
        the display is switched off."""
        on = self.lib.gameboy_get_frame(self._frame)
        return self._frame.raw if on else None

    def packed(self):
        """The same, four dots to a byte (the first in the high bits); b"" while it is off."""
        on = self.lib.gameboy_get_packed(self._packed)
        return self._packed.raw if on else b""

    def memory(self, addr):
        return self.lib.gameboy_get_memory(addr)

    def poke(self, addr, value):
        self.lib.gameboy_set_memory(addr, value)

    def drain_sound(self):
        return []

    def save(self):
        n = self.lib.gameboy_save(self._state, len(self._state))
        if n == 0:
            raise RuntimeError("state buffer too small")
        return self._state.raw[:n]

    def load(self, data):
        return self.lib.gameboy_load(data, len(data)) == 0

    def reset(self):
        """Switched off and on: the cartridge keeps its memory."""
        self.lib.gameboy_reset()

    def erase(self):
        """Switched off and on with an empty cartridge memory."""
        self.lib.gameboy_erase()

    def link_edges(self):
        return []

    def link_wave(self, wave):
        pass
