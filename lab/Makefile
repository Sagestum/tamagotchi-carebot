CC ?= gcc
CFLAGS ?= -O2 -fPIC -Wall

libtamalab.so: set_memory.c ../src/tama_core.c
	$(CC) $(CFLAGS) -shared -o $@ set_memory.c ../src/tamalib/cpu.c ../src/tamalib/hw.c ../src/tamalib/tamalib.c

clean:
	rm -f libtamalab.so *.pkl *.sav *.out

.PHONY: clean
