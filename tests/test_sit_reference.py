from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import edram
import sit_reference

ORIGINALS = Path(__file__).resolve().parents[1] / "data" / "original"


class SitReferenceTests(unittest.TestCase):
    def test_short_short_long_menu_selects_documented_profile(self):
        menu=[
            {"page":17,"pages":1,"repeats":1},{"page":18,"pages":2,"repeats":4},
            {"page":23,"pages":1,"repeats":1},{"page":24,"pages":2,"repeats":4},
            {"page":29,"pages":1,"repeats":1},{"page":30,"pages":2,"repeats":5},
            {"page":30,"pages":1,"repeats":1},
        ]
        parts=sit_reference.profile(menu)
        self.assertEqual([(p["frequency_hz"],p["duration_ms"]) for p in parts],
                         [(913.8,274),(1370.6,274),(1776.7,380)])
        self.assertEqual(len(sit_reference.synthesize(parts))//2,7424)

    def test_unknown_menu_does_not_get_a_fabricated_profile(self):
        with self.assertRaises(ValueError):
            sit_reference.profile([{"page":40,"pages":2,"repeats":1}])

    def test_reference_is_bounded_and_silent_at_outer_boundaries(self):
        pcm=sit_reference.synthesize([{"frequency_hz":913.8,"duration_ms":274}])
        values=struct.unpack("<"+"h"*(len(pcm)//2),pcm)
        self.assertEqual(values[0],0)
        self.assertEqual(values[-1],0)
        self.assertLessEqual(max(abs(v) for v in values),5000)

    def test_export_uses_sine_components_and_allows_raw_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = ORIGINALS / "estd0aa.bin44"
            manifest = edram.export(image, root, "alaw-unmasked")
            item = next(p for p in manifest["phrases"] if p["number"] == 9)
            wav_path = root / image.stem / item["wav"]
            self.assertEqual(item["rendering"], "nortel-sit")
            self.assertEqual(item["menu_samples"], 7680)
            with wave.open(str(wav_path)) as wav:
                self.assertEqual(wav.getnframes(), 7424)
                pcm = struct.unpack("<7424h", wav.readframes(7424))
            start = 0
            for length, expected_hz in ((2192, 913.8), (2192, 1370.6), (3040, 1776.7)):
                block = pcm[start:start + length]
                self.assertEqual((block[0], block[-1]), (0, 0))
                crossings = [i - block[i] / (block[i + 1] - block[i])
                             for i in range(32, length - 32) if block[i] <= 0 < block[i + 1]]
                hz = (len(crossings) - 1) * 8000 / (crossings[-1] - crossings[0])
                self.assertAlmostEqual(hz, expected_hz, delta=0.05)
                start += length
            raw = edram.export(image, root, "alaw-unmasked", overwrite=True, raw_sit=True)
            item = next(p for p in raw["phrases"] if p["number"] == 9)
            self.assertEqual(item["samples"], 7680)
            self.assertNotIn("rendering", item)

    def test_exact_french_menu_pointer_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = edram.export(ORIGINALS / "fstd0ba.bin44", root, "alaw-unmasked")
            first, second = [p for p in manifest["phrases"] if p["number"] == 16]
            self.assertEqual(second["sit_profile_source"], "fstd0ba-bank-0-sit9")
            self.assertEqual(first["pcm_sha256"], second["pcm_sha256"])
            with self.assertRaises(ValueError):
                sit_reference.archived_profile(second["segments"], source_hash="other", bank=1, phrase=16)


if __name__=="__main__":
    unittest.main()
