/*
 * Thin wrapper around TamaLIB, built as a shared library and driven from
 * Python (ctypes). The emulator never sleeps here: the caller asks for a
 * number of 32768 Hz ticks and does the real-time pacing itself.
 */
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "tamalib/tamalib.h"

#define ROM_WORDS		8192
#define SOUND_EVENTS		256
#define STATE_MAGIC		0x414d4154 /* "TAMA" */
#define STATE_VERSION		1

typedef struct {
	uint64_t tick;
	uint32_t freq; /* in dHz, 0 = silence */
} sound_event_t;

static u12_t rom[ROM_WORDS];

static uint8_t matrix[LCD_HEIGHT][LCD_WIDTH];
static uint8_t icons[ICON_NUM];

static uint64_t total_ticks = 0;

static uint32_t buzzer_freq = 0;
static uint8_t buzzer_on = 0;
static sound_event_t sound_events[SOUND_EVENTS];
static uint32_t sound_head = 0, sound_count = 0;

static u32_t run_start = 0;
static uint8_t running = 0;

static void push_sound(void)
{
	sound_event_t *e;

	/* Events arrive in the middle of a tama_run() slice, before total_ticks
	 * is updated.
	 */
	e = &sound_events[(sound_head + sound_count) % SOUND_EVENTS];
	e->tick = total_ticks + (running ? (u32_t) (*cpu_get_state()->tick_counter - run_start) : 0);
	e->freq = buzzer_on ? buzzer_freq : 0;

	if (sound_count < SOUND_EVENTS) {
		sound_count++;
	} else {
		sound_head = (sound_head + 1) % SOUND_EVENTS;
	}
}

static void * hal_malloc(u32_t size) { (void) size; return NULL; }
static void hal_free(void *ptr) { (void) ptr; }
static void hal_halt(void) {}
static bool_t hal_is_log_enabled(log_level_t level) { return level == LOG_ERROR; }

static void hal_log(log_level_t level, char *buff, ...)
{
	va_list args;

	if (level != LOG_ERROR) {
		return;
	}

	va_start(args, buff);
	vfprintf(stderr, buff, args);
	va_end(args);
}

static void hal_sleep_until(timestamp_t ts) { (void) ts; }
static timestamp_t hal_get_timestamp(void) { return 0; }
static void hal_update_screen(void) {}

static void hal_set_lcd_matrix(u8_t x, u8_t y, bool_t val)
{
	if (x < LCD_WIDTH && y < LCD_HEIGHT) {
		matrix[y][x] = val;
	}
}

static void hal_set_lcd_icon(u8_t icon, bool_t val)
{
	if (icon < ICON_NUM) {
		icons[icon] = val;
	}
}

static void hal_set_frequency(u32_t freq)
{
	if (freq != buzzer_freq) {
		buzzer_freq = freq;
		if (buzzer_on) {
			push_sound();
		}
	}
}

static void hal_play_frequency(bool_t en)
{
	if (en != buzzer_on) {
		buzzer_on = en;
		push_sound();
	}
}

static int hal_handler(void) { return 0; }

static hal_t hal = {
	.malloc = &hal_malloc,
	.free = &hal_free,
	.halt = &hal_halt,
	.is_log_enabled = &hal_is_log_enabled,
	.log = &hal_log,
	.sleep_until = &hal_sleep_until,
	.get_timestamp = &hal_get_timestamp,
	.update_screen = &hal_update_screen,
	.set_lcd_matrix = &hal_set_lcd_matrix,
	.set_lcd_icon = &hal_set_lcd_icon,
	.set_frequency = &hal_set_frequency,
	.play_frequency = &hal_play_frequency,
	.handler = &hal_handler,
};

/* rom_bytes: MAME "tama.b" layout, one 12-bit word per big-endian byte pair */
int tama_init(const uint8_t *rom_bytes, uint32_t len)
{
	uint32_t i;

	if (len % 2 != 0 || len / 2 > ROM_WORDS) {
		return -1;
	}

	memset(rom, 0, sizeof(rom));
	for (i = 0; i < len / 2; i++) {
		rom[i] = ((rom_bytes[2 * i] & 0xF) << 8) | rom_bytes[2 * i + 1];
	}

	memset(matrix, 0, sizeof(matrix));
	memset(icons, 0, sizeof(icons));
	total_ticks = 0;

	tamalib_register_hal(&hal);
	if (tamalib_init(rom, NULL, 1000000)) {
		return -1;
	}
	tamalib_set_speed(0);

	return 0;
}

void tama_reset(void)
{
	memset(matrix, 0, sizeof(matrix));
	memset(icons, 0, sizeof(icons));
	tamalib_reset();
	tamalib_refresh_hw();
}

/* Runs the CPU for at least the given number of ticks (32768 per second) */
void tama_run(uint32_t ticks)
{
	u32_t *counter = cpu_get_state()->tick_counter;

	run_start = *counter;
	running = 1;

	while ((u32_t) (*counter - run_start) < ticks) {
		if (cpu_step()) {
			break;
		}
	}

	running = 0;
	total_ticks += (u32_t) (*counter - run_start);
}

uint64_t tama_ticks(void)
{
	return total_ticks;
}

