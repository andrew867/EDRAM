import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edram
import tone_bank


ORIGINALS = Path(__file__).resolve().parents[1] / "data" / "original"


class ToneBankTests(unittest.TestCase):
    def test_eight_bit_750_hz_waveform_and_menu_repeats(self):
        source = ORIGINALS / "estd0aa.bin44"
        image = edram.Image.read(source)
        self.assertEqual(image.read_bytes(0x104, 8), bytes.fromhex("0e000102 0f000103"))
        attack = image.read_bytes(0x0E00, 256)
        sustain = image.read_bytes(0x0F00, 256)
        period = bytes.fromhex("0284868787840204060604818486878682040607070482848686840104060706")
        self.assertEqual(sustain[-128:], period * 4)
        samples = struct.unpack("<32h", edram.decode(period))
        self.assertEqual(sum(a <= 0 < b for a, b in zip(samples, samples[1:] + samples[:1])), 3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = edram.export(source, root, "alaw-unmasked")
            entry = next(p for p in manifest["phrases"] if (p["bank"], p["number"]) == (0, 1))
            self.assertEqual(entry["tone_name"], "750 Hz test tone")
            with wave.open(str(root / source.stem / entry["wav"])) as wav:
                self.assertEqual(wav.getnframes(), 1280)
                self.assertEqual(wav.readframes(1280), edram.decode(attack * 2 + sustain * 3))

    def test_sit_export_uses_source_pcm_and_menu_length(self):
        source = ORIGINALS / "estd0aa.bin44"
        image = edram.Image.read(source)
        codes = b"".join(image.read_bytes(a, 256) + image.read_bytes(b, 512) * 4
                         for a, b in ((0x1100, 0x1200), (0x1700, 0x1800), (0x1D00, 0x1E00)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = edram.export(source, root, "alaw-unmasked")
            entry = next(p for p in manifest["phrases"] if (p["bank"], p["number"]) == (0, 8))
            self.assertEqual(entry["samples"], 3 * 2304)
            with wave.open(str(root / source.stem / entry["wav"])) as wav:
                self.assertEqual(wav.readframes(wav.getnframes()), edram.decode(codes))

    def test_length_words_extract_milliwatt_and_roh_at_known_addresses(self):
        image = edram.Image.read(ORIGINALS / "mwttone.txt80")
        records = list(tone_bank.records(image))
        self.assertEqual(len(records), 17)
        self.assertEqual([(entry["sample_address"], len(raw)) for entry, raw in records[8:11]],
                         [(0x37A0, 996), (0x3BCC, 2000), (0x43E4, 996)])
        self.assertEqual(records[9][0]["frequencies_hz"], [1404, 2060, 2452, 2604])
        self.assertTrue(all(entry["codec"] == "mulaw-unmasked" for entry, _ in records))

    def test_spanish_busy_preserves_lead_in(self):
        image = edram.Image.read(ORIGINALS / "scls10cj.bin44")
        phrase = next(p for p in image.phrases(strict=False) if p.bank == 1 and p.number == 7)
        pcm, _ = edram.render(image, phrase)
        info = edram.tone_metadata(image, phrase, pcm, "alaw-unmasked")
        self.assertIn("tone_name", info)
        self.assertTrue(any(pcm[:1026]))

    def test_second_bank_has_two_dtmf_sets_and_exports_real_samples(self):
        source = ORIGINALS / "edrmtone.txt80"
        stored = list(tone_bank.records(edram.Image.read(source)))
        self.assertEqual(len(stored), 64)
        self.assertEqual((stored[0][1][3], stored[17][1][3]), (0x94, 0x54))
        for start, codec in ((21, "mulaw-unmasked"), (45, "alaw-unmasked")):
            group = stored[start:start + 16]
            self.assertEqual({entry["tone_name"].split()[1].rstrip(",") for entry, _ in group},
                             set("0123456789ABCD*#"))
            self.assertTrue(all(entry["codec"] == codec and len(raw) == 394 for entry, raw in group))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = edram.export(source, root, "alaw-unmasked", raw_tones=True)
            for entry, (_, payload) in zip(manifest["tone_bank"], stored, strict=True):
                raw = (root / source.stem / entry["raw"]).read_bytes()
                self.assertEqual(raw, (len(payload) // 2).to_bytes(2, "big") + payload)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["record_sha256"])
            self.assertEqual(sum(bool(t["wav"]) for t in manifest["tone_bank"]), 62)
            phrase = next(p for p in manifest["phrases"] if (p["bank"], p["number"]) == (0, 41))
            self.assertIsNone(phrase["wav"])
            self.assertIn("overlaps standalone tone records", phrase["reason"])
            original = manifest["tone_bank"][0]
            with wave.open(str(root / source.stem / original["wav"])) as wav:
                self.assertEqual(wav.readframes(wav.getnframes()), edram.decode(stored[0][1], original["codec"]))
            entry = manifest["tone_bank"][8]
            with wave.open(str(root / source.stem / entry["wav"])) as wav:
                pcm = wav.readframes(wav.getnframes())
            self.assertEqual(pcm, edram.decode(stored[8][1], "mulaw-unmasked"))
            self.assertEqual(hashlib.sha256(pcm).hexdigest(), entry["pcm_sha256"])


if __name__ == "__main__":
    unittest.main()
