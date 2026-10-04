/* The emulator wrapper plus one function the experiments need: write RAM. */
#include "../src/tama_core.c"

void tama_set_memory(uint32_t addr, uint8_t v)
{
	if (addr < MEM_RAM_SIZE) {
		SET_RAM_MEMORY(cpu_get_state()->memory, addr, v);
	}
}
