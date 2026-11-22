#!/usr/bin/env python3
"""Recover four SIT directory entries in the archived FSTD0BA load."""

import argparse
import hashlib
from pathlib import Path

import edram
from encode_edram import serialize


SOURCE_SHA256 = "aeb0d58e7c4a1db4ec09bf8d5246b7e2408654f255483e80939715b0099b99cd"
SIT_SLOTS = (8, 11, 16, 20)


def repair(data: bytes) -> bytes:
    """Copy the proved directory entries in a new binary load."""
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("expected the original FSTD0BA from EDRM0001 version 010")

    image = edram.Image(edram.parse_bin44(data))
    substitutions = {}
    for slot in SIT_SLOTS:
        offset = 4 * slot
        entry = image.read_bytes(offset, 4, required=True)
        reference = image.parse_phrase(0, slot, entry)
        peer = image.parse_phrase(edram.BANK_SIZE, slot, entry)
        if peer.segments != reference.segments:
            raise ValueError(f"bank 1 submenu for phrase {slot} differs from bank 0")
        for index, value in enumerate(entry, edram.BANK_SIZE + offset):
            substitutions[index] = value

    records = [
        (record.address, bytes(substitutions.get(address, value)
                               for address, value in enumerate(record.data, record.address)))
        for record in image.records
    ]
    repaired = serialize(records, "bin44")
    edram.Image(edram.parse_bin44(repaired)).phrases()
    return repaired


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="original FSTD0BA factory file")
    parser.add_argument("output", type=Path, help="new .bin44 file")
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != ".bin44":
        parser.error("output must have a .bin44 extension")
    try:
        repaired = repair(args.source.read_bytes())
        with args.output.open("xb") as target:
            target.write(repaired)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    print(f"{args.output}: repaired bank 1 SIT slots 8, 11, 16 and 20")


if __name__ == "__main__":
    main()
