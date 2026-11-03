CC ?= gcc
CFLAGS ?= -O2 -g -std=gnu11 -Wall -Wextra -Werror -pthread
BUILD := build
PROGS := sched_latency syscall_bench

all: $(addprefix $(BUILD)/,$(PROGS))

$(BUILD)/%: %.c common.c common.h | $(BUILD)
	$(CC) $(CFLAGS) -o $@ $< common.c

$(BUILD):
	mkdir -p $@

clean:
	rm -rf $(BUILD)

.PHONY: all clean
