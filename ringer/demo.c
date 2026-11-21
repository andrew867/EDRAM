#include "ringer.h"

#include <stdio.h>

static void write_le(FILE *out, uint32_t value, unsigned width)
{
    for (unsigned i = 0; i < width; i++) {
        fputc((int)(value & 255), out);
        value >>= 8;
    }
}

int main(int argc, char **argv)
{
    const uint32_t rate = 16000;
    const uint32_t frames = 2 * rate;
    const char *names[] = {"low-fast", "high-fast", "narrow-pulse", "three-pitch"};

    if (argc != 1) {
        fprintf(stderr, "Usage: %s (writes four WAVs to the current directory)\n", argv[0]);
        return 1;
    }
    for (int profile = 0; profile < RINGER_PROFILE_COUNT; profile++) {
        nortel_ringer ring;
        char filename[64];
        snprintf(filename, sizeof filename, "t7316-%s.wav", names[profile]);
        if (!ringer_init(&ring, rate, (enum ringer_profile)profile)) {
            return 1;
        }
        FILE *out = fopen(filename, "wb");
        if (out == NULL) {
            perror(filename);
            return 1;
        }
        fwrite("RIFF", 1, 4, out);
        write_le(out, 36 + frames * 2, 4);
        fwrite("WAVEfmt ", 1, 8, out);
        write_le(out, 16, 4);
        write_le(out, 1, 2);
        write_le(out, 1, 2);
        write_le(out, rate, 4);
        write_le(out, rate * 2, 4);
        write_le(out, 2, 2);
        write_le(out, 16, 2);
        fwrite("data", 1, 4, out);
        write_le(out, frames * 2, 4);
        const uint32_t ramp = rate / 250;
        for (uint32_t i = 0; i < frames; i++) {
            uint32_t edge = i < frames / 2 ? i : frames - 1 - i;
            int32_t sample = ringer_next(&ring);
            if (edge < ramp) {
                sample = sample * (int32_t)edge / (int32_t)ramp;
            }
            write_le(out, (uint16_t)sample, 2);
        }
        int failed = ferror(out);
        if (fclose(out) != 0 || failed) {
            fprintf(stderr, "Could not finish %s\n", filename);
            return 1;
        }
    }
    return 0;
}
