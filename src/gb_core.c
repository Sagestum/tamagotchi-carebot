/*
 * A Game Boy, for the Tamagotchi game of 1997: Peanut-GB (src/peanut/peanut_gb.h,
 * MIT, by Mahyar Koshkouei) with what the rest of the program expects of a
 * core. It is driven from Python like tama_core.c: the caller asks for a
 * number of 32768 Hz ticks, and whole pictures are run for them.
 */
#include <stdint.h>
#include <string.h>

#define ENABLE_SOUND 0
#define ENABLE_LCD 1
#include "peanut/peanut_gb.h"

#define GB_HZ			4194304
#define SUB_HZ			32768
/* Time is counted in units of which a tick of the caller has GB_HZ and a cycle
 * of the Game Boy SUB_HZ, so that both are whole numbers. */
#define TICK_UNITS		((int64_t) GB_HZ)
#define FRAME_UNITS		((int64_t) LCD_FRAME_CYCLES * SUB_HZ)

#define ROM_MAX			(2 * 1024 * 1024)
#define CART_RAM_MAX		(32 * 1024)
#define STATE_MAGIC		0x59424d47 /* "GMBY" */
#define STATE_VERSION		1

static uint8_t rom[ROM_MAX];
static uint32_t rom_size = 0;
static uint8_t frame[LCD_WIDTH * LCD_HEIGHT];	/* a shade from 0 (white) to 3 a dot */
static int lcd_on = 0;

/* Everything below this line is the state that is saved. */
static struct {
	struct gb_s gb;
	uint8_t cart_ram[CART_RAM_MAX];
	int64_t owed;			/* units run beyond the last gb_run_ticks() */
	uint64_t units;			/* all the units run */
	uint64_t frames;
} s;

static uint8_t rom_read(struct gb_s *gb, const uint_fast32_t addr)
{
	(void) gb;
	return addr < rom_size ? rom[addr] : 0xFF;
}

static uint8_t cart_ram_read(struct gb_s *gb, const uint_fast32_t addr)
{
	(void) gb;
	return addr < CART_RAM_MAX ? s.cart_ram[addr] : 0xFF;
}

static void cart_ram_write(struct gb_s *gb, const uint_fast32_t addr, const uint8_t val)
{
	(void) gb;
	if (addr < CART_RAM_MAX) {
		s.cart_ram[addr] = val;
	}
}

static void on_error(struct gb_s *gb, const enum gb_error_e err, const uint16_t addr)
{
	(void) gb;
	(void) err;
	(void) addr;
}

static void draw_line(struct gb_s *gb, const uint8_t *pixels, const uint_fast8_t line)
{
	int x;

	(void) gb;
	if (line >= LCD_HEIGHT) {
		return;
	}
	for (x = 0; x < LCD_WIDTH; x++) {
		frame[line * LCD_WIDTH + x] = pixels[x] & 0x03;
	}
}

/* What a saved state cannot hold: where the functions are in this process. */
static void wire(void)
{
	s.gb.gb_rom_read = rom_read;
	s.gb.gb_cart_ram_read = cart_ram_read;
	s.gb.gb_cart_ram_write = cart_ram_write;
	s.gb.gb_error = on_error;
	s.gb.gb_serial_tx = NULL;
	s.gb.gb_serial_rx = NULL;
	s.gb.gb_bootrom_read = NULL;
	s.gb.display.lcd_draw_line = draw_line;
	s.gb.direct.priv = NULL;
}

int gameboy_init(const uint8_t *rom_bytes, uint32_t len)
{
	if (len < 0x150 || len > ROM_MAX) {
		return -1;
	}
	memcpy(rom, rom_bytes, len);
	rom_size = len;
	memset(&s, 0, sizeof(s));
	memset(frame, 0, sizeof(frame));
	if (gb_init(&s.gb, rom_read, cart_ram_read, cart_ram_write, on_error, NULL) != GB_INIT_NO_ERROR) {
		return -1;
	}
	gb_init_lcd(&s.gb, draw_line);
	s.gb.direct.joypad = 0xFF;	/* nothing pressed */
	return 0;
}

