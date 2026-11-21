#!/usr/bin/env python3
"""Inspect and edit the 512-byte Nortel SLM tape images in the reference archive."""

import argparse
from collections.abc import Iterator
from dataclasses import dataclass
import lzma
from pathlib import Path
import re
import struct

import edram
from encode_edram import word_checksum


BLOCK = 512
FRAME = BLOCK + 8
BLOCK_WORD = struct.pack("<I", BLOCK)
MARK = bytes(4)
EOM = b"\xff" * 4
BATCH = 2048


class TapeError(ValueError):
    """Invalid or unsupported SLM tape structure."""


@dataclass(frozen=True)
class Entry:
    name: str
    ordinal: int
    size: int
    blocks: int
    record_size: int
    records: int
    file_code: int
    overhead: int
    data_offset: int
    header: bytes
    trailer: bytes


@dataclass(frozen=True)
class Tape:
    volume: str
    entries: tuple[Entry, ...]
    append_offset: int
    ending: bytes

    def find(self, name):
        matches = [entry for entry in self.entries if entry.name.upper() == name.upper()]
        if len(matches) != 1:
            raise TapeError(f"expected one entry named {name}, found {len(matches)}")
        return matches[0]


def open_image(path):
    return lzma.open(path, "rb") if path.suffix.lower() == ".xz" else path.open("rb")


def read_exact(stream, size):
    offset = stream.tell()
    data = stream.read(size)
    if len(data) != size:
        raise TapeError(f"truncated image at byte {offset}")
    return data


def swap_words(data):
    swapped = bytearray(len(data))
    swapped[::2] = data[1::2]
    swapped[1::2] = data[::2]
    return swapped


def checksum(label):
    return sum(word for word, in struct.iter_unpack(">H", label[:-2])) & 0xffff


def ascii_field(raw):
    decoded = swap_words(raw).decode("ascii").rstrip(" ")
    if not decoded or not decoded.isprintable():
        raise TapeError("empty or invalid SLM label text")
    return decoded


def read_label(stream, leader, kind):
    offset = stream.tell() - 4
    if leader != BLOCK_WORD:
        raise TapeError(f"expected {kind} length word at byte {offset}, got {leader.hex()}")
    label = read_exact(stream, BLOCK)
    if read_exact(stream, 8) != BLOCK_WORD + MARK:
        raise TapeError(f"invalid {kind} frame or following filemark at byte {offset}")
    if label[:2] != b"\x00\x01" or ascii_field(label[2:6]) != kind:
        raise TapeError(f"expected SLM {kind} at byte {offset}")
    if checksum(label) != struct.unpack_from(">H", label, 510)[0]:
        raise TapeError(f"invalid {kind} checksum at byte {offset}")
    return label


def read_batches(stream, blocks) -> Iterator[bytes]:
    for start in range(0, blocks, BATCH):
        count = min(BATCH, blocks - start)
        frames = read_exact(stream, count * FRAME)
        for offset in range(0, len(frames), FRAME):
            if frames[offset:offset + 4] != BLOCK_WORD or frames[offset + 516:offset + FRAME] != BLOCK_WORD:
                raise TapeError(f"invalid data frame at byte {stream.tell() - len(frames) + offset}")
        yield frames


def expect_mark(stream):
    if read_exact(stream, 4) != MARK:
        raise TapeError(f"missing data filemark at byte {stream.tell() - 4}")


