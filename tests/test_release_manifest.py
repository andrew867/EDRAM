from pathlib import Path
import tempfile
import unittest

import release_manifest


class ReleaseManifestTests(unittest.TestCase):
    def test_archived_example_and_block_units(self):
        originals = Path(__file__).resolve().parents[1] / "data" / "original"
        self.assertEqual(release_manifest.file_fields(originals / "edrmtone.txt80"), (1878, 341))
        self.assertEqual(release_manifest.file_fields(originals / "mwttone.txt80"), (17339, 110))

    def test_roundtrip_and_changed_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            voice = base / "LABANN.bin44"
            voice.write_bytes(b"\0" * 512 + b"\1")
            info = base / "LABANN_INFO.txt"
            info.write_bytes(b"\1")
            output = base / "manifests"
            release_manifest.build("LABANN", output, [info, voice])
            loads = output / "LABANN.loads"
            self.assertEqual(loads.read_bytes(), b"LABANN_INFO\nLABANN\n")
            self.assertEqual(loads.with_suffix(".chksum").read_bytes(),
                             b"LABANN_INFO.txt 00001 1 NEW\nLABANN.bin44 1 2 NEW\n")
            self.assertEqual(release_manifest.verify(loads, base), (2, []))
            with self.assertRaises(FileExistsError):
                release_manifest.build("LABANN", output, [voice])
            voice.write_bytes(b"\0" * 513)
            self.assertEqual(release_manifest.verify(loads, base),
                             (2, ["LABANN.bin44: expected 1 / 2, got 0 / 2"]))

    def test_duplicate_load_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate load name"):
            release_manifest.check_names(["LABANN.bin44", "labann.txt80"])
