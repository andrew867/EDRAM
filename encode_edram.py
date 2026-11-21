#!/usr/bin/env python3
"""Build a single-bank factory-style EDRAM voice load from PCM WAVs and tone sequences."""

import argparse
from itertools import groupby
import math
from pathlib import Path
import re
import struct
import wave

import edram
import tone_bank


TEMPLATE = Path(__file__).resolve().parent / "data" / "original" / "estd0aa.bin44"
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


def stored_tone(component, banks):
    if component in STORED_TONE_ALIASES:
        source, selector = STORED_TONE_ALIASES[component]
    elif match := re.fullmatch(r"(mwttone|edrmtone):([0-9]+)", component):
        source, selector = match[1], int(match[2])
    elif match := re.fullmatch(r"dtmf:([0-9a-d*#])(?::([12]))?", component):
        source, selector = "edrmtone", f"DTMF {match[1].upper()}, set {match[2] or '1'}"
    else:
        raise ValueError(f"unknown stored tone: {component!r}")

    if source not in banks:
        image = edram.Image.read(TEMPLATE.with_name(source + ".txt80"))
        banks[source] = list(tone_bank.records(image))
    for entry, raw in banks[source]:
        if selector in (entry["index"], entry["tone_name"]) and entry["wav"]:
            if entry["codec"] == "alaw-unmasked":
                return raw
            pcm = edram.decode(raw, entry["codec"])
            return bytes(alaw_encode(value) for value, in struct.iter_unpack("<h", pcm))
    raise ValueError(f"no playable stored tone: {component!r}")


def synthesize_tone(frequencies, frames):
    steps = [math.tau * frequency / edram.RATE for frequency in frequencies]
    peak = 5000 / len(steps)
    ramp = round(edram.RATE * 0.002)
    samples = bytearray()
    for frame in range(frames):
        envelope = min(1.0, frame / ramp, (frames - 1 - frame) / ramp)
        sample = round(peak * envelope * sum(math.sin(step * frame) for step in steps))
        samples.append(alaw_encode(sample))
    return samples


def read_tone(spec):
    """Encode a comma-separated sequence of generated and archived tones."""
    codes = bytearray()
    banks = {}
    for item in spec.split(","):
        component = item.strip().casefold()
        frequency_text, separator, duration = component.partition("@")
        if not separator:
            codes.extend(stored_tone(component, banks))
        else:
            if not re.fullmatch(r"[0-9]+", duration) or int(duration) == 0:
                raise ValueError(f"tone duration must be a positive whole number of milliseconds: {item!r}")
            frames = int(duration) * edram.RATE // 1000
            if len(codes) + frames > PHRASE_CAPACITY:
                raise ValueError("tone sequence exceeds the bank's voice capacity")
            if frequency_text == "silence":
                codes.extend(bytes([SILENCE_CODE]) * frames)
            else:
                frequencies = tuple(float(f) for f in frequency_text.split("+"))
                if any(not 0 < frequency < edram.RATE / 2 for frequency in frequencies):
                    raise ValueError(f"tone frequencies must be greater than 0 Hz and below {edram.RATE // 2} Hz")
                codes.extend(synthesize_tone(frequencies, frames))
        if len(codes) > PHRASE_CAPACITY:
            raise ValueError("tone sequence exceeds the bank's voice capacity")
    return bytes(codes)


def word_checksum(payloads):
    """Sum big-endian payload words in transport order, including rewrites."""
    return sum(word for data in payloads for word, in struct.iter_unpack(">H", data)) & 0xffffffff


def with_record_checksum(fields):
    return fields + bytes([~sum(fields) & 0xff])


def serialize(records, transport):
    checksum = word_checksum(data for _, data in records).to_bytes(4, "big")
    if transport == "bin44":
        def g_record(kind, fields):
            return (kind + with_record_checksum(fields)).ljust(43, b"\0") + b"\x16"

        data = [g_record(b"G0" if i == 0 else b"G2", bytes([len(payload)]) + address.to_bytes(3, "big") + payload)
                for i, (address, payload) in enumerate(records)]
        return b"".join(data) + g_record(b"G6", b"\x01" + checksum)

    def s_record(kind, fields):
        return kind + with_record_checksum(bytes([len(fields) + 1]) + fields).hex().upper().encode("ascii")

    data = [s_record(b"S2", address.to_bytes(3, "big") + payload) for address, payload in records]
    return b"\n".join([*data, s_record(b"S6", checksum), b""])


def build_load(name, phrases, transport):
    """Build a named load from a mapping of phrase IDs to unmasked A-law codes."""
    if not re.fullmatch(r"[A-Z0-9_]{1,8}", name):
        raise ValueError("load name must contain one to eight uppercase letters, digits or underscores")
    if not phrases or any(not FIRST_VOICE_PHRASE <= number <= 63 or not data for number, data in phrases.items()):
        raise ValueError("supply at least one nonempty voice phrase with an ID from 40 to 63")
    if transport not in ("bin44", "txt80"):
        raise ValueError(f"unsupported transport: {transport}")

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
        entries = bytearray()
        while pages:
            count = min(pages, 255)
            entries.extend(struct.pack("<HBB", start_page, count, 1))
            start_page += count
            pages -= count
        if submenu + len(entries) > NAME_ADDRESS:
            raise ValueError("voice submenus would overlap the load identifier")
        header = struct.pack("<HB", submenu, len(entries) // 4)
        data[number * 4:number * 4 + 4] = header + bytes([-(sum(header) + sum(entries)) & 0xff])
        data[submenu:submenu + len(entries)] = entries
        present[submenu:submenu + len(entries)] = b"\x01" * len(entries)
        submenu += len(entries)
        data.extend(padded)
        present.extend(b"\x01" * len(padded))
        expected[number] = padded

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
    for number, codes in expected.items():
        pcm, holes = edram.render(rebuilt, verified[number])
        if holes or pcm != edram.decode(codes):
            raise ValueError(f"encoder round trip failed for phrase {number}")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new .bin44 or .txt80 file")
    parser.add_argument("--name", help="internal load name (default: uppercase output stem)")
    parser.add_argument("--phrase", action="append", default=[], nargs=2, metavar=("ID", "WAV"),
                        help="phrase number 40 to 63 and its mono 8 kHz PCM WAV")
    parser.add_argument("--tone", action="append", default=[], nargs=2, metavar=("ID", "SPEC"),
                        help="phrase number 40 to 63 and a tone sequence such as 350+440@250,silence@100")
    args = parser.parse_args(argv)
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
        name = args.name or args.output.stem.upper()
        raw = build_load(name, phrases, args.output.suffix.lower().lstrip("."))
        with args.output.open("xb") as output:
            output.write(raw)
    except (OSError, ValueError, wave.Error) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
    print(f"{args.output}: {len(phrases)} phrases, {len(raw)} bytes, decoder round trip passed")


if __name__ == "__main__":
    main()
