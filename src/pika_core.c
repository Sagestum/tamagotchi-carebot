/*
 * Pocket Pikachu: a Mitsubishi M37520 (740 family, a 6502 relative) with its
 * timers, ports and LCD memory. Written after the core of BrickEmuPy
 * (cores/M37520.py, CC0), instruction for instruction, and driven from Python
 * like tama_core.c: the caller asks for a number of 32768 Hz ticks.
 */
#include <stdint.h>
#include <string.h>

#define MAIN_HZ			4000000
#define SUB_HZ			32768
/* Time is counted in units of which a cycle of the main clock has SUB_HZ and
 * a tick of the watch crystal MAIN_HZ, so that both are whole numbers. */
#define MAIN_CYCLE		((int64_t) SUB_HZ)
#define SUB_TICK		((int64_t) MAIN_HZ)

#define ROM_MAX			0x10000
#define RAM_SIZE		0x200
#define RAM_OFFSET		0x40
#define LCD_SIZE		0xB0
#define SOUND_EVENTS		256
#define STATE_MAGIC		0x414b4950 /* "PIKA" */
#define STATE_VERSION		1

#define IREQ1_INT0		0x01
#define IREQ1_INT1		0x02
#define IREQ1_TX		0x10
#define IREQ1_TY		0x20
#define IREQ1_T2		0x40
#define IREQ1_T3		0x80
#define IREQ2_T1		0x10
#define IREQ2_KEYON		0x20

typedef struct {
	uint64_t tick;
	uint32_t freq; /* in dHz, 0 = silence */
} sound_event_t;

static uint8_t rom[ROM_MAX];
static uint32_t rom_size = 0, rom_offset = 0;
static const uint8_t pull_ext[5] = { 0, 0, 0, 0x90, 0x2B }; /* resistors on the board */

/* Everything below this line is the state that is saved. */
static struct {
	int32_t PC, A, X, Y, SP, SPP;
	int32_t NF, VF, TF, BF, DF, IF, ZF, CF;
	int32_t nWAIT, nSTOP;
	uint8_t ram[RAM_SIZE], lcd[LCD_SIZE];
	int32_t lcd_offset;
	uint8_t pdir[5], pull[5], latch[5], in_low[5], in_high[5];
	int32_t TX, TXL, TY, TYL, T1, T1L, T2, T2L, T3, T3L;
	int32_t TXM, TYM, T123M, LC, LM, INTEDGE, CPUM, IREQ1, IREQ2, ICON1, ICON2;
	int64_t cx, cy, c1, c2, c3;	/* what is left until each timer counts */
	int64_t cpu_div, main_div;	/* length of a CPU cycle and of a timer count */
	int64_t owed;			/* units run beyond the last tama_run() */
	int64_t frac;			/* units of the current tick already gone */
	uint64_t ticks;
	uint64_t instructions;
	/* the buzzer: two pins of P3 driven against each other */
	int32_t level;
	uint64_t flank;			/* when the level last changed, in units */
	int64_t half;			/* the half wave in units, 0: silent */
	uint32_t freq;
} s;

static sound_event_t sound_events[SOUND_EVENTS];
static uint32_t sound_head = 0, sound_count = 0;

#define PC s.PC
#define A s.A
#define X s.X
#define Y s.Y
#define SP s.SP
#define NF s.NF
#define VF s.VF
#define TF s.TF
#define BF s.BF
#define DF s.DF
#define IF s.IF
#define ZF s.ZF
#define CF s.CF
#define nWAIT s.nWAIT
#define nSTOP s.nSTOP
#define NZ(v) do { NF = ((v) >> 7) & 1; ZF = !((v) & 0xFF); } while (0)

static uint64_t now(void)
{
	return s.ticks * (uint64_t) SUB_TICK + (uint64_t) s.frac;
}

