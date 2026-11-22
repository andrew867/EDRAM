from hashlib import sha256
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edram
import repair_fstd0ba


class Fstd0baRepairTests(unittest.TestCase):
    def test_repairs_all_four_entries_and_preserves_other_writes(self):
        source = Path(__file__).resolve().parents[1] / "data" / "original" / "fstd0ba.bin44"
        original_bytes = source.read_bytes()
        original = edram.Image(edram.parse_bin44(original_bytes))
        original.phrases(strict=False)
        self.assertEqual([p["number"] for p in original.invalid_phrases], [8, 11, 20])

        repaired_bytes = repair_fstd0ba.repair(original_bytes)
        repaired = edram.Image(edram.parse_bin44(repaired_bytes))
        phrases = {(p.bank, p.number): p for p in repaired.phrases()}
        changed = {0x40020, 0x40023, 0x4002C, 0x4002F, 0x40040, 0x40043, 0x40050, 0x40053}
        self.assertEqual(len(repaired_bytes), len(original_bytes))
        self.assertEqual(repaired.coverage, original.coverage)
        for before, after in zip(original.records, repaired.records, strict=True):
            self.assertEqual((before.address, before.location, before.kind),
                             (after.address, after.location, after.kind))
            for address, (old, new) in enumerate(zip(before.data, after.data, strict=True), before.address):
                if old != new:
                    changed.remove(address)
        self.assertEqual(changed, set())

        for slot, sample_count in {8: 6912, 11: 8448, 16: 7680, 20: 7680}.items():
            with self.subTest(slot=slot):
                reference, candidate = (phrases[(bank, slot)] for bank in (0, 1))
                self.assertEqual(candidate.segments, reference.segments)
                self.assertEqual(sum(s.samples for s in candidate.segments), sample_count)
                self.assertEqual(edram.render(repaired, candidate), edram.render(original, reference))

        footer = int.from_bytes(repaired_bytes[-41:-37], "big")
        payload_total = sum(word for record in repaired.records
                            for word, in struct.iter_unpack(">H", record.data))
        self.assertEqual(footer, payload_total & 0xFFFFFFFF)
        self.assertEqual(repair_fstd0ba.SOURCE_SHA256, sha256(source.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError, "original FSTD0BA"):
            repair_fstd0ba.repair(repaired_bytes)


if __name__ == "__main__":
    unittest.main()
