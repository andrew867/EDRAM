#!/usr/bin/env python3
"""Build and check EDRM0001-style release manifests for existing load files."""
import argparse
from pathlib import Path
import re


def load_name(filename):
    if not re.fullmatch(r"[A-Za-z0-9_]+\.(?:bin44|txt80|txt)", filename, re.IGNORECASE):
        raise ValueError(f"invalid release filename: {filename}")
    return Path(filename).stem


def file_fields(path):
    data = path.read_bytes()
    checksum = 0
    for byte in data:
        checksum = (((checksum >> 1) | ((checksum & 1) << 15)) + byte) & 0xFFFF
    return checksum, (len(data) + 511) // 512


def check_names(filenames):
    names = [load_name(filename) for filename in filenames]
    if len({name.upper() for name in names}) != len(names):
        raise ValueError("duplicate load name")
    return names


def build(name, output, paths):
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError("invalid manifest name")
    names = check_names([path.name for path in paths])

    checksums = []
    for path in paths:
        checksum, blocks = file_fields(path)
        checksum_text = str(checksum) if path.suffix.lower() == ".bin44" else f"{checksum:05d}"
        checksums.append(f"{path.name} {checksum_text} {blocks} NEW")

    manifests = ((output / f"{name}.loads", names), (output / f"{name}.chksum", checksums))
    output.mkdir()
    created = []
    try:
        for path, lines in manifests:
            with path.open("xb") as stream:
                created.append(path)
                stream.write(("\n".join(lines) + "\n").encode("ascii"))
    except OSError:
        for path in created:
            path.unlink()
        output.rmdir()
        raise


def verify(loads, payload_dir):
    names = loads.read_text(encoding="ascii").splitlines()
    checksum_file = loads.with_suffix(".chksum")
    entries = []
    for line_number, line in enumerate(checksum_file.read_text(encoding="ascii").splitlines(), 1):
        fields = line.split()
        if len(fields) != 4 or not fields[1].isdigit() or not fields[2].isdigit() or fields[3] != "NEW":
            raise ValueError(f"{checksum_file.name}:{line_number}: invalid checksum row")
        filename, checksum, blocks, _ = fields
        entries.append((filename, int(checksum), int(blocks)))
    if not entries or names != check_names([filename for filename, _, _ in entries]):
        raise ValueError(".loads names and .chksum filename stems differ")

    mismatches = []
    for filename, checksum, blocks in entries:
        actual_sum, actual_blocks = file_fields(payload_dir / filename)
        if (actual_sum, actual_blocks) != (checksum, blocks):
            mismatches.append(f"{filename}: expected {checksum} / {blocks}, got {actual_sum} / {actual_blocks}")
    return len(entries), mismatches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    writer = commands.add_parser("build", help="write both manifests into a new directory")
    writer.add_argument("name", help="base name shared by the two manifests")
    writer.add_argument("output", type=Path)
    writer.add_argument("files", nargs="+", type=Path)
    checker = commands.add_parser("verify", help="compare both manifests with the payloads")
    checker.add_argument("loads", type=Path)
    checker.add_argument("--payload-dir", type=Path, help="defaults to the directory containing the manifests")
    args = parser.parse_args()

    try:
        if args.command == "build":
            build(args.name, args.output, args.files)
            print(f"Wrote {args.name}.loads and {args.name}.chksum for {len(args.files)} files.")
        else:
            count, mismatches = verify(args.loads, args.payload_dir or args.loads.parent)
            if mismatches:
                parser.exit(1, f"{count - len(mismatches)}/{count} entries verified.\n" + "\n".join(mismatches) + "\n")
            print(f"Verified {count} entries.")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")


if __name__ == "__main__":
    main()
