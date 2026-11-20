#!/usr/bin/env python3
"""Download the public reference archive and retain only its original load files."""
import argparse
import hashlib
from pathlib import Path
import tarfile
import urllib.request

URL = "http://www.dms-100.net/files/telephony/nortel/SL100/samples/EDRAM/edram.tar.gz"
SHA256 = "88ab9decafafbb71642e5b58b9be91d1f9d6d801f00d838f1f16347506c27bf8"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, nargs="?", default=Path("samples"))
    parser.add_argument("--archive", type=Path, help="use an already downloaded reference archive")
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    archive = args.archive or args.destination / "edram.tar.gz"
    if not archive.exists():
        print("Downloading public reference archive...")
        with urllib.request.urlopen(URL, timeout=60) as source, archive.open("wb") as target:
            while block := source.read(1024 * 1024):
                target.write(block)
    with archive.open("rb") as file:
        digest = hashlib.sha256(file.read()).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"Archive SHA-256 mismatch: {digest}; refusing extraction")
    with tarfile.open(archive, "r:gz") as source:
        for member in source.getmembers():
            parts = member.name.split("/")
            if (not member.isfile() or len(parts) != 2 or parts[0] != "edram-data-orig"
                    or parts[1] in ("", ".", "..") or "\\" in parts[1]):
                continue
            target = args.destination / parts[1]
            if target.exists():
                raise SystemExit(f"File already exists: {target}")
            with source.extractfile(member) as data:
                target.write_bytes(data.read())
    print(f"Verified original files saved to {args.destination}")


if __name__ == "__main__":
    main()