static void push_sound(uint32_t freq)
{
	sound_event_t *e;

	if (freq == s.freq) {
		return;
	}
	s.freq = freq;
	e = &sound_events[(sound_head + sound_count) % SOUND_EVENTS];
	e->tick = s.ticks;
	e->freq = freq;
	if (sound_count < SOUND_EVENTS) {
		sound_count++;
	} else {
		sound_head = (sound_head + 1) % SOUND_EVENTS;
	}
}

static void buzzer(int value)
{
	int level = ((value >> 6) & 1) - ((value >> 5) & 1);
	uint64_t t = now();

	if (level == s.level) {
		return;
	}
	if (level != 0 && s.level != 0) {
		/* a full swing: half a wave has passed since the last one */
		int64_t half = (int64_t) (t - s.flank);
		/* The program makes the tone itself, so no two half waves are quite
		 * alike: a new pitch counts when two in a row agree and it is more
		 * than a semitone away from the one that sounds. */
		if (half > 0) {
			int64_t was = s.half, d = half > was ? half - was : was - half;
			uint32_t freq = (uint32_t) (10 * (int64_t) SUB_TICK * SUB_HZ / (2 * half));
			int64_t off = (int64_t) freq - (int64_t) s.freq;

			s.half = half;
			if (off < 0) off = -off;
			if (d * 16 < half && off * 16 > (int64_t) s.freq) {
				push_sound(freq);
			}
		}
	}
	if (level != 0) {
		s.flank = t;
	}
	s.level = level;
}

static void buzzer_idle(void)
{
	/* no swing for two half waves (at least 5 ms): it has stopped */
	int64_t limit = 2 * s.half;

	if (limit < SUB_TICK * 164) {
		limit = SUB_TICK * 164;
	}
	if (s.freq && (int64_t) (now() - s.flank) > limit) {
		s.half = 0;
		push_sound(0);
	}
}

static int port_read(int p)
{
	return ((s.pdir[p] & s.latch[p]) |
		(~s.pdir[p] & (~s.in_low[p] & (s.in_high[p] | s.pull[p] | pull_ext[p])))) & 0xFF;
}

static void set_cpum(int value)
{
	s.CPUM = value;
	if (value & 0x80) {
		/* the watch crystal drives the CPU */
		s.cpu_div = 2 * SUB_TICK;
		s.main_div = SUB_TICK;
	} else {
		s.cpu_div = 2 * MAIN_CYCLE;
		s.main_div = MAIN_CYCLE;
		if (value & 0x40) {
			s.cpu_div *= 4;
		}
	}
	s.SPP = (value & 0x04) ? 0x100 : 0;
}

static void set_lm(int value)
{
	s.LM = value;
	s.lcd_offset = (value & 0x04) ? 0x40 : 0x340;
}

static int io_read(int addr)
{
	switch (addr) {
	case 0x00: return port_read(0);
	case 0x01: return s.pdir[0];
	case 0x02: return port_read(1);
	case 0x03: return s.pdir[1];
	case 0x04: return port_read(2);
	case 0x05: return s.pdir[2];
	case 0x06: return port_read(3);
	case 0x07: return s.pdir[3];
	case 0x08: return port_read(4);
	case 0x09: return s.pdir[4];
	case 0x0B: return s.pull[0];
	case 0x0C: return s.pull[1];
	case 0x0D: return s.pull[2];
	case 0x0E: return s.pull[3];
	case 0x0F: return s.pull[4];
	case 0x20: return s.TX & 0xFF;
	case 0x21: return s.TX >> 8;
	case 0x22: return s.TY & 0xFF;
	case 0x23: return s.TY >> 8;
	case 0x24: return s.T1;
	case 0x25: return s.T2;
	case 0x26: return s.T3;
	case 0x27: return s.TXM;
	case 0x28: return s.TYM;
	case 0x29: return s.T123M;
	case 0x37: return s.LC;
	case 0x39: return s.LM;
	case 0x3A: return s.INTEDGE;
	case 0x3B: return s.CPUM;
	case 0x3C: return s.IREQ1;
	case 0x3D: return s.IREQ2;
	case 0x3E: return s.ICON1;
	case 0x3F: return s.ICON2;
	}
	return 0;
}

