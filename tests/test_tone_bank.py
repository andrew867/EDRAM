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
    def test_known_cue_and_shifted_waveform_render_identically(self):
        rendered = []
        for name in ("eacts0ae.bin44", "jpdmct00.bin44"):
            image = edram.Image.read(ORIGINALS / name)
            phrase = next(p for p in image.phrases(strict=False) if p.bank == 0 and p.number == 1)
            pcm, _, tone = edram.render_export(image, phrase, "alaw-unmasked", "")
            self.assertEqual(tone["rendering"], "nortel-cue")
            self.assertEqual(len(pcm), 2560)
            values = struct.unpack("<1280h", pcm)
            self.assertGreater(max(values[-250:]), 4900)
            rendered.append(pcm)
        self.assertEqual(*rendered)

    def test_prompt_cadence_has_three_96_ms_bursts(self):
        image = edram.Image.read(ORIGINALS / "estd0aa.bin44")
        phrase = next(p for p in image.phrases() if p.bank == 0 and p.number == 2)
        pcm, _, _ = edram.render_export(image, phrase, "alaw-unmasked", "")
        self.assertEqual(len(pcm), 2 * 7936)
        self.assertEqual(pcm[:8192], bytes(8192))
        for start in (4096, 5120, 6144):
            self.assertNotEqual(pcm[2 * start:2 * (start + 768)], bytes(1536))
            self.assertEqual(pcm[2 * (start + 768):2 * (start + 1024)], bytes(512))
        raw, _, meta = edram.render_export(image, phrase, "alaw-unmasked", "", raw_cues=True)
        self.assertNotEqual(raw, pcm)
        self.assertNotIn("rendering", meta)

    def test_length_words_extract_milliwatt_and_roh_at_known_addresses(self):
        image = edram.Image.read(ORIGINALS / "mwttone.txt80")
        records = list(tone_bank.records(image))
        self.assertEqual(len(records), 17)
        self.assertEqual([(entry["sample_address"], len(raw)) for entry, raw in records[8:11]],
                         [(0x37A0, 996), (0x3BCC, 2000), (0x43E4, 996)])
        self.assertEqual(records[9][0]["frequencies_hz"], [1404, 2060, 2452, 2604])
        self.assertTrue(all(entry["codec"] == "mulaw-unmasked" for entry, _ in records))

    def test_spanish_busy_lead_repair_preserves_the_recorded_burst(self):
        image = edram.Image.read(ORIGINALS / "scls10cj.bin44")
        phrase = next(p for p in image.phrases(strict=False) if p.bank == 1 and p.number == 7)
        raw, _ = edram.render(image, phrase)
        pcm, _, info = edram.render_export(image, phrase, "alaw-unmasked", "")
        self.assertEqual(info["silenced_lead_samples"], 513)
        self.assertEqual(pcm[:1026], bytes(1026))
        self.assertEqual(pcm[1026:], raw[1026:])
        self.assertNotEqual(pcm, raw)

    def test_second_bank_has_two_dtmf_sets_and_exports_real_samples(self):
        source = ORIGINALS / "edrmtone.txt80"
        stored = list(tone_bank.records(edram.Image.read(source)))
        self.assertEqual(len(stored), 64)
        self.assertEqual(tone_bank.repair_samples(stored[0][0], stored[0][1]), stored[17][1])
        for start, codec in ((21, "mulaw-unmasked"), (45, "alaw-unmasked")):
            group = stored[start:start + 16]
            self.assertEqual({entry["tone_name"].split()[1].rstrip(",") for entry, _ in group},
                             set("0123456789ABCD*#"))
            self.assertTrue(all(entry["codec"] == codec and len(raw) == 394 for entry, raw in group))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = edram.export(source, root, "alaw-unmasked")
            self.assertEqual(sum(bool(t["wav"]) for t in manifest["tone_bank"]), 62)
            entry = manifest["tone_bank"][8]
            with wave.open(str(root / source.stem / entry["wav"])) as wav:
                pcm = wav.readframes(wav.getnframes())
            self.assertEqual(pcm, edram.decode(stored[8][1], "mulaw-unmasked"))
            self.assertEqual(hashlib.sha256(pcm).hexdigest(), entry["pcm_sha256"])


if __name__ == "__main__":
    unittest.main()
