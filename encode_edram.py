#!/usr/bin/env python3
"""Build a factory-style EDRAM announcement load or rebuild a native tone-service bank."""

import argparse
from itertools import groupby
from pathlib import Path
import re
import struct
import wave

import edram
import tone_bank


DATA = Path(__file__).resolve().parent / "data"
TEMPLATE = DATA / "original" / "estd0aa.bin44"
TONE_BANK_COUNTS = {"mwttone": 17, "edrmtone": 64}
CUE_SLOTS = {"test": 1, "prompt": 2}
FIRST_VOICE_PHRASE = 40
FIRST_VOICE_ADDRESS = 0x2100
NAME_ADDRESS = 0x670
SILENCE_CODE = 0x00
PHRASE_CAPACITY = edram.BANK_SIZE - FIRST_VOICE_ADDRESS
STORED_TONE_ALIASES = {"milliwatt": ("mwttone", 9), "howler": ("mwttone", 10)}


def alaw_encode(sample):
    """Quantize signed linear PCM to the unmasked code used in the voice data."""
    magnitude = sample if sample >= 0 else -sample - 1
    exponent = max(0, magnitude.bit_length() - 8)
    mantissa = (magnitude >> max(4, exponent + 3)) & 15
    return (0x80 if sample >= 0 else 0) | (exponent << 4) | mantissa