/* Switched off and on again: the battery keeps what is in the cartridge. */
void gameboy_reset(void)
{
	uint8_t joypad = s.gb.direct.joypad;

	gb_reset(&s.gb);
	s.gb.direct.joypad = joypad;
}

/* The same, with an empty cartridge memory. */
void gameboy_erase(void)
{
	memset(s.cart_ram, 0, sizeof(s.cart_ram));
	gameboy_reset();
}

void gameboy_run(uint32_t ticks)
{
	int64_t want = (int64_t) ticks * TICK_UNITS - s.owed;

	while (want > 0) {
		gb_run_frame(&s.gb);
		lcd_on = (s.gb.hram_io[IO_LCDC] & 0x80) ? 1 : 0;
		if (!lcd_on) {
			memset(frame, 0, sizeof(frame));
		}
		want -= FRAME_UNITS;
		s.units += FRAME_UNITS;
		s.frames++;
	}
	s.owed = -want;
}

uint64_t gameboy_ticks(void)
{
	return s.units / TICK_UNITS;
}

uint64_t gameboy_frames(void)
{
	return s.frames;
}

/* bit: 0 A, 1 B, 2 select, 3 start, 4 right, 5 left, 6 up, 7 down */
void gameboy_button(int bit, int pressed)
{
	if (bit < 0 || bit > 7) {
		return;
	}
	if (pressed) {
		s.gb.direct.joypad &= (uint8_t) ~(1 << bit);
	} else {
		s.gb.direct.joypad |= (uint8_t) (1 << bit);
	}
}

/* The picture, LCD_WIDTH x LCD_HEIGHT shades; returns whether the display is on. */
int gameboy_get_frame(uint8_t *out)
{
	memcpy(out, frame, sizeof(frame));
	return lcd_on;
}

/* The same, four dots to a byte (the first in the high bits). */
int gameboy_get_packed(uint8_t *out)
{
	int i;

	for (i = 0; i < LCD_WIDTH * LCD_HEIGHT / 4; i++) {
		out[i] = (uint8_t) (frame[4 * i] << 6 | frame[4 * i + 1] << 4 | frame[4 * i + 2] << 2 | frame[4 * i + 3]);
	}
	return lcd_on;
}

/* 0x0000-0xFFFF as the program sees it, 0x10000 and on the cartridge memory. */
uint8_t gameboy_get_memory(uint32_t addr)
{
	if (addr >= 0x10000) {
		return addr - 0x10000 < CART_RAM_MAX ? s.cart_ram[addr - 0x10000] : 0;
	}
	return __gb_read(&s.gb, (uint16_t) addr);
}

void gameboy_set_memory(uint32_t addr, uint8_t value)
{
	if (addr >= 0x10000) {
		if (addr - 0x10000 < CART_RAM_MAX) {
			s.cart_ram[addr - 0x10000] = value;
		}
	} else if (addr >= 0xC000 && addr < 0xE000) {
		s.gb.wram[addr - 0xC000] = value;
	}
}

uint32_t gameboy_state_size(void)
{
	return (uint32_t) (3 * sizeof(uint32_t) + sizeof(s));
}

uint32_t gameboy_save(uint8_t *buf, uint32_t cap)
{
	uint32_t head[3] = { STATE_MAGIC, STATE_VERSION, (uint32_t) sizeof(s) };

	if (cap < sizeof(head) + sizeof(s)) {
		return 0;
	}
	memcpy(buf, head, sizeof(head));
	memcpy(buf + sizeof(head), &s, sizeof(s));
	return (uint32_t) (sizeof(head) + sizeof(s));
}

int gameboy_load(const uint8_t *buf, uint32_t len)
{
	uint32_t head[3];

	if (len != sizeof(head) + sizeof(s)) {
		return -1;
	}
	memcpy(head, buf, sizeof(head));
	if (head[0] != STATE_MAGIC || head[1] != STATE_VERSION || head[2] != sizeof(s)) {
		return -1;
	}
	memcpy(&s, buf + sizeof(head), sizeof(s));
	wire();
	return 0;
}
