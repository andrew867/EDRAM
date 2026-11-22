"""List or extract files from a Nortel XA-Core DSK1 / FTFS disk image.

The input can be a raw image or a single-stream XZ image. Extracted files
contain the declared byte count, in disk extent order, with 16-bit byte
pairs normalized. File-internal formats such as Nortel S-record wrappers
are preserved. Extraction creates a new output directory.

Examples:
    python xacore_ftfs.py 0001.img.xz --volume PMLD
    python xacore_ftfs.py 0001.img.xz --volume PMLD --name ED16AA07 --extract found
    python xacore_ftfs.py 0001.img.xz --extract 0001-files
"""

import argparse
import bisect
from collections import OrderedDict
from dataclasses import dataclass
import lzma
from pathlib import Path
import re
import struct
import sys
import zlib


SECTOR = 512
ROOT = 13 * SECTOR
DIRECTORY_PAGE = 1024
DIRECTORY_ENTRIES = 26
DIRECTORY_ENTRY_BYTES = 38
DESCRIPTOR_BYTES = 170
EXTENT_WIDTH = 6
DIRECT_EXTENTS = 8
NAME = rb"[A-Za-z0-9_$#+.()-]{1,32}"
COPY_CHUNK = 4 * 1024 * 1024


def swap_words(data):
    result = bytearray(len(data))
    result[::2] = data[1::2]
    result[1::2] = data[::2]
    return bytes(result)


def words32(data, offset):
    high, low = struct.unpack_from("<HH", data, offset)
    return high << 16 | low


def read_exact(stream, count):
    data = stream.read(count)
    if len(data) != count:
        raise ValueError("Truncated disk or XZ stream")
    return data


def read_vli(stream):
    value = 0
    for bit in range(0, 63, 7):
        byte = read_exact(stream, 1)[0]
        value |= (byte & 127) << bit
        if byte < 128:
            return value
    raise ValueError("Invalid XZ variable-length integer")


class Disk:
    """Read raw images or random-access blocks from a single-stream XZ image."""

    def __init__(self, path):
        self.path = Path(path)
        self.source = self.path.open("rb")
        self.offsets = []
        self.blocks = []
        self.cache = OrderedDict()
        try:
            self.source.seek(0, 2)
            self.size = self.source.tell()
            if self.path.suffix.lower() == ".xz":
                self.index_xz()
            if self.read(0, 4) != b"DSK1":
                raise ValueError("Expected a word-swapped XA-Core DSK1 disk")
        except BaseException:
            self.source.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.source.close()

    def index_xz(self):
        self.source.seek(0)
        self.header = read_exact(self.source, 12)
        self.source.seek(-12, 2)
        footer = read_exact(self.source, 12)
        if self.header[:6] != b"\xfd7zXZ\0" or footer[-2:] != b"YZ":
            raise ValueError("Expected one XZ stream without trailing padding")
        index_size = (struct.unpack_from("<I", footer, 4)[0] + 1) * 4
        index_start = self.size - 12 - index_size
        if index_start < 12:
            raise ValueError("Invalid XZ index length")
        self.source.seek(index_start)
        index = read_exact(self.source, index_size)
        if index[0] or zlib.crc32(index[:-4]) != struct.unpack_from("<I", index, index_size - 4)[0]:
            raise ValueError("Invalid XZ index")
        self.source.seek(index_start + 1)
        packed_offset = 12
        offset = 0
        for _ in range(read_vli(self.source)):
            packed_length = (read_vli(self.source) + 3) & ~3
            length = read_vli(self.source)
            if not packed_length or not length:
                raise ValueError("Empty XZ block")
            self.offsets.append(offset)
            self.blocks.append((packed_offset, packed_length, length))
            packed_offset += packed_length
            offset += length
        if packed_offset != index_start or self.source.tell() > self.size - 16:
            raise ValueError("XZ block sizes disagree with the index location")
        self.size = offset

    def read_raw(self, offset, size):
        if offset < 0 or size < 0 or offset + size > self.size:
            raise ValueError("Disk read is outside the image")
        if not self.blocks:
            self.source.seek(offset)
            return read_exact(self.source, size)
        pieces = []
        while size:
            block = bisect.bisect_right(self.offsets, offset) - 1
            if block not in self.cache:
                packed_offset, packed_length, length = self.blocks[block]
                self.source.seek(packed_offset)
                decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
                raw = decoder.decompress(self.header + read_exact(self.source, packed_length))
                if len(raw) != length:
                    raise ValueError("XZ block length mismatch")
                self.cache[block] = raw
                if len(self.cache) > 2:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(block)
            within = offset - self.offsets[block]
            part = self.cache[block][within:within + size]
            pieces.append(part)
            size -= len(part)
            offset += len(part)
        return b"".join(pieces)

    def read(self, offset, size):
        start = offset & ~1
        end = (offset + size + 1) & ~1
        result = swap_words(self.read_raw(start, end - start))
        return result[offset - start:offset - start + size]


