"""Recognize EDRAM tone cues and extract the archived NT1X80 tone banks."""

import hashlib
from itertools import chain
from pathlib import Path


TEST_MENU = ((14, 1, 2), (15, 1, 3))
PROMPT_MENU = (((13, 1, 16),)
               + ((14, 1, 1), (15, 1, 2), (13, 1, 1)) * 2
               + ((14, 1, 1), (15, 1, 2), (13, 1, 4)))
CUE_SHA256 = "2b6876311c7f97ba8bd33bc8af224ae2f3484fa4146e0c2f3a11536133672f68"

RECORDED_TONES = {
    "983a74a73302d137465260b5668a39714c2df06e3fe6d2e3ab58a1fd580eaa3d":
        ("CLASS short prompt tone", (398.4,)),
    "344bec89f753206c8f0590e4b15f12d1cef8838916c908fb77a281af376774b5":
        ("Short prompt tone", (398.4,)),
    "1c4f3655afb399e6256dcfec9ea176dd5e682a0b85dc557f0952ebeaa48dc773":
        ("Calling-card / operator bong with fade", (941, 1477, 350, 440)),
    "2b24480623b875c8737b51057e098cfdb03a0ace40a616def366c005e763d52c":
        ("Calling-card / operator bong with fade", (941, 1477, 350, 440)),
    "11a7c0d13a601824a96b6f2b647efb793f464de9ffb02f7d2562159c73c7d917":
        ("ACCS calling-card bong with fade", (941, 1477, 350, 440)),
    "182f860b86e3e0edec45e00557ba0dfdb6daad007eea94da8b9f2dc94cb5e28a":
        ("French calling-card bong with fade", (941, 1477, 350, 440)),
    "83e5e8f93d31e9dffccfd95abf1411cc158967afa3b427367816989a6d281bff":
        ("ACTS alert, four repeated bursts", (350, 440, 480, 620)),
    "27c6f6eb0fbb645463176253bd6d05d5fc97501dd5e5dd7c2562b2b22b26178f":
        ("Single recorded busy signal", (478, 617.5)),
    "03cc143d225e751a1aa3d8bb4c8c7c3cb4b4e3be8216a616e8f19d0fb4ec3512":
        ("French CLASS busy signal", (400, 620)),
    "0e21722e474cbc19fc795a8fc4e38506dbe49f5523ed69187e8d64f051473113":
        ("Spanish CLASS busy signal", (480, 620)),
    "4b8a9aa081525c5c290f185376f873529e2e8b06ac19baf7d369f0b4ae8bf091":
        ("ABC tone with fade", (941, 1477, 350, 440)),
    "4fef9b2cac6e2209885e8e523c070dd395dd40fdc8f34506edfc199d6cf14a37":
        ("Spanish CLASS cancellation prompt", (400,)),
}

# The archived Spanish busy cue has a full-scale glitch in its lead-in.
RECORDED_LEAD_REPAIRS = {
    "0e21722e474cbc19fc795a8fc4e38506dbe49f5523ed69187e8d64f051473113": 513,
}

SHARED_START = 0x2100
SHARED_END = 0x5E94
EXTRA_START = 0x5E9E
EXTRA_END = 0x11444
SHARED_SHA256 = "aba6ae51368b1a70186db98c67d16429bd85b8d83278c49fb0327e90e7d18452"
EXTRA_SHA256 = "ccc25cd2d7fb860e1f9356f274dc09349bd35a74fb89247d36d28e31b106a5ea"

SHARED_LABELS = (
    ("350 + 480 Hz", (350, 480)), ("440 + 620 Hz", (440, 620)),
    ("850 Hz", (850,)), ("1340 Hz, first level", (1340,)),
    ("440 Hz, first level", (440,)), ("440 Hz, second level", (440,)),
    ("1340 Hz, second level", (1340,)), ("440 Hz, third level", (440,)),
    ("1004 Hz milliwatt carrier", (1004,)),
    ("Receiver off-hook howler", (1404, 2060, 2452, 2604)),
    ("948 Hz test carrier", (948,)), ("1020 Hz, short carrier", (1020,)),
    ("1004 Hz, level variant 1", (1004,)), ("1004 Hz, level variant 2", (1004,)),
    ("1004 Hz, level variant 3", (1004,)), ("1020 Hz, long carrier", (1020,)),
    ("1004 Hz, level variant 4", (1004,)),
)

# The stored 394-sample periods correspond to these integer cycle counts.
DTMF_ORDER = "D1234567890*#ABC"
DTMF_CYCLES = dict(zip("123A456B789C*0#D", (
    (low, high) for low in (34, 38, 42, 46) for high in (60, 66, 72, 80))))


def dtmf_labels(group):
    return tuple((f"DTMF {key}, set {group}", tuple(round(c * 8000 / 394, 1) for c in DTMF_CYCLES[key]))
                 for key in DTMF_ORDER)


EXTRA_LABELS = (
    SHARED_LABELS[:4] + dtmf_labels(1)
    + (("440 Hz extended, first level", (440,)), ("440 Hz extended, second level", (440,)))
    + (("350 + 480 Hz, quieter sample", (350, 480)), ("440 + 620 Hz, quieter sample", (440, 620)),
       ("850 Hz, quieter sample", (850,)), ("1340 Hz, quieter sample", (1340,)),
       ("1400 Hz", (1400,)), ("Constant fill 0xff", ()))
    + dtmf_labels(2)
    + (("400 Hz extended, first level", (400,)), ("400 Hz extended, second level", (400,)),
       ("Constant fill 0x00", ()))
)


