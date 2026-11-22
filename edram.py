#!/usr/bin/env python3
"""Decode Nortel EDRAM loads as played by the card or as stored in the file."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import struct

import firmware_sit
import tone_bank

VERSION = "0.3.1"
DEFAULT_FIRMWARE = Path(__file__).resolve().parent / "data" / "xacore" / "srecords" / "ED16AA07.srec"
LOAD_HEADER_OFFSET = 0x0670
LOAD_HEADER_SIZE = 12
RATE = 8000
BANK_SIZE = 0x40000
PAGE_SIZE = 256
MAX_IMAGE = 16 * 1024 * 1024
MAX_PHRASE_SAMPLES = RATE * 600


class FormatError(ValueError):
    """An invalid container, table, or reference."""


class ToneBankOverlap(FormatError):
    """A phrase page range contains standalone tone-bank records."""


@dataclass(frozen=True)
class Record:
    address: int
    data: bytes
    kind: str
    location: int


@dataclass(frozen=True)
class Segment:
    page: int
    pages: int
    repeats: int

    @property
    def samples(self):
        return self.pages * PAGE_SIZE * self.repeats


@dataclass(frozen=True)
class Phrase:
    bank: int
    number: int
    menu_address: int
    checksum: int
    segments: tuple[Segment, ...]


def parse_bin44(data: bytes) -> list[Record]:
    if not data or len(data) % 44:
        raise FormatError("bin44 length must be a nonzero multiple of 44")
    records = []
    ended = False
    for offset in range(0, len(data), 44):
        raw = data[offset:offset + 44]
        if raw[:2] not in (b"G0", b"G2", b"G6") or raw[43] != 0x16:
            raise FormatError(f"invalid bin44 framing at 0x{offset:x}")
        kind = raw[:2].decode("ascii")
        count = raw[2]
        if not 1 <= count <= 36:
            raise FormatError(f"invalid payload length at 0x{offset:x}")
        # The checksum follows the valid payload, not the padded 36-byte slot.
        if sum(raw[2:7 + count]) & 0xff != 0xff:
            raise FormatError(f"bin44 checksum mismatch at 0x{offset:x}")
        if ended or (offset == 0 and kind != "G0") or (offset and kind == "G0"):
            raise FormatError(f"invalid bin44 record order at 0x{offset:x}")
        if kind == "G6":
            ended = True
        else:
            records.append(Record(int.from_bytes(raw[3:6], "big"),
                                  raw[6:6 + count], kind, offset))
    if not ended:
        raise FormatError("missing final G6 record")
    return records


def parse_srec(data: bytes) -> list[Record]:
    records = []
    ended = False
    address_sizes = {"0": 2, "1": 2, "2": 3, "3": 4, "5": 2,
                     "6": 3, "7": 4, "8": 3, "9": 2}
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise FormatError("S-record input is not ASCII") from exc
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        if len(line) < 4 or line[0] != "S" or line[1] not in address_sizes:
            raise FormatError(f"invalid S-record at line {lineno}")
        try:
            raw = bytes.fromhex(line[2:])
        except ValueError as exc:
            raise FormatError(f"invalid hex at line {lineno}") from exc
        size = address_sizes[line[1]]
        if not raw or raw[0] != len(raw) - 1 or len(raw) < size + 2:
            raise FormatError(f"S-record length mismatch at line {lineno}")
        if sum(raw) & 0xff != 0xff:
            raise FormatError(f"S-record checksum mismatch at line {lineno}")
        if ended:
            raise FormatError(f"data after S-record termination at line {lineno}")
        if line[1] in "123":
            records.append(Record(int.from_bytes(raw[1:1 + size], "big"),
                                  raw[1 + size:-1], line[:2], lineno))
        elif line[1] in "789":
            ended = True
    if not records:
        raise FormatError("no S-record data")
    return records


class Image:
    def __init__(self, records: list[Record], *, strict_overlaps=False):
        end = max((r.address + len(r.data) for r in records), default=0)
        if not 0 < end <= MAX_IMAGE:
            raise FormatError("empty image or image exceeds 16 MiB")
        self.data = bytearray(end)
        self.coverage = bytearray(end)
        self.records = records
        self.overwrites = []
        for record in records:
            start, stop = record.address, record.address + len(record.data)
            previous = self.coverage[start:stop]
            if any(previous):
                changed = 0
                for index, byte in enumerate(record.data, start):
                    if self.coverage[index] and self.data[index] != byte:
                        if strict_overlaps:
                            raise FormatError(f"conflicting data at 0x{index:x}")
                        changed += 1
                if changed:
                    self.overwrites.append({"address": start, "location": record.location,
                                            "changed_bytes": changed})
            self.data[start:stop] = record.data
            self.coverage[start:stop] = b"\1" * len(record.data)

    @classmethod
    def read(cls, path: Path):
        data = path.read_bytes()
        records = parse_bin44(data) if data[:1] == b"G" else parse_srec(data)
        return cls(records)

    def read_bytes(self, start: int, size: int, *, required=False) -> bytes:
        if start < 0 or size < 0 or start + size > MAX_IMAGE:
            raise FormatError("reference outside supported address space")
        covered = self.coverage[start:start + size]
        if required and (len(covered) != size or not all(covered)):
            raise FormatError(f"missing table bytes at 0x{start:x}")
        value = self.data[start:start + size]
        return bytes(value) + bytes(size - len(value))

    def parse_phrase(self, base, number, entry):
        pointer, count, checksum = struct.unpack("<HBB", entry)
        if pointer < 256 or pointer % 4 or not count or pointer + count * 4 > 0x1100:
            raise FormatError(f"invalid phrase {base // BANK_SIZE}:{number} menu")
        submenu = self.read_bytes(base + pointer, count * 4, required=True)
        if (sum(entry) + sum(submenu)) & 0xff:
            raise FormatError(f"phrase checksum mismatch at 0x{base + number * 4:x}")
        segments = tuple(Segment(*struct.unpack_from("<HBB", submenu, offset))
                         for offset in range(0, len(submenu), 4))
        for segment in segments:
            if (not segment.pages or not segment.repeats or segment.page < 13
                    or (segment.page + segment.pages) * PAGE_SIZE > BANK_SIZE):
                raise FormatError(f"invalid segment in phrase {base // BANK_SIZE}:{number}")
        if sum(s.samples for s in segments) > MAX_PHRASE_SAMPLES:
            raise FormatError("phrase exceeds the 10-minute output limit")
        return Phrase(base // BANK_SIZE, number, base + pointer, checksum, segments)

    def phrases(self, *, strict=True) -> list[Phrase]:
        phrases = []
        self.invalid_phrases = []
        for base in range(0, len(self.data), BANK_SIZE):
            if not any(self.coverage[base:base + 256]):
                continue
            # Entirely zero-filled inactive table regions may also be omitted.
            table = self.read_bytes(base, 256)
            for number in range(64):
                entry = table[number * 4:number * 4 + 4]
                if entry in (b"\xff" * 4, b"\0" * 4):
                    continue
                try:
                    phrases.append(self.parse_phrase(base, number, entry))
                except FormatError as exc:
                    if strict:
                        raise
                    self.invalid_phrases.append({"bank": base // BANK_SIZE, "number": number,
                                                 "raw_entry_hex": entry.hex(), "reason": str(exc)})
        if not phrases:
            raise FormatError("no validated EDRAM phrase tables found")
        return phrases

    def segment_bytes(self, bank: int, segment: Segment):
        start = bank * BANK_SIZE + segment.page * PAGE_SIZE
        size = segment.pages * PAGE_SIZE
        covered = sum(self.coverage[start:start + size])
        # Preserve the archive convention for a wholly unwritten page 16.
        if not covered and segment.page not in (13, 16):
            raise FormatError(f"unavailable segment at 0x{start:x}, {size} bytes")
        data = self.read_bytes(start, size)
        # The native page-fill routine clears stage memory for address 0x0D00.
        if segment.page == 13:
            data = bytes(PAGE_SIZE) + data[PAGE_SIZE:]
        return data, size - covered


def alaw_sample(value: int) -> int:
    """G.711 expansion of stored unmasked code, equivalent to A-law(value ^ 0x55)."""
    sample = ((value & 15) << 4) + 8
    exponent = (value >> 4) & 7
    if exponent:
        sample += 256
    if exponent > 1:
        sample <<= exponent - 1
    return sample if value & 128 else -sample


def mulaw_sample(value: int) -> int:
    """G.711 expansion of stored unmasked code, equivalent to mu-law(value ^ 0x7f)."""
    sample = ((((value & 15) << 3) + 132) << ((value >> 4) & 7)) - 132
    return sample if value & 128 else -sample


def decode(data: bytes, codec="alaw-unmasked") -> bytes:
    table = PCM_TABLES[codec]
    return b"".join(table[value] for value in data)


PCM_TABLES = {
    name: tuple(struct.pack("<h", fun(value)) for value in range(256))
    for name, fun in (("alaw-unmasked", alaw_sample), ("mulaw-unmasked", mulaw_sample))
}


def render_codes(image: Image, phrase: Phrase):
    chunks = []
    implicit = 0
    for segment in phrase.segments:
        data, missing = image.segment_bytes(phrase.bank, segment)
        chunks.append(data * segment.repeats)
        implicit += missing * segment.repeats
    return b"".join(chunks), implicit


def render(image: Image, phrase: Phrase, codec="alaw-unmasked"):
    codes, implicit = render_codes(image, phrase)
    return decode(codes, codec), implicit


def tone_metadata(image, phrase, pcm, codec):
    """Identify known tones for display without changing their PCM."""
    if cue := tone_bank.cue_profile(image, phrase, BANK_SIZE, PAGE_SIZE):
        name, parts = cue
        return {"tone_name": name, "frequencies_hz": [750], "tone_components": parts}
    if codec == "alaw-unmasked" and len(pcm) <= 2 * RATE * 2:
        if recorded := tone_bank.RECORDED_TONES.get(hashlib.sha256(pcm).hexdigest()):
            name, frequencies = recorded
            return {"tone_name": name, "frequencies_hz": list(frequencies)}
    return {}


def chunk(tag: bytes, data: bytes) -> bytes:
    return tag + struct.pack("<I", len(data)) + data + (b"\0" if len(data) % 2 else b"")


def write_wav(path: Path, pcm: bytes, title: str, comment: str):
    info = b"INFO" + chunk(b"INAM", title.encode("ascii", "replace") + b"\0")
    info += chunk(b"ISFT", f"EDRAM converter {VERSION}".encode() + b"\0")
    info += chunk(b"ICMT", comment.encode("ascii", "replace") + b"\0")
    body = b"WAVE" + chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, RATE, RATE * 2, 2, 16))
    body += chunk(b"LIST", info) + chunk(b"data", pcm)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def phrase_name(phrase: Phrase):
    if (8 <= phrase.number <= 39 and len(phrase.segments) >= 6
            and all(s.page in (17, 18, 20, 21, 23, 24, 26, 27, 29, 30) for s in phrase.segments)
            and any(s.page == 29 for s in phrase.segments)):
        return f"phrase_{phrase.number:02d}_sit_{phrase.number - 7:02d}"
    return f"phrase_{phrase.number:02d}"


def check_voice_ranges(bank, segments, tone_ranges):
    for segment in segments:
        start = bank * BANK_SIZE + segment.page * PAGE_SIZE
        if tone_bank.overlaps_records(start, segment.pages * PAGE_SIZE, tone_ranges):
            raise ToneBankOverlap(f"page range at 0x{start:x} overlaps standalone tone records")


def output_folder(path, output, overwrite):
    folder = output / path.stem
    if folder.exists() and any(folder.iterdir()) and not overwrite:
        raise FormatError(f"output already exists: {folder}; use --overwrite explicitly")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def export(path: Path, output: Path, codec: str, segments=False, overwrite=False, *, raw_tones=False):
    image = Image.read(path)
    phrases = image.phrases(strict=False)
    folder = output_folder(path, output, overwrite)
    manifest = {"converter_version": VERSION, "source": path.name,
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "codec": codec, "sample_rate": RATE, "sample_width_bits": 16,
                "playback_model": "stored codes, whole-range repetition and zero-coded page 13",
                "timing_status": "256 addressed samples per page at nominal 8000 Hz",
                "record_count": len(image.records), "addressed_bytes": sum(image.coverage),
                "overwrite_policy": "records applied in file order; later writes replace earlier bytes",
                "overwrites": image.overwrites,
                "invalid_phrases": image.invalid_phrases,
                "zero_fill_policy": "unaddressed portions of referenced segments are zero codes; wholly absent non-silence segments are unavailable",
                "phrases": [], "segments": []}
    standalone = list(tone_bank.records(image))
    tone_ranges = tone_bank.record_ranges(entry for entry, _ in standalone)
    available = {}
    for phrase in phrases:
        entry = asdict(phrase)
        entry["samples"] = sum(s.samples for s in phrase.segments)
        entry["duration_seconds"] = entry["samples"] / RATE
        entry["wav"] = None
        entry["label"] = phrase_name(phrase)
        try:
            pcm, implicit = render(image, phrase, codec)
            check_voice_ranges(phrase.bank, phrase.segments, tone_ranges)
            relative = Path(f"bank_{phrase.bank:02d}") / (phrase_name(phrase) + ".wav")
            write_wav(folder / relative, pcm, f"{path.stem} bank {phrase.bank} phrase {phrase.number}",
                      f"source_sha256={manifest['source_sha256']}; codec={codec}; menu=0x{phrase.menu_address:x}")
            entry.update(tone_metadata(image, phrase, pcm, codec))
            entry.update(wav=relative.as_posix(), implicit_zero_samples=implicit,
                         pcm_sha256=hashlib.sha256(pcm).hexdigest(), status="exported")
        except FormatError as exc:
            entry.update(status="unavailable", reason=str(exc))
        manifest["phrases"].append(entry)
        for segment in phrase.segments:
            available[(phrase.bank, segment.page, segment.pages)] = Segment(segment.page, segment.pages, 1)
    if segments:
        for (bank, page, pages), segment in sorted(available.items()):
            entry = {"bank": bank, "page": page, "pages": pages, "wav": None}
            try:
                data, implicit = image.segment_bytes(bank, segment)
                check_voice_ranges(bank, (segment,), tone_ranges)
                relative = Path("segments") / f"bank_{bank:02d}_page_{page:04x}_pages_{pages:03d}.wav"
                write_wav(folder / relative, decode(data, codec), f"{path.stem} bank {bank} page {page:04x}",
                          f"codec={codec}; repeats=1; implicit_zero_samples={implicit}")
                entry.update(wav=relative.as_posix(), status="exported", implicit_zero_samples=implicit)
            except FormatError as exc:
                entry.update(status="unavailable", reason=str(exc))
            manifest["segments"].append(entry)
    for entry, payload in standalone:
        if raw_tones:
            record = image.read_bytes(entry["header_address"], len(payload) + 2, required=True)
            entry["raw"] = f"tone-bank/tone_{entry['index']:02d}.record.bin"
            target = folder / entry["raw"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(record)
            entry["record_sha256"] = hashlib.sha256(record).hexdigest()
        if entry["wav"]:
            pcm = decode(payload, entry["codec"])
            write_wav(folder / entry["wav"], pcm, entry["tone_name"],
                      f"Stored EDRAM tone bank waveform; codec={entry['codec']}.")
            entry["pcm_sha256"] = hashlib.sha256(pcm).hexdigest()
        manifest.setdefault("tone_bank", []).append(entry)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with (folder / "phrases.csv").open("w", newline="", encoding="utf-8") as file:
        fields = ("bank", "number", "status", "duration_seconds", "samples", "wav", "implicit_zero_samples", "reason")
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(manifest["phrases"])
    return manifest


def parse_firmware_sit(raw: bytes, selector=0x4040):
    if raw.lstrip().startswith(b"S"):
        image = Image(parse_srec(raw), strict_overlaps=True)
        raw = bytes(image.data[firmware_sit.LOAD_ADDRESS:])
    try:
        return firmware_sit.Firmware(raw, selector)
    except ValueError as exc:
        raise FormatError(str(exc)) from exc


class CardPlayback:
    """A load placed in the RAM initialized by the verified firmware startup path."""

    def __init__(self, image, firmware, first_bank=0):
        self.firmware = firmware
        self.first_bank = first_bank
        self.bank_count = (len(image.data) + BANK_SIZE - 1) // BANK_SIZE
        limit = firmware_sit.STARTUP_BANKS
        if not 0 <= first_bank < limit or first_bank + self.bank_count > limit:
            raise FormatError(f"the load must fit within startup-initialized RAM banks 0 to {limit - 1}")

        lo, hi = firmware_sit.PROTECTED_START, firmware_sit.PROTECTED_END
        self.memory = bytearray(limit * BANK_SIZE)
        for bank, protected in enumerate(firmware.protected):
            base = bank * BANK_SIZE
            self.memory[base + lo:base + hi] = protected

        target = first_bank * BANK_SIZE
        high_water = 0
        cleared = set()
        for record in image.records:
            start = record.address
            end = start + len(record.data)
            high_water = max(high_water, end - 1)
            bank = first_bank + high_water // BANK_SIZE
            if bank not in cleared:
                base = bank * BANK_SIZE
                self.memory[base:base + lo] = bytes(lo)
                self.memory[base + hi:base + BANK_SIZE] = bytes(BANK_SIZE - hi)
                cleared.add(bank)
            # The write exclusion is relative to the first bank in the transaction.
            before = min(lo, end)
            after = max(hi, start)
            if start < before:
                self.memory[target + start:target + before] = record.data[:before - start]
            if after < end:
                self.memory[target + after:target + end] = record.data[after - start:]

        if self.memory[target + 0x2A4:target + 0x2A8] == b"UPLD":
            raise FormatError("UPLD playback needs the installed card's RAM-bank routing state")
        start = target + LOAD_HEADER_OFFSET
        self.load_header = bytes(self.memory[start:start + LOAD_HEADER_SIZE])
        header = self.load_header
        suffix = header[4:8]
        self.bank_type = 0
        if header[8:12] == b".bin":
            self.bank_type = int(suffix in (b"0AA ", b"0AB ", b"0BA ", b"S0CA"))
        elif header[:4] in (b"TONE", b"U1X7"):
            self.bank_type = {b"6AA0": 1, b"6AB0": 1, b"6BA0": 1, b"6CA0": 1,
                              b"00AA": 2, b"00AB": 3}.get(suffix, 0)
        self.tone_records = {
            firmware_sit.BANK_BASE + target + entry["header_address"]: (entry, raw)
            for entry, raw in tone_bank.records(image)
        } if self.bank_type > 1 else {}
        # Reuse the voice menu parser with fully addressed RAM bytes.
        self.loaded_image = Image([Record(0, bytes(self.memory), "RAM", 0)])

    def read(self, address, size):
        start = address - firmware_sit.BANK_BASE
        if start < 0 or start + size > len(self.memory):
            raise FormatError(f"address 0x{address:06x} is outside initialized card RAM")
        return bytes(self.memory[start:start + size])

    def waveform(self, address):
        try:
            if address in self.tone_records:
                entry, raw = self.tone_records[address]
                codec = entry["codec"]
            else:
                raw, codec = self.firmware.waveform(address)
        except ValueError as exc:
            raise FormatError(f"no known waveform record at 0x{address:06x}") from exc
        record = (len(raw) // 2).to_bytes(2, "big") + raw
        if self.read(address, len(record)) != record:
            raise FormatError(f"waveform at 0x{address:06x} differs from the known startup or load record")
        return raw, codec

    def slots(self, bank):
        top = (4, 40, 64, 64)[self.bank_type]
        return [slot for slot in range(64)
                if slot < top or self.directory_entry(bank, slot) not in (bytes(4), b"\xff" * 4)]

    def directory_entry(self, bank, slot):
        return self.read(firmware_sit.BANK_BASE + bank * BANK_SIZE + slot * 4, 4)

    def phrase(self, bank, slot, codec="alaw-unmasked"):
        if not self.first_bank <= bank < self.first_bank + self.bank_count or not 0 <= slot < 64:
            raise FormatError("requested slot is outside the loaded banks")
        if slot < 4:
            return self.firmware.cue(slot, read=self.read)
        if self.bank_type > 1 or (self.bank_type == 1 and slot < 40):
            bank_offset = bank * BANK_SIZE if self.bank_type > 1 else 0
            if 8 <= slot < 40:
                return self.firmware.sit(slot - 7, bank_offset=bank_offset, waveform=self.waveform)
            return self.firmware.continuous(slot, bank_offset=bank_offset, waveform=self.waveform)

        offset = bank * BANK_SIZE
        phrase = self.loaded_image.parse_phrase(offset, slot, self.directory_entry(bank, slot))
        base = firmware_sit.BANK_BASE + offset
        ranges = ((base + part.page * PAGE_SIZE, part.pages, part.repeats) for part in phrase.segments)
        return self.firmware.pages(slot, ranges, read=self.read, codec=codec)

    def label(self, tone):
        if isinstance(tone, firmware_sit.SIT):
            return f"Built-in SIT {tone.number:02d}"
        if isinstance(tone, firmware_sit.Continuous):
            entry = self.tone_records.get(tone.components[0].record_address)
            return entry[0]["tone_name"] if entry else firmware_sit.CONTINUOUS_SLOTS.get(
                tone.slot, f"Continuous slot {tone.slot:02d}")
        return firmware_sit.PAGE_SLOTS.get(tone.slot, f"Phrase {tone.slot:02d}")


def render_firmware_tone(tone, codec=None):
    return b"".join(decode(codes, codec or law) for codes, law in firmware_sit.coded_chunks(tone))


def firmware_tone_entry(tone, firmware, label, title, folder, codec):
    codes = tone.codes
    loop = isinstance(tone, firmware_sit.Continuous)
    raw = tone.record_bytes if loop else codes.ljust(len(codes) + (-len(codes) % PAGE_SIZE), b"\0")
    pcm = render_firmware_tone(tone, codec)
    entry = {"slot": tone.slot, "label": title, "samples": len(codes),
             "active_sha256": hashlib.sha256(codes).hexdigest(),
             "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
             "components": [asdict(part) for part in tone.components]}
    if loop:
        entry.update(continuous=True, preview_seconds=len(codes) / RATE,
                     record_sha256=hashlib.sha256(raw).hexdigest())
    else:
        entry.update(duration_seconds=len(codes) / RATE, staged_samples=len(raw),
                     staged_sha256=hashlib.sha256(raw).hexdigest())
    if folder is not None:
        entry.update(wav=f"{label}.wav", raw=f"{label}.{'record' if loop else 'staged'}.bin")
        write_wav(folder / entry["wav"], pcm, f"{firmware.name} {title}",
                  f"selector=0x{firmware.selector:04x}; WAV law={codec or 'per component'}")
        (folder / entry["raw"]).write_bytes(raw)
    return entry


def export_firmware_sit(path, output, codec=None, selector=0x4040, *, inspect=False, overwrite=False):
    source = path.read_bytes()
    firmware = parse_firmware_sit(source, selector)
    folder = None if inspect else output_folder(path, output, overwrite)
    sits = []
    for number in range(1, 33):
        entry = firmware_tone_entry(firmware.sit(number), firmware, f"sit_{number:02d}",
                                    f"Built-in SIT {number:02d}", folder, codec)
        entry["number"] = number
        sits.append(entry)
    cues = [
        firmware_tone_entry(firmware.cue(slot), firmware, f"cue_{slot:02d}",
                            title, folder, codec)
        for slot, title in firmware_sit.CUES.items()
    ]
    continuous = [firmware_tone_entry(firmware.continuous(slot), firmware, f"loop_{slot:02d}",
                                      title, folder, codec)
                  for slot, title in firmware_sit.CONTINUOUS_SLOTS.items()]
    manifest = {
        "converter_version": VERSION, "source": path.name, "firmware": firmware.name,
        "source_sha256": hashlib.sha256(source).hexdigest(), "flat_sha256": firmware.sha256,
        "selector": selector, "low_memory_byte": firmware_sit.LOW_MEMORY_BYTE,
        "preview_codec": codec or "per-component", "sample_rate": RATE,
        "firmware_sits": sits, "firmware_cues": cues, "firmware_continuous": continuous,
        "startup_copies": [asdict(copy) for copy in firmware.startup_copies],
    }
    if folder is not None:
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def export_card_playback(path, output, firmware, first_bank=0, slots=None, codec="alaw-unmasked",
                         *, inspect=False, overwrite=False):
    source = path.read_bytes()
    parse = parse_bin44 if source[:1] == b"G" else parse_srec
    playback = CardPlayback(Image(parse(source)), firmware, first_bank)
    folder = None if inspect else output_folder(path, output, overwrite)
    entries = []
    for bank in range(first_bank, first_bank + playback.bank_count):
        for slot in slots or playback.slots(bank):
            try:
                tone = playback.phrase(bank, slot, codec)
            except ValueError as exc:
                entries.append({"bank": bank, "slot": slot, "status": "unavailable", "reason": str(exc)})
                continue
            entry = firmware_tone_entry(tone, firmware, f"bank_{bank:02d}_slot_{slot:02d}",
                                        playback.label(tone), folder, None)
            entries.append({"bank": bank, "status": "exported", **entry})
    manifest = {"converter_version": VERSION, "source": path.name, "firmware": firmware.name,
                "source_sha256": hashlib.sha256(source).hexdigest(), "flat_sha256": firmware.sha256,
                "selector": firmware.selector, "first_bank": first_bank, "bank_type": playback.bank_type,
                "load_header": {"offset": LOAD_HEADER_OFFSET, "hex": playback.load_header.hex(),
                                "ascii": playback.load_header.decode("ascii", errors="backslashreplace")},
                "low_memory_byte": firmware_sit.LOW_MEMORY_BYTE, "sample_rate": RATE,
                "startup_copies": [asdict(copy) for copy in firmware.startup_copies],
                "card_slots": entries}
    if folder is not None:
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def write_browser(output: Path, manifests):
    rows = []
    for manifest in manifests:
        source = manifest["source"]
        if "firmware" in manifest:
            tones = manifest.get("card_slots", [*manifest.get("firmware_cues", ()),
                                 *manifest.get("firmware_continuous", ()), *manifest.get("firmware_sits", ())])
            for tone in tones:
                if "wav" not in tone:
                    continue
                name = f'{manifest["firmware"]} / 0x{manifest["selector"]:04x} / {tone["label"]}'
                if "bank" in tone:
                    name = f'{source} / RAM bank {tone["bank"]} / slot {tone["slot"]:02d} / {name}'
                folder = Path(Path(source).stem)
                url = html.escape((folder / tone["wav"]).as_posix(), quote=True)
                raw_url = html.escape((folder / tone["raw"]).as_posix(), quote=True)
                loop = tone.get("continuous", False)
                timing = "Continuous" if loop else f'{tone["duration_seconds"]:.3f}s'
                button = "Loop" if loop else "Play"
                raw_label = "Native record" if loop else "Staged codes"
                rows.append(f'<tr><td>{html.escape(name)}</td><td>{timing}</td>'
                            f'<td><button data-src="{url}" data-loop="{str(loop).lower()}">{button}</button> '
                            f'<a href="{url}" download>WAV</a> <a href="{raw_url}" download>{raw_label}</a></td></tr>')
            continue
        raw_paths = tone_bank.raw_bank_paths(manifest, BANK_SIZE, PAGE_SIZE)
        for phrase in manifest["phrases"]:
            if not phrase["wav"]:
                continue
            url = (Path(Path(source).stem) / phrase["wav"]).as_posix()
            if url in raw_paths:
                continue
            name = f"{source} / bank {phrase['bank']} / {phrase['label']}"
            if phrase.get("tone_name"):
                name += f' / {phrase["tone_name"]}'
            rows.append(f'<tr><td>{html.escape(name)}</td><td>{phrase["duration_seconds"]:.3f}s</td>'
                        f'<td><button data-src="{html.escape(url, quote=True)}">Play stored audio</button> '
                        f'<a href="{html.escape(url, quote=True)}" download>WAV</a></td></tr>')
        for clip in tone_bank.bank_clips(manifest):
            name = f"{source} / tone bank / {clip['label']} / {clip['tone_name']}"
            url = html.escape(clip["path"], quote=True)
            rows.append(f'<tr><td>{html.escape(name)}</td><td>{clip["seconds"]:.4f}s</td>'
                        f'<td><button data-src="{url}">Play</button> <a href="{url}" download>WAV</a></td></tr>')
    firmware_only = bool(manifests) and all("firmware" in m for m in manifests)
    title = "Nortel EDRAM card playback" if firmware_only else "EDRAM announcement archive"
    description = ("8 kHz PCM from card RAM. Continuous WAVs contain one native waveform record."
                   if firmware_only else
                   "8 kHz, 16-bit mono PCM. WAVs expand the stored sample bytes at the addressed locations. IDs are bank-local.")
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>PAGE_TITLE</title><style>
body{max-width:1100px;margin:2rem auto;padding:0 1rem;font:16px system-ui;background:#101820;color:#edf4f9}
a{color:#7ad8ff} input{font:inherit;padding:.6rem;width:95%} table{width:100%;border-collapse:collapse}
td{padding:.55rem;border-bottom:1px solid #334452} button{padding:.35rem 1rem;cursor:pointer}
header{position:sticky;top:0;background:#101820;padding:1rem 0} audio{width:100%;margin:1rem 0}
</style><header><h1>PAGE_TITLE</h1>
<p>PAGE_DESCRIPTION</p>
<input id="filter" aria-label="Filter recordings" placeholder="Filter by source, tone name or phrase ID">
<audio id="player" controls></audio><div id="playing">Select a recording</div></header>
<table><tbody>ROWS</tbody></table><script>
const p=document.querySelector('#player');
document.addEventListener('click',e=>{if(e.target.dataset.src){p.loop=e.target.dataset.loop==='true';p.src=e.target.dataset.src;p.play();document.querySelector('#playing').textContent=e.target.closest('tr').cells[0].textContent;}});
document.querySelector('#filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));});
</script></html>'''
    document = (document.replace("PAGE_TITLE", title).replace("PAGE_DESCRIPTION", description)
                .replace("ROWS", "\n".join(rows)))
    (output / "listen.html").write_text(document, encoding="utf-8")


def input_paths(inputs, *, firmware=False):
    suffixes = (".bin", ".srec", ".s19", ".s28") if firmware else (".bin44", ".txt80", ".srec", ".s19", ".s28")
    paths = []
    for value in inputs:
        path = Path(value)
        if path.is_dir():
            paths.extend(p for p in sorted(path.iterdir()) if p.suffix.lower() in suffixes)
        else:
            paths.append(path)
    paths = list(dict.fromkeys(p.resolve() for p in paths))
    stems = [p.stem.lower() for p in paths]
    if len(stems) != len(set(stems)):
        raise FormatError("input basenames collide; extract these inputs separately")
    if not paths:
        raise FormatError("no input files found")
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="bin44/S-record files or directories")
    parser.add_argument("-o", "--output", type=Path, default=Path("edram-wav"))
    parser.add_argument("--inspect", action="store_true", help="list resolved slots or file tables without writing files")
    parser.add_argument("--codec", choices=tuple(PCM_TABLES),
                        help="override the WAV law (A-law for announcements, per waveform for firmware by default)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--firmware-sit", "--firmware-tones", action="store_true",
                      help="decode built-in cues, SITs and continuous tones from firmware images")
    mode.add_argument("--card-playback", type=Path, metavar="FIRMWARE",
                      help="override the firmware for card playback (default: bundled ED16AA07)")
    mode.add_argument("--as-stored", action="store_true",
                      help="decode addressed bytes and menus directly from the load file")
    parser.add_argument("--first-bank", type=int, help="zero-based RAM bank for the load (default: 0)")
    parser.add_argument("--slot", type=int, action="append", metavar="0..63",
                        help="restrict card playback to a slot, repeatable")
    parser.add_argument("--sit-selector", "--playback-selector", type=lambda value: int(value, 0),
                        choices=firmware_sit.SELECTORS,
                        metavar="{0x4040,0x5050}", help="firmware playback selector (default: 0x4040)")
    parser.add_argument("--raw-tones", "--raw-sit", action="store_true",
                        help="export all standalone waveform records as stored in the file")
    parser.add_argument("--segments", action="store_true", help="export the file as stored, including each segment without repeats")
    parser.add_argument("--overwrite", action="store_true", help="allow replacing outputs in existing source folders")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    archive_options = args.segments or args.raw_tones
    as_stored = args.as_stored or (archive_options and not (args.card_playback or args.firmware_sit))
    card_playback = not (as_stored or args.firmware_sit)
    if args.sit_selector is not None and as_stored:
        parser.error("--playback-selector requires firmware or card playback")
    if (args.first_bank is not None or args.slot) and not card_playback:
        parser.error("--first-bank and --slot require card playback")
    if args.slot and any(not 0 <= slot < 64 for slot in args.slot):
        parser.error("--slot must be between 0 and 63")
    if args.segments and not as_stored:
        parser.error("--segments is for file-only announcement exports")
    try:
        paths = input_paths(args.inputs, firmware=args.firmware_sit)
        if args.firmware_sit:
            manifests = [export_firmware_sit(path, args.output, args.codec, args.sit_selector or 0x4040,
                                             inspect=args.inspect, overwrite=args.overwrite) for path in paths]
            if args.inspect:
                for manifest in manifests:
                    print(json.dumps(manifest))
            else:
                write_browser(args.output, manifests)
                for manifest in manifests:
                    print(f"{manifest['source']}: {len(manifest['firmware_sits'])} SITs, "
                          f"{len(manifest['firmware_cues'])} cues and "
                          f"{len(manifest['firmware_continuous'])} continuous tones exported")
            return
        codec = args.codec or "alaw-unmasked"
        if card_playback:
            firmware_path = args.card_playback or DEFAULT_FIRMWARE
            firmware = parse_firmware_sit(firmware_path.read_bytes(), args.sit_selector or 0x4040)
            slots = sorted(set(args.slot)) if args.slot else None
            manifests = [export_card_playback(path, args.output, firmware, args.first_bank or 0, slots, codec,
                                              inspect=args.inspect, overwrite=args.overwrite) for path in paths]
            if args.inspect:
                for manifest in manifests:
                    print(json.dumps(manifest))
            else:
                write_browser(args.output, manifests)
                for manifest in manifests:
                    available = sum(s["status"] == "exported" for s in manifest["card_slots"])
                    print(f"{manifest['source']}: {available}/{len(manifest['card_slots'])} card slots exported")
            return
        manifests = []
        for path in paths:
            if args.inspect:
                image = Image.read(path)
                phrases = image.phrases(strict=False)
                print(json.dumps({"source": path.name, "records": len(image.records), "phrases": [asdict(p) for p in phrases],
                                  "invalid_phrases": image.invalid_phrases,
                                  "tone_bank": [entry for entry, _ in tone_bank.records(image)]}))
            else:
                manifest = export(path, args.output, codec, args.segments, args.overwrite, raw_tones=args.raw_tones)
                manifests.append(manifest)
                count = sum(p["status"] == "exported" for p in manifest["phrases"])
                print(f"{path.name}: {count}/{len(manifest['phrases'])} phrases exported")
        if not args.inspect:
            write_browser(args.output, manifests)
            summary = {"sources": len(manifests), "phrases": sum(len(m["phrases"]) for m in manifests),
                       "exported": sum(p["status"] == "exported" for m in manifests for p in m["phrases"]),
                       "unavailable": sum(p["status"] == "unavailable" for m in manifests for p in m["phrases"]),
                       "invalid_menu_entries": sum(len(m["invalid_phrases"]) for m in manifests),
                       "tone_bank_wavs": sum(bool(t["wav"]) for m in manifests for t in m.get("tone_bank", []))}
            (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(summary))
    except (FormatError, OSError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