def scan(stream):
    vol = read_label(stream, read_exact(stream, 4), "VOL1")
    entries = []
    while True:
        offset = stream.tell()
        leader = stream.read(4)
        if leader in (MARK, EOM):
            ending = bytearray()
            while leader == MARK:
                ending.extend(leader)
                leader = stream.read(4)
            if leader == EOM:
                ending.extend(leader)
                leader = stream.read(1)
            if leader:
                raise TapeError(f"data after end of tape at byte {offset}")
            return Tape(ascii_field(vol[6:38]), tuple(entries), offset, bytes(ending))
        header = read_label(stream, leader, "HDR1")
        name = ascii_field(header[8:40])
        ordinal = struct.unpack_from(">H", header, 6)[0]
        size, blocks, block_size, file_code = struct.unpack_from(">IIHH", header, 86)
        if ascii_field(header[164:168]) != "LFS0":
            raise TapeError(f"unsupported file metadata for {name}")
        record_size, _, overhead, _, _, stride, records = struct.unpack_from(">6HI", header, 168)
        if (block_size != BLOCK or size <= 0 or blocks != (size + BLOCK - 1) // BLOCK
                or record_size <= 0 or size != record_size * records or stride != record_size + overhead):
            raise TapeError(f"inconsistent length fields for {name}")
        data_offset = stream.tell()
        for _ in read_batches(stream, blocks):
            pass
        expect_mark(stream)
        trailer = read_label(stream, read_exact(stream, 4), "EOF1")
        used = struct.unpack_from(">H", trailer, 184)[0]
        if (header[6:40] != trailer[6:40] or header[86:184] != trailer[86:184]
                or used != size % BLOCK):
            raise TapeError(f"header and trailer disagree for {name}")
        entries.append(Entry(name, ordinal, size, blocks, record_size, records, file_code, overhead,
                             data_offset, header, trailer))


def inventory(path):
    with open_image(path) as stream:
        return scan(stream)


def extract(image, entry, output, raw_words=False):
    with open_image(image) as source, output.open("xb") as target:
        try:
            source.seek(entry.data_offset)
            remaining = entry.size
            for frames in read_batches(source, entry.blocks):
                for offset in range(0, len(frames), FRAME):
                    block = frames[offset + 4:offset + 516]
                    count = min(remaining, BLOCK)
                    target.write((block if raw_words else swap_words(block))[:count])
                    remaining -= count
            expect_mark(source)
        except BaseException:
            target.close()
            output.unlink()
            raise


def write_label(target, label):
    target.write(BLOCK_WORD + label + BLOCK_WORD + MARK)


def number_label(label, ordinal):
    result = bytearray(label)
    struct.pack_into(">H", result, 6, ordinal)
    struct.pack_into(">H", result, 510, checksum(result))
    return result


def copy_bytes(source, target, size):
    for offset in range(0, size, 1024 * 1024):
        target.write(read_exact(source, min(1024 * 1024, size - offset)))


def write_image(base_path, tape, output, names, write_entries, standalone=False):
    if output.suffix.lower() != ".tap":
        raise TapeError("output must be an uncompressed .tap file")
    entries = () if standalone else tape.entries
    used = {entry.name.upper() for entry in entries}
    if len({name.upper() for name in names}) != len(names) or used.intersection(name.upper() for name in names):
        raise TapeError("duplicate tape file name")
    ordinal = max((entry.ordinal for entry in entries), default=0) + 1
    if ordinal + len(names) - 1 > 65535:
        raise TapeError("tape file ordinal exceeds 65535")
    with open_image(base_path) as source, output.open("xb") as target:
        try:
            copy_bytes(source, target, FRAME + 4 if standalone else tape.append_offset)
            write_entries(target, ordinal)
            target.write(tape.ending)
            target.flush()
            verified = inventory(output)
            if (verified.volume != tape.volume or verified.ending != tape.ending
                    or tuple(e.name for e in verified.entries) != (*(e.name for e in entries), *names)):
                raise TapeError("output image verification failed")
        except BaseException:
            target.close()
            output.unlink()
            raise


def append(base, output, donor, names):
    inventory_base = inventory(base)
    inventory_donor = inventory(donor)
    entries = [inventory_donor.find(name) for name in names]

    def write_entries(target, ordinal):
        with open_image(donor) as source:
            for entry in entries:
                write_label(target, number_label(entry.header, ordinal))
                source.seek(entry.data_offset)
                for frames in read_batches(source, entry.blocks):
                    target.write(frames)
                expect_mark(source)
                target.write(MARK)
                write_label(target, number_label(entry.trailer, ordinal))
                ordinal += 1

    write_image(base, inventory_base, output, [entry.name for entry in entries], write_entries)