static void io_write(int addr, int v)
{
	switch (addr) {
	case 0x00: s.latch[0] = v; break;
	case 0x01: s.pdir[0] = v; break;
	case 0x02: s.latch[1] = v; break;
	case 0x03: s.pdir[1] = v; break;
	case 0x04: s.latch[2] = v; break;
	case 0x05: s.pdir[2] = v; break;
	case 0x06: buzzer(v); s.latch[3] = v; break;
	case 0x07: s.pdir[3] = v; break;
	case 0x08: s.latch[4] = v & 0xFE; break;
	case 0x09: s.pdir[4] = v & 0xFE; break;
	case 0x0B: s.pull[0] = v; break;
	case 0x0C: s.pull[1] = v; break;
	case 0x0D: s.pull[2] = v; break;
	case 0x0E: s.pull[3] = v; break;
	case 0x0F: s.pull[4] = v; break;
	case 0x20:
		s.TXL = (s.TX & 0xFF00) | v;
		if (!(s.TXM & 0x01)) s.TX = s.TXL;
		break;
	case 0x21:
		s.TXL = (s.TX & 0xFF) | (v << 8);
		if (!(s.TXM & 0x01)) s.TX = s.TXL;
		break;
	case 0x22: s.TY = (s.TY & 0xFF00) | v; s.TYL = s.TY; break;
	case 0x23: s.TY = (s.TY & 0xFF) | (v << 8); s.TYL = s.TY; break;
	case 0x24: s.T1 = s.T1L = v; break;
	case 0x25:
		if (!(s.T123M & 0x04)) s.T2 = v;
		s.T2L = v;
		break;
	case 0x26: s.T3 = s.T3L = v; break;
	case 0x27: s.TXM = v; break;
	case 0x28: s.TYM = v; break;
	case 0x29: s.T123M = v; break;
	case 0x37: s.LC = v; break;
	case 0x39: set_lm(v); break;
	case 0x3A: s.INTEDGE = v; break;
	case 0x3B: set_cpum(v); break;
	case 0x3C: s.IREQ1 &= v; break;
	case 0x3D: s.IREQ2 &= v; break;
	case 0x3E: s.ICON1 = v; break;
	case 0x3F: s.ICON2 = v; break;
	}
}

static int rd(int addr)
{
	if (addr >= s.lcd_offset && addr < s.lcd_offset + LCD_SIZE) {
		return s.lcd[addr - s.lcd_offset];
	}
	if (addr >= RAM_OFFSET && addr < RAM_OFFSET + RAM_SIZE) {
		return s.ram[addr - RAM_OFFSET];
	}
	if (addr < 0x40) {
		return io_read(addr);
	}
	if (addr >= (int) rom_offset) {
		return rom[(addr - rom_offset) % rom_size];
	}
	return 0;
}

static void wr(int addr, int value)
{
	value &= 0xFF;
	if (addr >= s.lcd_offset && addr < s.lcd_offset + LCD_SIZE) {
		s.lcd[addr - s.lcd_offset] = value;
	} else if (addr >= RAM_OFFSET && addr < RAM_OFFSET + RAM_SIZE) {
		s.ram[addr - RAM_OFFSET] = value;
	} else if (addr < 0x40) {
		io_write(addr, value);
	}
}

static int ps(void)
{
	return NF << 7 | VF << 6 | TF << 5 | BF << 4 | DF << 3 | IF << 2 | ZF << 1 | CF;
}