@dataclass(frozen=True)
class Volume:
    name: str
    start: int
    size: int

    @property
    def end(self):
        return self.start + self.size


@dataclass(frozen=True)
class File:
    volume: Volume
    name: str
    index: int
    descriptor: int
    size: int
    extents: tuple[tuple[int, int], ...]

    @property
    def address(self):
        return self.extents[0][0] if self.extents else 0

    @property
    def allocated(self):
        return sum(length for _, length in self.extents)


def checksum(record):
    words = struct.iter_unpack("<H", record[:-2])
    return (sum(word for word, in words) & 0xffff) == struct.unpack_from("<H", record, len(record) - 2)[0]


def file_extents(disk, volume, descriptor, name):
    first_size = words32(descriptor, 0x1c) * 1024
    growth_size = words32(descriptor, 0x20) * 1024
    count = words32(descriptor, 0x24)
    table_start = 0x54
    indirect_start = table_start + DIRECT_EXTENTS * EXTENT_WIDTH
    entries = descriptor[table_start:indirect_start]
    if count > DIRECT_EXTENTS:
        extra_count = count - DIRECT_EXTENTS
        indirect = words32(descriptor, indirect_start) * SECTOR
        if extra_count > (SECTOR - 2) // EXTENT_WIDTH or not volume.start < indirect <= volume.end - SECTOR:
            raise ValueError(f"Unsupported indirect extent table in {volume.name}/{name}")
        extension = disk.read(indirect, SECTOR)
        listed_sum = struct.unpack_from("<H", extension)[0]
        computed_sum = sum(word for word, in struct.iter_unpack("<H", extension[2:])) & 0xffff
        if computed_sum != listed_sum:
            raise ValueError(f"Invalid extent table checksum in {volume.name}/{name}")
        entries += extension[2:]
    return tuple(
        (words32(entries, index * EXTENT_WIDTH) * SECTOR, first_size if index == 0 else growth_size)
        for index in range(count)
    )


def volumes(disk):
    primary = disk.read(ROOT, 2 * SECTOR)
    if primary != disk.read(ROOT + 2 * SECTOR, 2 * SECTOR):
        raise ValueError("XA-Core primary and backup volume tables differ")
    found = []
    for offset in range(4, len(primary) - 19, 20):
        name, start, count = struct.unpack_from("<12sII", primary, offset)
        name = name.rstrip(b" ")
        if not re.fullmatch(rb"[A-Z0-9_]{1,12}", name):
            continue
        volume = Volume(name.decode("ascii"), start * SECTOR, count * SECTOR)
        if volume.start < ROOT + 4 * SECTOR or volume.end > disk.size or not volume.size:
            raise ValueError(f"Invalid sector range for {volume.name}")
        found.append(volume)
    if not found:
        raise ValueError("No XA-Core volumes found")
    return found


