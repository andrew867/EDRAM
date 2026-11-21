#!/usr/bin/env python3
"""Extract Nortel EDRAM phrases from addressed bin44 and Motorola S-record files."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import struct
from sit_reference import archived_profile, synthesize
import tone_bank

VERSION = "0.1.0"
RATE = 8000
BANK_SIZE = 0x40000
PAGE_SIZE = 256
MAX_IMAGE = 16 * 1024 * 1024
MAX_PHRASE_SAMPLES = RATE * 600


class FormatError(ValueError):
    """An invalid container, table, or reference."""


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
        # Sparse zero regions are common. Entirely missing speech is not silence.
        if not covered and segment.page not in (13, 16):
            raise FormatError(f"unavailable segment at 0x{start:x}, {size} bytes")
        return self.read_bytes(start, size), size - covered


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
    """Diagnostic alternative, equivalent to mu-law(value ^ 0x7f)."""
    sample = ((((value & 15) << 3) + 132) << ((value >> 4) & 7)) - 132
    return sample if value & 128 else -sample


def decode(data: bytes, codec="alaw-unmasked") -> bytes:
    table = PCM_TABLES[codec]
    return b"".join(table[value] for value in data)


PCM_TABLES = {
    name: tuple(struct.pack("<h", fun(value)) for value in range(256))
    for name, fun in (("alaw-unmasked", alaw_sample), ("mulaw-unmasked", mulaw_sample))
}


def render(image: Image, phrase: Phrase, codec="alaw-unmasked"):
    chunks = []
    implicit = 0
    for segment in phrase.segments:
        data, missing = image.segment_bytes(phrase.bank, segment)
        chunks.append(decode(data, codec) * segment.repeats)
        implicit += missing * segment.repeats
    return b"".join(chunks), implicit


def render_export(image, phrase, codec, source_hash, *, raw_sit=False, raw_cues=False):
    pcm, implicit = render(image, phrase, codec)
    if not raw_sit and "_sit_" in phrase_name(phrase):
        try:
            parts, profile_source = archived_profile((asdict(s) for s in phrase.segments),
                                                     source_hash=source_hash, bank=phrase.bank, phrase=phrase.number)
        except ValueError:
            pass
        else:
            info = {"rendering": "nortel-sit", "sit_components": parts, "sit_profile_source": profile_source,
                    "menu_samples": len(pcm) // 2, "source_pcm_sha256": hashlib.sha256(pcm).hexdigest()}
            return synthesize(parts, rate=RATE), implicit, info
    if cue := tone_bank.cue_profile(image, phrase, BANK_SIZE, PAGE_SIZE):
        name, parts = cue
        info = {"tone_name": name, "frequencies_hz": [750], "tone_components": parts}
        if not raw_cues:
            info.update(rendering="nortel-cue", menu_samples=len(pcm) // 2,
                        source_pcm_sha256=hashlib.sha256(pcm).hexdigest())
            return synthesize(parts, rate=RATE), implicit, info
        return pcm, implicit, info
    if codec == "alaw-unmasked" and len(pcm) <= 2 * RATE * 2:
        digest = hashlib.sha256(pcm).hexdigest()
        if recorded := tone_bank.RECORDED_TONES.get(digest):
            name, frequencies = recorded
            info = {"tone_name": name, "frequencies_hz": list(frequencies)}
            if not raw_cues and (lead := tone_bank.RECORDED_LEAD_REPAIRS.get(digest)):
                info.update(rendering="repaired-tone", source_pcm_sha256=digest, silenced_lead_samples=lead)
                pcm = bytes(2 * lead) + pcm[2 * lead:]
            return pcm, implicit, info
    return pcm, implicit, {}


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


def export(path: Path, output: Path, codec: str, segments=False, overwrite=False, *, raw_sit=False, raw_tones=False):
    image = Image.read(path)
    phrases = image.phrases(strict=False)
    folder = output / path.stem
    if folder.exists() and any(folder.iterdir()) and not overwrite:
        raise FormatError(f"output already exists: {folder}; use --overwrite explicitly")
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"converter_version": VERSION, "source": path.name,
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "codec": codec, "sample_rate": RATE, "sample_width_bits": 16,
                "codec_status": "legacy-compatible A-law expansion; hardware equivalence unverified",
                "timing_status": "256 addressed samples per page at nominal 8000 Hz",
                "record_count": len(image.records), "addressed_bytes": sum(image.coverage),
                "overwrite_policy": "records applied in file order; later writes replace earlier bytes",
                "overwrites": image.overwrites,
                "invalid_phrases": image.invalid_phrases,
                "zero_fill_policy": "unaddressed portions of referenced segments are zero codes; wholly absent non-silence segments are unavailable",
                "phrases": [], "segments": []}
    available = {}
    for phrase in phrases:
        entry = asdict(phrase)
        entry["samples"] = sum(s.samples for s in phrase.segments)
        entry["duration_seconds"] = entry["samples"] / RATE
        entry["wav"] = None
        entry["label"] = phrase_name(phrase)
        try:
            pcm, implicit, tone = render_export(image, phrase, codec, manifest["source_sha256"],
                                                raw_sit=raw_sit or raw_tones, raw_cues=raw_tones)
            relative = Path(f"bank_{phrase.bank:02d}") / (phrase_name(phrase) + ".wav")
            rendering = tone.get("rendering")
            if rendering == "nortel-sit":
                manifest["sit_rendering"] = "nortel-sit"
                write_wav(folder / relative, pcm, f"Nortel EDRAM SIT {phrase.number - 7}",
                          "Sine synthesis from Nortel 297-1001-527 Table 4-2; 274/380 ms; peak PCM 5000.")
            elif rendering == "nortel-cue":
                manifest["cue_rendering"] = "nortel-cue"
                write_wav(folder / relative, pcm, tone["tone_name"],
                          "Measured 750 Hz; cadence from source phrase menu; peak PCM 5000.")
            elif rendering == "repaired-tone":
                manifest["cue_rendering"] = "nortel-cue"
                write_wav(folder / relative, pcm, tone["tone_name"],
                          f"Stored tone with {tone['silenced_lead_samples']} lead-in samples silenced.")
            else:
                write_wav(folder / relative, pcm, f"{path.stem} bank {phrase.bank} phrase {phrase.number}",
                          f"source_sha256={manifest['source_sha256']}; codec={codec}; menu=0x{phrase.menu_address:x}")
            entry.update(tone, samples=len(pcm) // 2, duration_seconds=len(pcm) / (2 * RATE))
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
                relative = Path("segments") / f"bank_{bank:02d}_page_{page:04x}_pages_{pages:03d}.wav"
                write_wav(folder / relative, decode(data, codec), f"{path.stem} bank {bank} page {page:04x}",
                          f"codec={codec}; repeats=1; implicit_zero_samples={implicit}")
                entry.update(wav=relative.as_posix(), status="exported", implicit_zero_samples=implicit)
            except FormatError as exc:
                entry.update(status="unavailable", reason=str(exc))
            manifest["segments"].append(entry)
    for entry, payload in tone_bank.records(image):
        if entry["wav"]:
            if not raw_tones:
                payload = tone_bank.repair_samples(entry, payload)
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


def write_browser(output: Path, manifests):
    rows = []
    for manifest in manifests:
        source = manifest["source"]
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
            play = "Play Nortel SIT" if phrase.get("rendering") == "nortel-sit" else "Play"
            rows.append(f'<tr><td>{html.escape(name)}</td><td>{phrase["duration_seconds"]:.3f}s</td>'
                        f'<td><button data-src="{html.escape(url, quote=True)}">{play}</button> '
                        f'<a href="{html.escape(url, quote=True)}" download>WAV</a></td></tr>')
        for clip in tone_bank.bank_clips(manifest):
            name = f"{source} / tone bank / {clip['label']} / {clip['tone_name']}"
            url = html.escape(clip["path"], quote=True)
            rows.append(f'<tr><td>{html.escape(name)}</td><td>{clip["seconds"]:.4f}s</td>'
                        f'<td><button data-src="{url}">Play</button> <a href="{url}" download>WAV</a></td></tr>')
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>EDRAM announcement archive</title><style>
body{max-width:1100px;margin:2rem auto;padding:0 1rem;font:16px system-ui;background:#101820;color:#edf4f9}
a{color:#7ad8ff} input{font:inherit;padding:.6rem;width:95%} table{width:100%;border-collapse:collapse}
td{padding:.55rem;border-bottom:1px solid #334452} button{padding:.35rem 1rem;cursor:pointer}
header{position:sticky;top:0;background:#101820;padding:1rem 0} audio{width:100%;margin:1rem 0}
</style><header><h1>EDRAM announcement archive</h1>
<p>8 kHz, 16-bit mono PCM. Recognized SITs use Nortel's EDRAM frequencies and timing. IDs are bank-local.</p>
<input id="filter" aria-label="Filter recordings" placeholder="Filter by source, tone name or phrase ID">
<audio id="player" controls></audio><div id="playing">Select an announcement</div></header>
<table><tbody>ROWS</tbody></table><script>
const p=document.querySelector('#player');
document.addEventListener('click',e=>{if(e.target.dataset.src){p.src=e.target.dataset.src;p.play();document.querySelector('#playing').textContent=e.target.closest('tr').cells[0].textContent;}});
document.querySelector('#filter').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));});
</script></html>'''.replace("ROWS", "\n".join(rows))
    (output / "listen.html").write_text(document, encoding="utf-8")


def input_paths(inputs):
    paths = []
    for value in inputs:
        path = Path(value)
        if path.is_dir():
            paths.extend(p for p in sorted(path.iterdir()) if p.suffix.lower() in (".bin44", ".txt80", ".srec", ".s19", ".s28"))
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
    parser.add_argument("--inspect", action="store_true", help="validate and list tables without writing files")
    parser.add_argument("--codec", choices=tuple(PCM_TABLES), default="alaw-unmasked")
    parser.add_argument("--raw-sit", action="store_true", help="expand SIT sample bytes with the selected codec")
    parser.add_argument("--raw-tones", action="store_true", help="expand phrase tone bytes without sine synthesis")
    parser.add_argument("--segments", action="store_true", help="also export each referenced segment without repeats")
    parser.add_argument("--overwrite", action="store_true", help="allow replacing outputs in existing source folders")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    try:
        paths = input_paths(args.inputs)
        manifests = []
        for path in paths:
            if args.inspect:
                image = Image.read(path)
                phrases = image.phrases(strict=False)
                print(json.dumps({"source": path.name, "records": len(image.records), "phrases": [asdict(p) for p in phrases],
                                  "invalid_phrases": image.invalid_phrases,
                                  "tone_bank": [entry for entry, _ in tone_bank.records(image)]}))
            else:
                manifest = export(path, args.output, args.codec, args.segments, args.overwrite,
                                  raw_sit=args.raw_sit, raw_tones=args.raw_tones)
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
