#ifndef EDRAM_PLAYBACK_H
#define EDRAM_PLAYBACK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum {
    EDRAM_PAGE_SIZE = 256,
    EDRAM_BANK_SIZE = 0x40000,
    EDRAM_SLOT_COUNT = 64
};

/* These are local API results. Only 0x41 denotes the native checksum error. */
enum edram_result {
    EDRAM_OK,
    EDRAM_NO_PHRASE,
    EDRAM_BAD_FORMAT,
    EDRAM_OTHER_PATH,
    EDRAM_BAD_CHECKSUM = 0x41
};

struct edram_voice {
    const uint8_t *bank;
    size_t descriptor;
    unsigned entries_left;
    unsigned start_page;
    unsigned pages;
    unsigned page_index;
    unsigned repeats_left;
};

/* Bank memory must remain readable and unchanged until playback finishes. */
enum edram_result edram_voice_begin(struct edram_voice *voice,
                                    const uint8_t *bank, size_t bank_size,
                                    unsigned slot);

/* Returns false after the last page. The final page is returned normally. */
bool edram_voice_page(struct edram_voice *voice, uint8_t out[EDRAM_PAGE_SIZE]);

struct edram_tone_part {
    /* Big-endian word count followed by that many two-byte sample words. */
    const uint8_t *record;
    size_t record_size;
    /* A finite duration expressed in eight-code units. */
    uint32_t duration_quanta;
};

struct edram_tone {
    const struct edram_tone_part *parts;
    size_t count;
    size_t current;
    size_t codes_left;
    size_t record_offset;
};

/* The caller resolves record addresses for the selected hardware profile. */
enum edram_result edram_tone_begin(struct edram_tone *tone,
                                   const struct edram_tone_part *parts,
                                   size_t count);

/* Returns the number of active codes written. A partial page is zero-padded. */
size_t edram_tone_page(struct edram_tone *tone, uint8_t out[EDRAM_PAGE_SIZE]);

#endif