/* btn: 0 = left (A), 1 = middle (B), 2 = right (C) */
void tama_button(int btn, int pressed)
{
	if (btn < 0 || btn > 2) {
		return;
	}

	tamalib_set_button((button_t) btn, pressed ? BTN_STATE_PRESSED : BTN_STATE_RELEASED);
}

/* out: LCD_HEIGHT * LCD_WIDTH pixels (row by row) followed by ICON_NUM icons */
void tama_get_frame(uint8_t *out)
{
	memcpy(out, matrix, sizeof(matrix));
	memcpy(out + sizeof(matrix), icons, sizeof(icons));
}

uint8_t tama_get_memory(uint32_t addr)
{
	if (addr >= MEMORY_SIZE) {
		return 0;
	}

	return GET_MEMORY(cpu_get_state()->memory, addr);
}

uint32_t tama_drain_sound(sound_event_t *out, uint32_t max)
{
	uint32_t n = 0;

	while (sound_count > 0 && n < max) {
		out[n++] = sound_events[sound_head];
		sound_head = (sound_head + 1) % SOUND_EVENTS;
		sound_count--;
	}

	return n;
}

#define PUT(v)	do { if (pos + sizeof(v) > cap) return 0; memcpy(buf + pos, &(v), sizeof(v)); pos += sizeof(v); } while (0)
#define GET(v)	do { if (pos + sizeof(v) > len) return -1; memcpy(&(v), buf + pos, sizeof(v)); pos += sizeof(v); } while (0)

uint32_t tama_save(uint8_t *buf, uint32_t cap)
{
	state_t *s = cpu_get_state();
	uint32_t pos = 0, magic = STATE_MAGIC, version = STATE_VERSION;
	int i;

	PUT(magic);
	PUT(version);
	PUT(total_ticks);
	PUT(*s->pc);
	PUT(*s->x);
	PUT(*s->y);
	PUT(*s->a);
	PUT(*s->b);
	PUT(*s->np);
	PUT(*s->sp);
	PUT(*s->flags);
	PUT(*s->tick_counter);
	PUT(*s->clk_timer_2hz_timestamp);
	PUT(*s->clk_timer_4hz_timestamp);
	PUT(*s->clk_timer_8hz_timestamp);
	PUT(*s->clk_timer_16hz_timestamp);
	PUT(*s->clk_timer_32hz_timestamp);
	PUT(*s->clk_timer_64hz_timestamp);
	PUT(*s->clk_timer_128hz_timestamp);
	PUT(*s->clk_timer_256hz_timestamp);
	PUT(*s->prog_timer_timestamp);
	PUT(*s->prog_timer_enabled);
	PUT(*s->prog_timer_data);
	PUT(*s->prog_timer_rld);
	PUT(*s->call_depth);
	for (i = 0; i < INT_SLOT_NUM; i++) {
		PUT(s->interrupts[i].factor_flag_reg);
		PUT(s->interrupts[i].mask_reg);
		PUT(s->interrupts[i].triggered);
	}
	PUT(*s->cpu_halted);

	if (pos + MEM_BUFFER_SIZE * sizeof(MEM_BUFFER_TYPE) > cap) {
		return 0;
	}
	memcpy(buf + pos, s->memory, MEM_BUFFER_SIZE * sizeof(MEM_BUFFER_TYPE));
	pos += MEM_BUFFER_SIZE * sizeof(MEM_BUFFER_TYPE);

	return pos;
}

int tama_load(const uint8_t *buf, uint32_t len)
{
	state_t *s = cpu_get_state();
	uint32_t pos = 0, magic, version;
	int i;

	GET(magic);
	GET(version);
	if (magic != STATE_MAGIC || version != STATE_VERSION) {
		return -1;
	}

	GET(total_ticks);
	GET(*s->pc);
	GET(*s->x);
	GET(*s->y);
	GET(*s->a);
	GET(*s->b);
	GET(*s->np);
	GET(*s->sp);
	GET(*s->flags);
	GET(*s->tick_counter);
	GET(*s->clk_timer_2hz_timestamp);
	GET(*s->clk_timer_4hz_timestamp);
	GET(*s->clk_timer_8hz_timestamp);
	GET(*s->clk_timer_16hz_timestamp);
	GET(*s->clk_timer_32hz_timestamp);
	GET(*s->clk_timer_64hz_timestamp);
	GET(*s->clk_timer_128hz_timestamp);
	GET(*s->clk_timer_256hz_timestamp);
	GET(*s->prog_timer_timestamp);
	GET(*s->prog_timer_enabled);
	GET(*s->prog_timer_data);
	GET(*s->prog_timer_rld);
	GET(*s->call_depth);
	for (i = 0; i < INT_SLOT_NUM; i++) {
		GET(s->interrupts[i].factor_flag_reg);
		GET(s->interrupts[i].mask_reg);
		GET(s->interrupts[i].triggered);
	}
	GET(*s->cpu_halted);

	if (pos + MEM_BUFFER_SIZE * sizeof(MEM_BUFFER_TYPE) > len) {
		return -1;
	}
	memcpy(s->memory, buf + pos, MEM_BUFFER_SIZE * sizeof(MEM_BUFFER_TYPE));

	memset(matrix, 0, sizeof(matrix));
	memset(icons, 0, sizeof(icons));
	tamalib_refresh_hw();

	return 0;
}
