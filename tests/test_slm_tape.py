import lzma
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import encode_edram
import slm_tape as tape


def label(kind, name, size=0, ordinal=1):
    raw = bytearray(512)
    raw[:2] = b"\x00\x01"
    raw[2:6] = tape.swap_words(kind)
    if kind == b"VOL1":
        raw[6:38] = tape.swap_words(name.ljust(32).encode("ascii"))
    else:
        raw[8:40] = tape.swap_words(name.ljust(32).encode("ascii"))
        struct.pack_into(">HIIHH", raw, 84, 1, size, (size + 511) // 512, 512, 11)
        raw[164:168] = tape.swap_words(b"LFS0")
        struct.pack_into(">H", raw, 168, 128)
        struct.pack_into(">H", raw, 172, 2)
        struct.pack_into(">HIH", raw, 178, 130, size // 128, size % 512 if kind == b"EOF1" else 0)
    return tape.number_label(raw, ordinal) if kind != b"VOL1" else finish_volume_checksum(raw)


def finish_volume_checksum(raw):
    struct.pack_into(">H", raw, 510, tape.checksum(raw))
    return raw


def fixture(path, name, payload):
    with path.open("wb") as stream:
        tape.write_label(stream, label(b"VOL1", "LAB"))
        tape.write_label(stream, label(b"HDR1", name, len(payload)))
        for offset in range(0, len(payload), 512):
            block = tape.swap_words(payload[offset:offset + 512].ljust(512, b"\0"))
            stream.write(tape.BLOCK_WORD + block + tape.BLOCK_WORD)
        stream.write(tape.MARK)
        tape.write_label(stream, label(b"EOF1", name, len(payload)))
        stream.write(tape.MARK * 2)


class TapeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.base = self.root / "base.tap"
        fixture(self.base, "BASE$PATCH", b"\xb0Q" * 128)

    def test_append_preserves_existing_prefix_and_donor_payload(self):
        donor = self.root / "donor.tap"
        body = bytes(range(256)) * 3
        fixture(donor, "SECOND", body)
        compressed = self.root / "donor.tap.xz"
        compressed.write_bytes(lzma.compress(donor.read_bytes()))
        output = self.root / "combined.tap"
        tape.append(self.base, output, compressed, ["SECOND"])
        result = tape.inventory(output)
        self.assertEqual([e.ordinal for e in result.entries], [1, 2])
        prefix = tape.inventory(self.base).append_offset
        self.assertEqual(output.read_bytes()[:prefix], self.base.read_bytes()[:prefix])
        selected = result.find("second")
        self.assertEqual((selected.size, selected.blocks, selected.record_size, selected.records), (768, 2, 128, 6))
        extracted = self.root / "extracted"
        tape.extract(output, selected, extracted)
        self.assertEqual(extracted.read_bytes(), body)

    def test_generated_bin44_spans_blocks_and_extracts_byte_for_byte(self):
        voice = self.root / "LABANN.bin44"
        voice.write_bytes(encode_edram.build_load("LABANN", {40: b"\x81" * 919}, "bin44"))
        output = self.root / "voice.tap"
        tape.add_bin44(self.base, voice, output, "LABANN", "BASE$PATCH", standalone=True)
        result = tape.inventory(output)
        entry, = result.entries
        self.assertEqual((entry.name, entry.ordinal, entry.record_size, entry.overhead), ("LABANN", 1, 44, 2))
        self.assertEqual(entry.records * 44, voice.stat().st_size)
        self.assertGreater(entry.blocks, 1)
        recovered = self.root / "roundtrip.bin44"
        tape.extract(output, entry, recovered)
        self.assertEqual(recovered.read_bytes(), voice.read_bytes())

    def test_malformed_records_and_duplicate_append_fail(self):
        bad = self.root / "bad.tap"
        damaged = bytearray(self.base.read_bytes())
        damaged[60] ^= 1
        bad.write_bytes(damaged)
        with self.assertRaisesRegex(tape.TapeError, "checksum"):
            tape.inventory(bad)
        output = self.root / "duplicate.tap"
        with self.assertRaisesRegex(tape.TapeError, "duplicate"):
            tape.append(self.base, output, self.base, ["BASE$PATCH"])
        self.assertFalse(output.exists())