def read_voice(path):
    with wave.open(str(path), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (edram.RATE, 1, 2):
            raise ValueError(f"{path} must be mono 8000 Hz 16-bit PCM")
        frames = source.getnframes()
        if not 0 < frames <= PHRASE_CAPACITY:
            raise ValueError(f"{path} is empty or exceeds the bank's voice capacity")
        pcm = source.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError(f"truncated PCM in {path}")
    return bytes(alaw_encode(sample) for sample, in struct.iter_unpack("<h", pcm))


def read_bank(bank, cache):
    if bank not in TONE_BANK_COUNTS:
        raise ValueError(f"unsupported native tone bank: {bank}")
    if bank not in cache:
        source = (DATA / "original" / f"{bank}.txt80").read_bytes()
        image = edram.Image(edram.parse_srec(source), strict_overlaps=True)
        records = list(tone_bank.records(image))
        if len(records) != TONE_BANK_COUNTS[bank]:
            raise ValueError(f"{bank}: incomplete or unrecognized tone bank")
        cache[bank] = source, image, records
    return cache[bank]


def find_bank_tone(component, cache):
    if component in STORED_TONE_ALIASES:
        bank, selector = STORED_TONE_ALIASES[component]
    elif match := re.fullmatch(r"(mwttone|edrmtone):([0-9]+)", component):
        bank, selector = match[1], int(match[2])
    elif match := re.fullmatch(r"dtmf:([0-9a-d*#])(?::([12]))?", component):
        bank, selector = "edrmtone", f"DTMF {match[1].upper()}, set {match[2] or '1'}"
    else:
        raise ValueError(f"unknown stored tone: {component!r}")

    for entry, raw in read_bank(bank, cache)[2]:
        if selector in (entry["index"], entry["tone_name"]) and entry["wav"]:
            return entry, raw
    raise ValueError(f"no playable stored tone: {component!r}")


def stored_tone(component, cache):
    if cue := re.fullmatch(r"cue:(page:)?(test|prompt)", component):
        if not cue[1]:
            raise ValueError(f"{component}: native firmware cue uses mu-law; use cue:page:{cue[2]} "
                             "for the archived A-law announcement cue")
        return template_phrase(cache, CUE_SLOTS[cue[2]])
    if match := re.fullmatch(r"sit:(page|firmware):([0-9]+)(?::(4040|5050))?", component):
        number = int(match[2])
        if not 1 <= number <= 32:
            raise ValueError("SIT number must be from 1 to 32")
        if match[1] == "firmware":
            raise ValueError(f"{component}: native firmware SIT includes mu-law codes; "
                             f"use sit:page:{number} for the archived A-law announcement SIT")
        if match[3]:
            raise ValueError(f"{component}: page-based SIT has no firmware selector")
        return template_phrase(cache, number + 7)
    entry, raw = find_bank_tone(component, cache)
    if entry["codec"] != "alaw-unmasked":
        raise ValueError(f"{component}: stored mu-law cannot be placed in an A-law phrase byte for byte; "
                         "use --tone-bank for the native tone service")
    return raw


def template_phrase(cache, slot):
    if "template" not in cache:
        image = edram.Image.read(TEMPLATE)
        cache["template"] = image, {p.number: p for p in image.phrases() if p.bank == 0}
    image, phrases = cache["template"]
    return edram.render_codes(image, phrases[slot])[0]


def read_tone(spec):
    """Concatenate stored OEM A-law waveform codes for ordinary phrase playback."""
    codes = bytearray()
    cache = {}
    for item in spec.split(","):
        component = item.strip().casefold()
        if "@" in component:
            raise ValueError("tone phrases require stored OEM waveform names")
        codes.extend(stored_tone(component, cache))
        if len(codes) > PHRASE_CAPACITY:
            raise ValueError("tone sequence exceeds the bank's voice capacity")
    return bytes(codes)


def word_checksum(payloads):
    """Sum big-endian payload words in transport order, including rewrites."""
    return sum(word for data in payloads for word, in struct.iter_unpack(">H", data)) & 0xffffffff


def with_record_checksum(fields):
    return fields + bytes([~sum(fields) & 0xff])


def serialize(records, transport, *, checksum=None):
    if checksum is None:
        checksum = word_checksum(data for _, data in records)
    footer = checksum.to_bytes(4, "big")
    if transport == "bin44":
        def g_record(kind, fields):
            return (kind + with_record_checksum(fields)).ljust(43, b"\0") + b"\x16"

        data = [g_record(b"G0" if i == 0 else b"G2", bytes([len(payload)]) + address.to_bytes(3, "big") + payload)
                for i, (address, payload) in enumerate(records)]
        return b"".join(data) + g_record(b"G6", b"\x01" + footer)

    def s_record(kind, fields):
        return kind + with_record_checksum(bytes([len(fields) + 1]) + fields).hex().upper().encode("ascii")

    data = [s_record(b"S2", address.to_bytes(3, "big") + payload) for address, payload in records]
    return b"\n".join([*data, s_record(b"S6", footer), b""])


def build_tone_bank(bank, replacements=None):
    """Re-encode an OEM tone bank and optionally replace same-layout EDRMTONE payloads."""
    cache = {}
    source, image, stored = read_bank(bank, cache)
    footer = int(source.split()[-1][4:12], 16)
    if replacements and bank != "edrmtone":
        raise ValueError("MWTTONE replacements require a verified aggregate checksum rule")

    patches = {}
    expected = {entry["index"]: raw for entry, raw in stored}
    for index, selector in (replacements or {}).items():
        if not 1 <= index <= len(stored) or not stored[index - 1][0]["wav"]:
            raise ValueError(f"{bank}: invalid playable tone index {index}")
        dest, original = stored[index - 1]
        replacement, raw = find_bank_tone(selector.casefold(), cache)
        if replacement["codec"] != dest["codec"] or len(raw) != len(original):
            raise ValueError(f"{bank}:{index} replacement must have the same law and sample count")
        if replacement["frequencies_hz"] != dest["frequencies_hz"]:
            raise ValueError(f"{bank}:{index} replacement must have the same nominal frequencies")
        patches[dest["sample_address"]] = raw
        expected[index] = raw

    updated = image.data.copy()
    for address, raw in patches.items():
        updated[address:address + len(raw)] = raw
    records = [(r.address, bytes(updated[r.address:r.address + len(r.data)])) for r in image.records]
    if bank == "edrmtone" and word_checksum(r.data for r in image.records) != footer:
        raise ValueError("EDRMTONE template aggregate checksum mismatch")

    trailing = source[len(source.rstrip(b"\n")):]
    rebuilt = serialize(records, "txt80", checksum=None if patches else footer).rstrip(b"\n") + trailing
    if not patches and rebuilt != source:
        raise ValueError(f"{bank}: native transport round trip changed the original file")
    decoded = edram.Image(edram.parse_srec(rebuilt), strict_overlaps=True)
    actual = {entry["index"]: raw for entry, raw in tone_bank.records(decoded)}
    if decoded.data != updated or decoded.coverage != image.coverage or actual != expected:
        raise ValueError(f"{bank}: native tone bank round trip changed the image")
    return rebuilt


def build_load(name, phrases, transport, *, repeats=None):
    """Build a named load from unmasked A-law codes and optional range repeats."""
    if not re.fullmatch(r"[A-Z0-9_]{1,8}", name):
        raise ValueError("load name must contain one to eight uppercase letters, digits or underscores")
    if not phrases or any(not FIRST_VOICE_PHRASE <= number <= 63 or not data for number, data in phrases.items()):
        raise ValueError("supply at least one nonempty voice phrase with an ID from 40 to 63")
    if transport not in ("bin44", "txt80"):
        raise ValueError(f"unsupported transport: {transport}")

    repeats = repeats or {}
    if any(number not in phrases or not isinstance(count, int) or not 1 <= count <= 255
           for number, count in repeats.items()):
        raise ValueError("repeat counts must be 1 to 255 and refer to an authored phrase")

    image = edram.Image.read(TEMPLATE)
    source_phrases = image.phrases()
    retained = [p for p in source_phrases if p.bank == 0 and p.number < FIRST_VOICE_PHRASE]
    # Reuse the known voice header, phrase tables and tone region of ESTD0AA.
    data = bytearray(image.read_bytes(0, FIRST_VOICE_ADDRESS))
    present = bytearray(image.coverage[:FIRST_VOICE_ADDRESS])
    submenu = max(p.menu_address + 4 * len(p.segments) for p in retained)
    data[4 * FIRST_VOICE_PHRASE:256] = b"\xff" * (4 * (64 - FIRST_VOICE_PHRASE))
    present[4 * FIRST_VOICE_PHRASE:256] = b"\x01" * (4 * (64 - FIRST_VOICE_PHRASE))
    data[NAME_ADDRESS:NAME_ADDRESS + 8] = name.ljust(8).encode("ascii")
    expected = {}
    for number, codes in sorted(phrases.items()):
        padding = -len(codes) % edram.PAGE_SIZE
        padded = codes + bytes([SILENCE_CODE]) * padding
        start_page = len(data) // edram.PAGE_SIZE
        pages = len(padded) // edram.PAGE_SIZE
        if len(data) + len(padded) > edram.BANK_SIZE:
            raise ValueError(f"phrase {number} exceeds the remaining single-bank voice capacity")
        count = repeats.get(number, 1)
        if count > 1 and pages > 255:
            raise ValueError(f"repeated phrase {number} exceeds the 255-page range limit")
        if len(padded) * count > edram.MAX_PHRASE_SAMPLES:
            raise ValueError(f"repeated phrase {number} exceeds the 10-minute output limit")
        entries = bytearray()
        while pages:
            range_pages = min(pages, 255)
            entries.extend(struct.pack("<HBB", start_page, range_pages, count))
            start_page += range_pages
            pages -= range_pages
        if submenu + len(entries) > NAME_ADDRESS:
            raise ValueError("voice submenus would overlap the load identifier")
        header = struct.pack("<HB", submenu, len(entries) // 4)
        data[number * 4:number * 4 + 4] = header + bytes([-(sum(header) + sum(entries)) & 0xff])
        data[submenu:submenu + len(entries)] = entries
        present[submenu:submenu + len(entries)] = b"\x01" * len(entries)
        submenu += len(entries)
        data.extend(padded)
        present.extend(b"\x01" * len(padded))
        expected[number] = (padded, count)

    limit = 36 if transport == "bin44" else 24
    records = []
    for covered, positions in groupby(range(len(present)), key=present.__getitem__):
        if covered:
            first = next(positions)
            stop = first + 1 + sum(1 for _ in positions)
            records.extend((start, data[start:min(start + limit, stop)]) for start in range(first, stop, limit))
    result = serialize(records, transport)
    parse = edram.parse_bin44 if transport == "bin44" else edram.parse_srec
    rebuilt = edram.Image(parse(result), strict_overlaps=True)
    verified = {p.number: p for p in rebuilt.phrases()}
    if [p for p in verified.values() if p.number < FIRST_VOICE_PHRASE] != retained:
        raise ValueError("encoder verification failed for the retained template menus")
    for number, (codes, count) in expected.items():
        raw, holes = edram.render_codes(rebuilt, verified[number])
        if holes or raw != codes * count:
            raise ValueError(f"encoder round trip failed for phrase {number}")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new .bin44 or .txt80 file")
    parser.add_argument("--name", help="internal load name (default: uppercase output stem)")
    parser.add_argument("--phrase", action="append", default=[], nargs=2, metavar=("ID", "WAV"),
                        help="phrase number 40 to 63 and its mono 8 kHz PCM WAV")
    parser.add_argument("--tone", action="append", default=[], nargs=2, metavar=("ID", "SPEC"),
                        help="phrase number 40 to 63 and stored A-law tones such as cue:page:test,sit:page:1")
    parser.add_argument("--repeat", action="append", default=[], nargs=2, metavar=("ID", "COUNT"),
                        help="repeat the authored phrase's whole padded range 1 to 255 times")
    parser.add_argument("--tone-bank", choices=TONE_BANK_COUNTS, help="rebuild an OEM standalone .txt80 bank")
    parser.add_argument("--replace-tone", action="append", default=[], nargs=2, metavar=("INDEX", "SOURCE"),
                        help="replace an EDRMTONE record with a compatible OEM waveform variant")
    args = parser.parse_args(argv)
    if args.tone_bank:
        if args.phrase or args.tone or args.repeat or args.name or args.output.suffix.lower() != ".txt80":
            parser.error("--tone-bank takes a .txt80 output and optional --replace-tone")
        try:
            replacements = {}
            for index, selector in args.replace_tone:
                index = int(index)
                if index in replacements:
                    raise ValueError(f"duplicate tone record index: {index}")
                replacements[index] = selector
            raw = build_tone_bank(args.tone_bank, replacements)
            with args.output.open("xb") as output:
                output.write(raw)
        except (OSError, ValueError) as exc:
            parser.exit(1, f"{parser.prog}: {exc}\n")
        print(f"{args.output}: {len(raw)} bytes, native tone bank round trip passed")
        return
    if args.replace_tone:
        parser.error("--replace-tone requires --tone-bank")
    if not args.phrase and not args.tone:
        parser.error("supply at least one --phrase or --tone")
    try:
        phrases = {}
        for read, entries in ((read_voice, args.phrase), (read_tone, args.tone)):
            for number, source in entries:
                number = int(number)
                if number in phrases:
                    raise ValueError(f"duplicate phrase ID: {number}")
                if not FIRST_VOICE_PHRASE <= number <= 63:
                    raise ValueError(f"phrase ID must be from 40 to 63: {number}")
                phrases[number] = read(source)
        repeats = {}
        for phrase_id, count in args.repeat:
            number = int(phrase_id)
            if number in repeats:
                raise ValueError(f"duplicate repeat for phrase ID: {number}")
            repeats[number] = int(count)
        name = args.name or args.output.stem.upper()
        raw = build_load(name, phrases, args.output.suffix.lower().lstrip("."), repeats=repeats)
        with args.output.open("xb") as output:
            output.write(raw)
    except (OSError, ValueError, wave.Error) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
    print(f"{args.output}: {len(phrases)} phrases, {len(raw)} bytes, decoder round trip passed")


if __name__ == "__main__":
    main()
