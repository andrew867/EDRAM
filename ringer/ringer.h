#ifndef NORTEL_RINGER_H
#define NORTEL_RINGER_H

#include <stdint.h>

/* Measured T7316 profiles in order of first appearance in the recording. */
enum ringer_profile {
    RINGER_LOW_FAST,
    RINGER_HIGH_FAST,
    RINGER_NARROW_PULSE,
    RINGER_THREE_PITCH,
    RINGER_PROFILE_COUNT
};

enum { RINGER_TABLE_SIZE = 256 };

typedef struct {
    uint32_t phase;
    uint32_t elapsed;
    uint32_t steps[3];
    uint32_t stage_ends[3];
    unsigned stage;
    enum ringer_profile profile;
    int16_t table[3][RINGER_TABLE_SIZE];
} nortel_ringer;

/* Prepare before starting an audio callback. The render loop uses integer DDS. */
int ringer_init(nortel_ringer *ring, uint32_t sample_rate, enum ringer_profile profile);
int16_t ringer_next(nortel_ringer *ring);

#endif
