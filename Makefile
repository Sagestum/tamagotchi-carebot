CC ?= gcc
CFLAGS ?= -O2 -fPIC -Wall

SRC = src/tama_core.c src/tamalib/cpu.c src/tamalib/hw.c src/tamalib/tamalib.c src/pika_core.c

libtama.so: $(SRC) src/hal_types.h src/m37520_ops.h
	$(CC) $(CFLAGS) -shared -o $@ $(SRC)

clean:
	rm -f libtama.so

.PHONY: clean