static void set_ps(int v)
{
	NF = v >> 7 & 1;
	VF = v >> 6 & 1;
	TF = v >> 5 & 1;
	BF = v >> 4 & 1;
	DF = v >> 3 & 1;
	IF = v >> 2 & 1;
	ZF = v >> 1 & 1;
	CF = v & 1;
}

static void push(int v)
{
	wr(s.SPP | SP, v);
	SP = (SP - 1) & 0xFF;
}

static int pull(void)
{
	SP = (SP + 1) & 0xFF;
	return rd(s.SPP | SP);
}

static void go_vector(int addr)
{
	uint32_t at = (0x10000 - addr) - rom_offset;

	PC = rom[at % rom_size] | rom[(at + 1) % rom_size] << 8;
}

static void interrupt(int addr)
{
	nWAIT = 1;
	push(PC >> 8);
	push(PC & 0xFF);
	push(ps());
	IF = 1;
	go_vector(addr);
}

static void interrupt_process(void)
{
	int i;

	for (i = 0; i < 8; i++) {
		if (s.IREQ1 & s.ICON1 & (1 << i)) {
			s.IREQ1 &= ~(1 << i);
			interrupt(6 + (i << 1));
			return;
		}
	}
	for (i = 0; i < 6; i++) {
		if (s.IREQ2 & s.ICON2 & (1 << i)) {
			s.IREQ2 &= ~(1 << i);
			interrupt(22 + (i << 1));
			return;
		}
	}
}

/* With the T flag set the accumulator's part is played by the memory at X. */
static int acc(void) { return TF ? rd(X) : A; }

static int adc(int m)
{
	int a = acc(), v = a + m + CF;

	if (DF && (a & 0x0F) + (m & 0x0F) + CF > 9) v += 6;
	VF = ((~(a ^ m) & (a ^ v)) >> 7) & 1;
	NF = (v >> 7) & 1;
	if (DF && v > 0x99) v += 0x60;
	ZF = !(v & 0xFF);
	CF = v > 255;
	if (TF) { wr(X, v); return 3; }
	A = v & 0xFF;
	return 0;
}

static int sbc(int m)
{
	int a = acc(), v = a - m - !CF;

	if (DF) {
		if ((a & 0x0F) - (m & 0x0F) - !CF < 0) v -= 6;
		if (v < 0) v -= 0x60;
	}
	VF = (((a ^ m) & (a ^ v)) >> 7) & 1;
	NF = (v >> 7) & 1;
	ZF = !(v & 0xFF);
	CF = v >= 0;
	if (TF) { wr(X, v); return 3; }
	A = v & 0xFF;
	return 0;
}

static int logic(int v)
{
	NZ(v);
	if (TF) { wr(X, v); return 3; }
	A = v;
	return 0;
}

static int ora(int m) { return logic(acc() | m); }
static int and_(int m) { return logic(acc() & m); }
static int eor(int m) { return logic(acc() ^ m); }

static int lda(int m)
{
	NZ(m);
	if (TF) { wr(X, m); return 2; }
	A = m;
	return 0;
}

static void compare(int r, int m)
{
	int v = r - m;

	NF = (v >> 7) & 1;
	ZF = !v;
	CF = v >= 0;
}

static int cmp(int m)
{
	compare(acc(), m);
	return TF;
}

static int asl(int v) { v <<= 1; CF = v >> 8 & 1; v &= 0xFF; NZ(v); return v; }
static int rol(int v) { v = v << 1 | CF; CF = v >> 8 & 1; v &= 0xFF; NZ(v); return v; }
static int lsr(int v) { CF = v & 1; v >>= 1; NF = 0; ZF = !v; return v; }
static int ror(int v) { int c = v & 1; v = v >> 1 | CF << 7; NF = CF; ZF = !v; CF = c; return v; }

