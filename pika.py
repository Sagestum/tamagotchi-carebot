"""ctypes binding for the Pocket Pikachu's core (src/pika_core.c, part of libtama.so).

It answers to the same calls as tama.Tama, so that the engine can run either. What differs
is the display: 36 x 30 dots, five digits and three icons, handed out as the LCD memory
itself (lcd), and the inputs: eight keys and the pendulum that counts the steps.
"""
import ctypes
import os

from tama import SoundEvent, TICK_HZ

HERE = os.path.dirname(os.path.abspath(__file__))

LCD_BYTES = 0xB0
LCD_AT = 0x10000        # where memory() shows the LCD memory
# The keys are on port P2, one bit each; the pendulum pulls P4.0 low with every step.
# Numbered after engine.BUTTONS: A, B, (C), the pendulum, then the keys only this one has.
KEYS = {0: (2, 0x01), 1: (2, 0x02), 3: (4, 0x01),
        8: (2, 0x40), 9: (2, 0x10), 10: (2, 0x80), 11: (2, 0x20),     # up, down, left, right
        12: (2, 0x04), 13: (2, 0x08)}                                  # start, select
BTN_A, BTN_B, BTN_STEP = 0, 1, 3
BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_START, BTN_SELECT = 8, 9, 10, 11, 12, 13


class Pika:
    """One emulated Pocket Pikachu. Not thread-safe: guard it with a lock."""

    icon_pins = None
    lcd = None

    def __init__(self, rom_path, lib_path=os.path.join(HERE, "libtama.so")):
        self.lib = lib = ctypes.CDLL(lib_path)
        lib.pika_init.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.pika_run.argtypes = [ctypes.c_uint32]
        lib.pika_run.restype = None
        lib.pika_ticks.restype = ctypes.c_uint64
        lib.pika_port.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.pika_port.restype = None
        lib.pika_get_frame.argtypes = [ctypes.c_char_p]
        lib.pika_get_memory.argtypes = [ctypes.c_uint32]
        lib.pika_get_memory.restype = ctypes.c_uint8
        lib.pika_set_memory.argtypes = [ctypes.c_uint32, ctypes.c_uint8]
        lib.pika_set_memory.restype = None
        lib.pika_drain_sound.argtypes = [ctypes.POINTER(SoundEvent), ctypes.c_uint32]
        lib.pika_drain_sound.restype = ctypes.c_uint32
        lib.pika_save.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.pika_save.restype = ctypes.c_uint32
        lib.pika_load.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.pika_reset.restype = None

        with open(rom_path, "rb") as f:
            rom = f.read()
        if lib.pika_init(rom, len(rom)) != 0:
            raise RuntimeError("could not load ROM %s" % rom_path)
        self._lcd = ctypes.create_string_buffer(LCD_BYTES)
        self._sound = (SoundEvent * 256)()
        self._state = ctypes.create_string_buffer(4096)

    def run(self, ticks):
        self.lib.pika_run(ticks)

    @property
    def ticks(self):
        return self.lib.pika_ticks()

    @property
    def seconds(self):
        return self.lib.pika_ticks() / TICK_HZ

    def button(self, btn, pressed):
        if btn in KEYS:
            port, mask = KEYS[btn]
            self.lib.pika_port(port, mask, 0 if pressed else -1)

    def frame(self):
        """What a Tamagotchi has: none of it. (The display is lcd_memory().)"""
        return b"", bytes(8)

    def lcd_memory(self):
        """The LCD memory, or None while the display is switched off."""
        on = self.lib.pika_get_frame(self._lcd)
        return self._lcd.raw if on else None

    def lit(self, byte, bit):
        return self.lib.pika_get_memory(LCD_AT + byte) >> bit & 1

    def memory(self, addr):
        return self.lib.pika_get_memory(addr)

    def poke(self, addr, value):
        self.lib.pika_set_memory(addr, value)

    def drain_sound(self):
        n = self.lib.pika_drain_sound(self._sound, len(self._sound))
        return [(self._sound[i].tick, self._sound[i].freq) for i in range(n)]

    def save(self):
        n = self.lib.pika_save(self._state, len(self._state))
        if n == 0:
            raise RuntimeError("state buffer too small")
        return self._state.raw[:n]

    def load(self, data):
        return self.lib.pika_load(data, len(data)) == 0

    def reset(self):
        self.lib.pika_reset()

    def link_edges(self):
        return []

    def link_wave(self, wave):
        pass