def volume_files(disk, volume):
    header = disk.read(volume.start, SECTOR)
    if header[:4] != b"FTFS" or header[6:14].rstrip() != volume.name.encode():
        raise ValueError(f"Unsupported volume header in {volume.name}")
    directory = struct.unpack_from("<I", header, 32)[0] * SECTOR
    table = words32(header, 0x46) * SECTOR
    if not volume.start < table < directory < volume.end:
        raise ValueError(f"Invalid metadata locations in {volume.name}")
    descriptors = disk.read(table, directory - table)
    root_allocated = words32(descriptors, 0x1c) * 1024
    if (not checksum(descriptors[:DESCRIPTOR_BYTES]) or root_allocated < DIRECTORY_PAGE
            or root_allocated % DIRECTORY_PAGE or directory + root_allocated > volume.end):
        raise ValueError(f"Invalid directory descriptor in {volume.name}")
    pages = disk.read(directory, root_allocated)
    found = []
    seen = set()
    for page_start in range(0, len(pages), DIRECTORY_PAGE):
        page = pages[page_start:page_start + DIRECTORY_PAGE]
        if not checksum(page):
            if not any(page):
                continue
            raise ValueError(f"Invalid directory checksum in {volume.name} at {directory + page_start:#x}")
        entries = page[:DIRECTORY_ENTRIES * DIRECTORY_ENTRY_BYTES]
        for raw_name, index, generation, _ in struct.iter_unpack("<32s3H", entries):
            raw_name = raw_name.rstrip(b" ")
            if not raw_name:
                continue
            name = raw_name.decode("ascii")
            if name in (".", ".."):
                continue
            if not re.fullmatch(NAME, raw_name) or not index or not generation or index in seen:
                raise ValueError(f"Invalid directory entry in {volume.name}: {name!r}")
            sector, descriptor_slot = divmod(index, 3)
            start = sector * SECTOR + descriptor_slot * DESCRIPTOR_BYTES
            desc = descriptors[start:start + DESCRIPTOR_BYTES]
            if len(desc) != DESCRIPTOR_BYTES:
                raise ValueError(f"Descriptor outside the table for {volume.name}/{name}")
            state, identifier, revision = struct.unpack_from("<3H", desc)
            if state != 1 or identifier != index or revision != generation or not checksum(desc):
                raise ValueError(f"Invalid descriptor for {volume.name}/{name}")
            size = words32(desc, 0x2a)
            extents = file_extents(disk, volume, desc, name)
            file = File(volume, name, index, table + start, size, extents)
            if (size > file.allocated
                    or any(length <= 0 or address < directory + root_allocated or address + length > volume.end
                           for address, length in extents)):
                raise ValueError(f"Invalid extents in {volume.name}/{name}: {size} bytes, {extents!r}")
            found.append(file)
            seen.add(index)
    ranges = sorted((address, address + length) for file in found for address, length in file.extents)
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise ValueError(f"File allocations overlap in {volume.name}")
    return found


def copy_file(disk, file, path):
    """Write the declared file bytes, following its extent order."""
    with path.open("xb") as output:
        remaining = file.size
        for offset, capacity in file.extents:
            used = min(remaining, capacity)
            for start in range(0, used, COPY_CHUNK):
                output.write(disk.read(offset + start, min(COPY_CHUNK, used - start)))
            remaining -= used


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="XA-Core raw disk or .img.xz")
    parser.add_argument("--volume", action="append", default=[], help="Select a named volume")
    parser.add_argument("--name", action="append", default=[], help="Select a named file")
    parser.add_argument("--extract", type=Path, help="Extract into a new directory instead of listing")
    args = parser.parse_args()

    requested_volumes = {name.upper() for name in args.volume}
    requested_files = {name.upper() for name in args.name}
    try:
        with Disk(args.image) as disk:
            selected = [volume for volume in volumes(disk)
                        if not requested_volumes or volume.name in requested_volumes]
            missing = requested_volumes.difference(volume.name for volume in selected)
            if missing:
                raise ValueError(f"Volumes not found: {', '.join(sorted(missing))}")
            files = []
            for volume in selected:
                files.extend(file for file in volume_files(disk, volume)
                             if not requested_files or file.name.upper() in requested_files)
            missing = requested_files.difference(file.name.upper() for file in files)
            if missing:
                raise ValueError(f"Files not found: {', '.join(sorted(missing))}")

            if args.extract is not None:
                args.extract.mkdir(parents=True, exist_ok=False)
                for file in sorted(files, key=lambda file: file.address):
                    folder = args.extract / file.volume.name
                    folder.mkdir(exist_ok=True)
                    copy_file(disk, file, folder / file.name)
            else:
                for file in files:
                    print(f"{file.volume.name}/{file.name}\t{file.size}\t{len(file.extents)} extents")
            print(f"{len(files)} files, {sum(file.size for file in files):,} bytes", file=sys.stderr)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