static void timers(int64_t units)
{
	/* Timers 2 and 3 can count the underflows of timer 1, which come every
	 * latch + 1 counts. (BrickEmuPy takes the latch alone; the Pikachu's
	 * second, 32768 Hz / 32 / 256 / 4, would then be 1/256 short.) */
	int64_t sub32 = 32 * SUB_TICK, chain = s.T1L + 1, step;

	if (!(s.TXM & 0x80)) {
		s.cx -= units;
		while (s.cx <= 0) {
			s.cx += s.main_div;
			if (--s.TX < 0) { s.TX = s.TXL; s.IREQ1 |= IREQ1_TX; }
		}
	}
	if (!(s.TYM & 0x80)) {
		s.cy -= units;
		while (s.cy <= 0) {
			s.cy += s.main_div;
			if (--s.TY < 0) { s.TY = s.TYL; s.IREQ1 |= IREQ1_TY; }
		}
	}
	s.c1 -= units;
	while (s.c1 <= 0) {
		s.c1 += (s.T123M & 0x20) ? sub32 : s.main_div;
		if (--s.T1 < 0) { s.T1 = s.T1L; s.IREQ2 |= IREQ2_T1; }
	}
	s.c2 -= units;
	while (s.c2 <= 0) {
		if (s.T123M & 0x08) step = s.main_div;
		else if (s.T123M & 0x20) step = sub32 * chain;
		else step = s.main_div * chain;
		s.c2 += step > 0 ? step : s.main_div;
		if (--s.T2 < 0) { s.T2 = s.T2L; s.IREQ1 |= IREQ1_T2; }
	}
	s.c3 -= units;
	while (s.c3 <= 0) {
		if (s.T123M & 0x10) step = sub32;
		else if (s.T123M & 0x20) step = sub32 * chain;
		else step = s.main_div * chain;
		s.c3 += step > 0 ? step : s.main_div;
		if (--s.T3 < 0) { s.T3 = s.T3L; s.IREQ1 |= IREQ1_T3; }
	}
}

#define LEN(n) b1 = rom[(at + 1) % rom_size]; b2 = rom[(at + 2) % rom_size]; PC += (n)

/* One instruction (or one idle CPU cycle); returns the units it took. */
static int64_t step(void)
{
	int64_t units = s.cpu_div;

	if (nSTOP) {
		if (nWAIT) {
			uint32_t at = (uint32_t) (PC - (int32_t) rom_offset);
			int op = rom[at % rom_size], b1 = 0, b2 = 0, cyc = 2, t, u;

			(void) u;
			(void) b2;
			switch (op) {
#include "m37520_ops.h"
			}
			units *= cyc;
			s.instructions++;
		}
		timers(units);
	}
	if (!IF) {
		interrupt_process();
	}
	return units;
}

void pika_reset(void)
{
	int64_t owed = s.owed, frac = s.frac;
	uint64_t ticks = s.ticks;

	memset(&s, 0, sizeof(s));
	s.owed = owed;
	s.frac = frac;
	s.ticks = ticks;
	set_ps(0x04);
	nWAIT = nSTOP = 1;
	s.TX = s.TXL = 0xFFFF;
	s.TY = s.TYL = 0xFFFF;
	s.T1 = s.T1L = 0xFF;
	s.T2 = s.T2L = 0x01;
	s.T3 = s.T3L = 0xFF;
	set_lm(0x00);
	set_cpum(0x4C);
	go_vector(4);
}

int pika_init(const uint8_t *rom_bytes, uint32_t len)
{
	if (len == 0 || len > ROM_MAX) {
		return -1;
	}
	memcpy(rom, rom_bytes, len);
	rom_size = len;
	rom_offset = 0x10000 - len;
	memset(&s, 0, sizeof(s));
	sound_head = sound_count = 0;
	pika_reset();
	return 0;
}

void pika_run(uint32_t ticks)
{
	int64_t want = (int64_t) ticks * SUB_TICK - s.owed;

	while (want > 0) {
		int64_t units = step();

		want -= units;
		s.frac += units;
		if (s.frac >= SUB_TICK) {
			s.ticks += (uint64_t) (s.frac / SUB_TICK);
			s.frac %= SUB_TICK;
		}
	}
	s.owed = -want;
	buzzer_idle();
}

