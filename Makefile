CC ?= gcc
CFLAGS ?= -O2 -fPIC -Wall

SRC = src/tama_core.c src/tamalib/cpu.c src/tamalib/hw.c src/tamalib/tamalib.c

libtama.so: $(SRC) src/hal_types.h
	$(CC) $(CFLAGS) -shared -o $@ $(SRC)

clean:
	rm -f libtama.so

.PHONY: clean
