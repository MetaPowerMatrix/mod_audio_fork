MODNAME = mod_audio_fork.so
AUDIO_FORK_C = audio_fork
SRC = mod_audio_fork.c audio_pipe.cpp lws_glue.cpp parser.cpp
CXX = g++
CC = gcc
CXXFLAGS = -fPIC -Wall -Wno-unused-variable -Wno-parentheses -Wno-unused-but-set-variable -Wno-reorder -g \
    `pkg-config --cflags freeswitch` \
    `pkg-config --cflags libwebsockets`
CFLAGS = -Wall -g \
    `pkg-config --cflags freeswitch` \
    `pkg-config --cflags json-c`
LDFLAGS = \
    `pkg-config --libs freeswitch` \
    `pkg-config --libs libwebsockets`
AUDIO_FORK_LDFLAGS = \
    `pkg-config --libs freeswitch` \
    `pkg-config --libs json-c` \
    -lesl

all: $(MODNAME) $(AUDIO_FORK_C)

$(MODNAME): $(SRC)
	$(CXX) -shared -o $@ $(SRC) $(CXXFLAGS) $(LDFLAGS)

$(AUDIO_FORK_C): audio_fork.c
	$(CC) -o $@ $< $(CFLAGS) $(AUDIO_FORK_LDFLAGS)

install: $(MODNAME)
	install -d /usr/lib/freeswitch/mod
	install $(MODNAME) /usr/lib/freeswitch/mod

clean:
	rm -f $(MODNAME) $(AUDIO_FORK_C) *.o