def voice_label(template, name, ordinal, size, eof=False):
    label = bytearray(template)
    label[8:40] = swap_words(name.ljust(32).encode("ascii"))
    struct.pack_into(">II", label, 86, size, (size + BLOCK - 1) // BLOCK)
    overhead = struct.unpack_from(">H", label, 172)[0]
    struct.pack_into(">H", label, 168, 44)
    struct.pack_into(">HI", label, 178, 44 + overhead, size // 44)
    struct.pack_into(">H", label, 184, size % BLOCK if eof else 0)
    return number_label(label, ordinal)


def add_bin44(base, voice, output, name, template_name, *, template_image=None, standalone=False, raw_words=False):
    if not re.fullmatch(r"[A-Z0-9_]{1,8}", name):
        raise TapeError("voice load name must contain one to eight uppercase letters, digits or underscores")
    blob = voice.read_bytes()
    records = edram.parse_bin44(blob)
    if blob[-42] != 1 or any(len(record.data) % 2 for record in records):
        raise TapeError("expected a bin44 word checksum and even-sized data payloads")
    expected = struct.unpack_from(">I", blob, len(blob) - 41)[0]
    if word_checksum(record.data for record in records) != expected:
        raise TapeError("invalid bin44 aggregate checksum")
    tape = inventory(base)
    template_tape = inventory(template_image) if template_image is not None else tape
    template = template_tape.find(template_name)

    def write_entry(target, ordinal):
        write_label(target, voice_label(template.header, name, ordinal, len(blob)))
        for offset in range(0, len(blob), BLOCK):
            data = blob[offset:offset + BLOCK].ljust(BLOCK, b"\0")
            target.write(BLOCK_WORD + (data if raw_words else swap_words(data)) + BLOCK_WORD)
        target.write(MARK)
        write_label(target, voice_label(template.trailer, name, ordinal, len(blob), eof=True))

    write_image(base, tape, output, [name], write_entry, standalone)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="verify all labels and print the tape directory")
    listing.add_argument("image", type=Path)
    unpack = sub.add_parser("extract", help="extract a file using its declared byte count")
    unpack.add_argument("image", type=Path)
    unpack.add_argument("name")
    unpack.add_argument("output", type=Path)
    unpack.add_argument("--raw-words", action="store_true", help="preserve the on-tape byte order")
    copying = sub.add_parser("append", help="copy existing entries and their metadata from another SLM image")
    copying.add_argument("image", type=Path)
    copying.add_argument("output", type=Path)
    copying.add_argument("--from", dest="donor", required=True, type=Path)
    copying.add_argument("--file", dest="names", required=True, action="append")
    packing = sub.add_parser("add-bin44", help="build an experimental 44-byte logical-record voice file")
    packing.add_argument("image", type=Path)
    packing.add_argument("voice", type=Path)
    packing.add_argument("output", type=Path)
    packing.add_argument("--name", help="DMS file name, defaulting to the uppercase input stem")
    packing.add_argument("--template", required=True, help="entry whose remaining file metadata is reused")
    packing.add_argument("--template-image", type=Path, help="read the template entry from a different image")
    packing.add_argument("--standalone", action="store_true", help="start from only the base volume label")
    packing.add_argument("--raw-words", action="store_true", help="store input bytes unchanged instead of swapping word bytes")
    args = parser.parse_args()
    try:
        if args.command == "list":
            tape = inventory(args.image)
            print(f"Volume {tape.volume}, {len(tape.entries)} files")
            print(f"{'File':32s} {'#':>5s} {'Bytes':>10s} {'Blocks':>8s} {'LRECL':>5s} {'Records':>8s} {'Code':>6s}")
            for entry in tape.entries:
                print(f"{entry.name:32s} {entry.ordinal:5d} {entry.size:10d} {entry.blocks:8d} "
                      f"{entry.record_size:5d} {entry.records:8d} 0x{entry.file_code:04x}")
        elif args.command == "extract":
            entry = inventory(args.image).find(args.name)
            extract(args.image, entry, args.output, args.raw_words)
            print(f"Extracted {entry.name}, {entry.size} bytes")
        elif args.command == "append":
            append(args.image, args.output, args.donor, args.names)
            print(f"Wrote {args.output} with {len(args.names)} appended entries")
        else:
            add_bin44(args.image, args.voice, args.output, args.name or args.voice.stem.upper(),
                      args.template, template_image=args.template_image, standalone=args.standalone,
                      raw_words=args.raw_words)
            print(f"Wrote experimental SLM voice cassette image {args.output}. Switch acceptance is untested.")
    except (OSError, EOFError, ValueError, lzma.LZMAError) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")


if __name__ == "__main__":
    main()
