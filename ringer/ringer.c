#include "ringer.h"

#include <math.h>
#include <stddef.h>

typedef struct {
    double frequency;
    uint32_t duration_us;
} tone_stage;

typedef struct {
    unsigned count;
    double duty;
    tone_stage stages[3];
} ring_pattern;

static const ring_pattern patterns[] = {
    {2, 0.50, {{1000.0 / 3.0, 50000}, {250.0, 50000}}},
    {2, 0.50, {{2000.0 / 3.0, 50000}, {500.0, 50000}}},
    {2, 0.25, {{1000.0 / 3.0, 87500}, {500.0, 87500}}},
    {3, 0.50, {{1000.0 / 3.0, 136000}, {500.0, 76000}, {2000.0 / 3.0, 76000}}},
};

/* Round cumulative stage edges, so rounding individual phases cannot accumulate. */
static uint32_t stage_end_sample(const ring_pattern *pattern, uint32_t sample_rate, unsigned stage)
{
    uint32_t us = 0;
    for (unsigned i = 0; i <= stage; i++) {
        us += pattern->stages[i].duration_us;
    }
    return (uint32_t)(((uint64_t)us * sample_rate + 500000) / 1000000);
}

static uint32_t phase_step(double frequency, uint32_t sample_rate)
{
    return (uint32_t)(frequency * 4294967296.0 / sample_rate + 0.5);
}

int ringer_init(nortel_ringer *ring, uint32_t sample_rate, enum ringer_profile profile)
{
    const double pi = 3.14159265358979323846;
    if (ring == NULL || sample_rate < 8000 || sample_rate > 192000 ||
        (unsigned)profile >= RINGER_PROFILE_COUNT) {
        return 0;
    }

    const ring_pattern *pattern = &patterns[profile];
    const double limit = fmin(5200.0, 0.45 * sample_rate);
    ring->profile = profile;
    ring->stage = 0;
    ring->elapsed = 0;
    ring->phase = 0;
    for (unsigned stage = 0; stage < pattern->count; stage++) {
        const double frequency = pattern->stages[stage].frequency;
        ring->steps[stage] = phase_step(frequency, sample_rate);
        ring->stage_ends[stage] = stage_end_sample(pattern, sample_rate, stage);
        for (unsigned i = 0; i < RINGER_TABLE_SIZE; i++) {
            const double position = (double)i / RINGER_TABLE_SIZE;
            double sample = 0.0;
            /* Fourier series of a zero-mean pulse, with a smooth harmonic rolloff. */
            for (unsigned harmonic = 1; harmonic * frequency < limit; harmonic++) {
                const double taper = cos(pi * harmonic * frequency / (2.0 * limit));
                const double amplitude = 4.0 * sin(pi * harmonic * pattern->duty) / (pi * harmonic);
                sample += taper * amplitude * cos(2.0 * pi * harmonic * (position - pattern->duty / 2.0));
            }
            ring->table[stage][i] = (int16_t)lround(sample * 6000.0);
        }
    }
    return 1;
}

int16_t ringer_next(nortel_ringer *ring)
{
    const ring_pattern *pattern = &patterns[ring->profile];
    const unsigned index = ring->phase >> 24;
    const int16_t sample = ring->table[ring->stage][index];
    ring->phase += ring->steps[ring->stage];
    if (++ring->elapsed == ring->stage_ends[ring->stage]) {
        if (++ring->stage == pattern->count) {
            ring->stage = 0;
            ring->elapsed = 0;
        }
    }
    return sample;
}
