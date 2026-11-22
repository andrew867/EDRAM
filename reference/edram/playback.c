#include "playback.h"

#include <string.h>

static unsigned le16(const uint8_t *p)
{
    return (unsigned)p[0] | (unsigned)p[1] << 8;
}

static size_t tone_record_codes(const uint8_t *p)
{
    return ((size_t)p[0] << 8 | p[1]) * 2;
}

static void enter_voice_descriptor(struct edram_voice *voice)
{
    const uint8_t *entry = voice->bank + voice->descriptor;
    voice->start_page = le16(entry);
    voice->pages = entry[2];
    voice->repeats_left = entry[3];
    voice->page_index = 0;
}

enum edram_result edram_voice_begin(struct edram_voice *voice,
                                    const uint8_t *bank, size_t bank_size,
                                    unsigned slot)
{
    *voice = (struct edram_voice){0};
    if (bank == NULL || bank_size != EDRAM_BANK_SIZE || slot >= EDRAM_SLOT_COUNT)
        return EDRAM_BAD_FORMAT;

    const uint8_t *entry = bank + slot * 4;
    if ((entry[0] | entry[1] | entry[2] | entry[3]) == 0 ||
        (entry[0] & entry[1] & entry[2] & entry[3]) == UINT8_MAX)
        return EDRAM_NO_PHRASE;

    unsigned count = entry[2];
    size_t offset = le16(entry);
    size_t bytes = (size_t)count * 4;
    if (count == 0 || offset < EDRAM_PAGE_SIZE || offset % 4 != 0 ||
        bytes > bank_size - offset)
        return EDRAM_BAD_FORMAT;

    unsigned sum = (unsigned)entry[0] + entry[1] + entry[2] + entry[3];
    for (size_t i = 0; i < bytes; ++i)
        sum += bank[offset + i];
    if ((sum & 0xff) != 0)
        return EDRAM_BAD_CHECKSUM;

    for (size_t i = 0; i < bytes; i += 4) {
        const uint8_t *part = bank + offset + i;
        unsigned page = le16(part);
        if (page == 0)
            return EDRAM_OTHER_PATH;
        if (part[2] == 0 || part[3] == 0 ||
            page > (unsigned)EDRAM_BANK_SIZE / EDRAM_PAGE_SIZE - part[2])
            return EDRAM_BAD_FORMAT;
    }

    voice->bank = bank;
    voice->descriptor = offset;
    voice->entries_left = count;
    enter_voice_descriptor(voice);
    return EDRAM_OK;
}

bool edram_voice_page(struct edram_voice *voice, uint8_t out[EDRAM_PAGE_SIZE])
{
    if (voice->entries_left == 0)
        return false;

    unsigned page = voice->start_page + voice->page_index;
    if (page == 13)
        memset(out, 0, EDRAM_PAGE_SIZE);
    else
        memcpy(out, voice->bank + page * EDRAM_PAGE_SIZE, EDRAM_PAGE_SIZE);

    if (++voice->page_index == voice->pages) {
        voice->page_index = 0;
        if (--voice->repeats_left == 0 && --voice->entries_left != 0) {
            voice->descriptor += 4;
            enter_voice_descriptor(voice);
        }
    }
    return true;
}

enum edram_result edram_tone_begin(struct edram_tone *tone,
                                  const struct edram_tone_part *parts,
                                  size_t count)
{
    *tone = (struct edram_tone){0};
    if (parts == NULL || count == 0)
        return EDRAM_BAD_FORMAT;

    for (size_t i = 0; i < count; ++i) {
        const struct edram_tone_part *part = &parts[i];
        if (part->record == NULL || part->record_size < 2 ||
            part->duration_quanta == 0 || part->duration_quanta > 0xffffff)
            return EDRAM_BAD_FORMAT;
        size_t codes = tone_record_codes(part->record);
        if (codes == 0 || codes > part->record_size - 2)
            return EDRAM_BAD_FORMAT;
        if (part->duration_quanta == 0xffffff)
            return EDRAM_OTHER_PATH;
    }

    tone->parts = parts;
    tone->count = count;
    tone->codes_left = (size_t)parts[0].duration_quanta * 8;
    return EDRAM_OK;
}

size_t edram_tone_page(struct edram_tone *tone, uint8_t out[EDRAM_PAGE_SIZE])
{
    if (tone->current == tone->count)
        return 0;

    size_t produced = 0;
    while (produced < EDRAM_PAGE_SIZE && tone->current < tone->count) {
        const uint8_t *record = tone->parts[tone->current].record;
        size_t record_codes = tone_record_codes(record);
        size_t copy = record_codes - tone->record_offset;
        if (copy > tone->codes_left)
            copy = tone->codes_left;
        if (copy > EDRAM_PAGE_SIZE - produced)
            copy = EDRAM_PAGE_SIZE - produced;

        memcpy(out + produced, record + 2 + tone->record_offset, copy);
        produced += copy;
        tone->codes_left -= copy;
        tone->record_offset += copy;
        if (tone->record_offset == record_codes)
            tone->record_offset = 0;

        if (tone->codes_left == 0 && ++tone->current < tone->count) {
            tone->codes_left = (size_t)tone->parts[tone->current].duration_quanta * 8;
            tone->record_offset = 0;
        }
    }

    memset(out + produced, 0, EDRAM_PAGE_SIZE - produced);
    return produced;
}