/* One step alone, for comparing with another core; returns its length in
 * 1/32768 of a main clock cycle. */
int64_t pika_step(void)
{
	int64_t units = step();

	s.frac += units;
	s.ticks += (uint64_t) (s.frac / SUB_TICK);
	s.frac %= SUB_TICK;
	return units;
}

uint64_t pika_ticks(void)
{
	return s.ticks;
}

uint64_t pika_instructions(void)
{
	return s.instructions;
}

/* A contact on a port pin: level 0 pulls it low, 1 high, -1 lets it go. */
void pika_port(int port, int mask, int level)
{
	int before, after, changed;

	if (port < 0 || port > 4) {
		return;
	}
	before = port_read(port);
	s.in_low[port] &= ~mask;
	s.in_high[port] &= ~mask;
	if (level == 0) s.in_low[port] |= mask;
	if (level == 1) s.in_high[port] |= mask;
	after = port_read(port);
	changed = before ^ after;
	if (!changed) {
		return;
	}
	if (port == 2 && (changed & before)) {
		s.IREQ2 |= IREQ2_KEYON;		/* a key pulled its pin low */
	}
	if (port == 4) {
		if ((changed & 1) && !(after & 1) == !(s.INTEDGE & 0x01)) s.IREQ1 |= IREQ1_INT0;
		if ((changed & 2) && !(after & 2) == !(s.INTEDGE & 0x02)) s.IREQ1 |= IREQ1_INT1;
	}
}

/* The LCD memory, 0xB0 bytes; returns whether the display is on. */
int pika_get_frame(uint8_t *out)
{
	memcpy(out, s.lcd, LCD_SIZE);
	return (s.LM & 0x08) ? 1 : 0;
}

uint8_t pika_get_memory(uint32_t addr)
{
	if (addr >= RAM_OFFSET && addr < RAM_OFFSET + RAM_SIZE) {
		return s.ram[addr - RAM_OFFSET];
	}
	if (addr < 0x40) {
		return (uint8_t) io_read((int) addr);
	}
	if (addr >= 0x10000 && addr < 0x10000 + LCD_SIZE) {
		return s.lcd[addr - 0x10000];
	}
	if (addr >= rom_offset && addr < 0x10000) {
		return rom[addr - rom_offset];
	}
	return 0;
}

void pika_set_memory(uint32_t addr, uint8_t value)
{
	if (addr >= RAM_OFFSET && addr < RAM_OFFSET + RAM_SIZE) {
		s.ram[addr - RAM_OFFSET] = value;
	}
}

/* For comparing with another core: PC, A, X, Y, SP, flags. */
void pika_registers(int32_t *out)
{
	out[0] = PC & 0xFFFF;
	out[1] = A;
	out[2] = X;
	out[3] = Y;
	out[4] = SP;
	out[5] = ps();
}

uint32_t pika_drain_sound(sound_event_t *out, uint32_t max)
{
	uint32_t n = 0;

	while (sound_count > 0 && n < max) {
		out[n++] = sound_events[sound_head];
		sound_head = (sound_head + 1) % SOUND_EVENTS;
		sound_count--;
	}
	return n;
}

uint32_t pika_save(uint8_t *buf, uint32_t cap)
{
	uint32_t head[3] = { STATE_MAGIC, STATE_VERSION, (uint32_t) sizeof(s) };

	if (cap < sizeof(head) + sizeof(s)) {
		return 0;
	}
	memcpy(buf, head, sizeof(head));
	memcpy(buf + sizeof(head), &s, sizeof(s));
	return (uint32_t) (sizeof(head) + sizeof(s));
}

int pika_load(const uint8_t *buf, uint32_t len)
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
	return 0;
}