def cue_profile(image, phrase, bank_size, page_size):
    menu = tuple((s.page, s.pages, s.repeats) for s in phrase.segments)
    if menu not in (TEST_MENU, PROMPT_MENU):
        return None
    start = phrase.bank * bank_size + 14 * page_size
    for address in (start, start - 1):
        raw = image.read_bytes(address, 2 * page_size)
        if hashlib.sha256(raw).hexdigest() == CUE_SHA256:
            break
    else:
        return None
    if menu == TEST_MENU:
        return "750 Hz test tone", [{"frequency_hz": 750, "duration_ms": 160}]
    return "Three-burst 750 Hz prompt", [
        {"frequency_hz": hz, "duration_ms": ms}
        for hz, ms in ((0, 512), (750, 96), (0, 32), (750, 96), (0, 32), (750, 96), (0, 128))
    ]


def word_count(data, offset):
    return int.from_bytes(data[offset:offset + 2], "big")


def padded_records(data):
    """Recover two-byte big-endian word counts following zero padding."""
    cursor = 0
    while cursor < len(data):
        first = cursor
        while first < len(data) and data[first] == 0:
            first += 1
        if first == len(data):
            return
        candidates = []
        for offset in (first - 1, first):
            if offset < cursor:
                continue
            end = offset + 2 + 2 * word_count(data, offset)
            if offset + 2 < end <= len(data) and not any(data[end:end + 6]):
                candidates.append((offset, end))
        if len(candidates) != 1:
            raise ValueError("ambiguous word count in padded tone bank")
        offset, cursor = candidates[0]
        yield offset, data[offset + 2:cursor]


def contiguous_records(data):
    offset = 0
    while offset < len(data):
        end = offset + 2 + 2 * word_count(data, offset)
        if offset + 2 >= end or end > len(data):
            raise ValueError("invalid word count in contiguous tone bank")
        yield offset, data[offset + 2:end]
        offset = end


def matched_region(image, start, end, digest):
    data = image.read_bytes(start, end - start)
    if hashlib.sha256(data).hexdigest() == digest:
        return image.read_bytes(start, end - start, required=True)
    return None


def records(image):
    """Yield manifest metadata and encoded sample bytes for verified archive regions."""
    tag = image.read_bytes(0x670, 10)
    if tag not in (b"TONE00AA10", b"TONE00AB10"):
        return
    shared = matched_region(image, SHARED_START, SHARED_END, SHARED_SHA256)
    if shared is None:
        return
    groups = [(SHARED_START, SHARED_LABELS, padded_records(shared))]
    if tag == b"TONE00AB10":
        extra = matched_region(image, EXTRA_START, EXTRA_END, EXTRA_SHA256)
        if extra is not None:
            groups.append((EXTRA_START, EXTRA_LABELS, contiguous_records(extra)))
    index = 0
    for start, labels, parsed in groups:
        for (name, frequencies), (offset, raw) in zip(labels, parsed, strict=True):
            index += 1
            header = start + offset
            info = {"index": index, "tone_name": name, "frequencies_hz": list(frequencies),
                    "header_address": header, "sample_address": header + 2, "samples": len(raw),
                    "codec": "mulaw-unmasked" if header < 0xB5EA else "alaw-unmasked",
                    "payload_sha256": hashlib.sha256(raw).hexdigest()}
            if frequencies:
                info["wav"] = f"tone-bank/tone_{index:02d}.wav"
            else:
                info.update(wav=None, constant_byte=raw[0])
            yield info, raw


def repair_samples(entry, raw):
    # A sign-bit error in the shared record is confirmed by EDRMTONE record 18.
    if entry["index"] == 1:
        entry["sample_repair"] = {"sample_index": 3, "original_code": 0x94, "replacement_code": 0x54}
        return raw[:3] + b"\x54" + raw[4:]
    return raw


def bank_clips(manifest):
    source = Path(manifest["source"]).stem
    for entry in manifest.get("tone_bank", []):
        if entry["wav"]:
            yield {
                **entry, "path": (Path(source) / entry["wav"]).as_posix(),
                "source": source, "label": f'tone_{entry["index"]:02d}',
                "kind": "tone-bank", "seconds": entry["samples"] / manifest["sample_rate"],
                "content": "tone", "description": entry["tone_name"], "transcript": {"text": ""},
            }


def raw_bank_paths(manifest, bank_size, page_size):
    """Find generic WAV exports that expand tone-bank records as phrase pages."""
    regions = [(tone["header_address"], tone["sample_address"] + tone["samples"])
               for tone in manifest.get("tone_bank", ())]
    if not regions:
        return set()
    source = Path(manifest["source"]).stem
    paths = set()
    for entry in chain(manifest["phrases"], manifest.get("segments", ())):
        if not entry["wav"]:
            continue
        base = entry["bank"] * bank_size
        for segment in entry.get("segments", (entry,)):
            start = base + segment["page"] * page_size
            end = start + segment["pages"] * page_size
            if any(start < region_end and region_start < end for region_start, region_end in regions):
                paths.add((Path(source) / entry["wav"]).as_posix())
                break
    return paths
