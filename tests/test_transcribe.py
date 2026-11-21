import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edram
import transcribe


class TranscriptTests(unittest.TestCase):
    def make_archive(self, root, *, tone=False):
        folder = root / "pack"
        folder.mkdir()
        pcm = struct.pack("<hh", 1000, -1000) * 256
        paths = ["bank_00/phrase_04.wav", "bank_00/phrase_05.wav"]
        phrases = []
        for index, path in enumerate(paths):
            edram.write_wav(folder / path, pcm, "Test", "Test fixture")
            phrases.append({"bank": 0, "number": index + 4, "wav": path, "label": f"phrase_{index + 4:02d}",
                            "segments": [{"page": 17, "pages": 2, "repeats": 1}]})
        if tone:
            phrases[0]["label"] = "phrase_08_sit_01"
        (folder / "manifest.json").write_text(json.dumps({"source": "pack.bin44", "phrases": phrases, "segments": []}))
        return pcm

    def test_identical_pcm_is_deduplicated_and_page17_speech_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_archive(root)
            plan = transcribe.make_plan(root)
            self.assertEqual(len(plan["clips"]), 2)
            self.assertEqual(len(plan["tasks"]), 1)
            self.assertTrue(all(c["content"] == "speech" for c in plan["clips"]))

    def test_known_tone_pcm_is_not_sent_to_speech_recognition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_archive(root, tone=True)
            plan = transcribe.make_plan(root)
            self.assertEqual(plan["tasks"], [])
            self.assertTrue(all(c["content"] == "tone" for c in plan["clips"]))

    def test_missing_shard_results_prevent_false_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_archive(root)
            plan = root / "plan.json"
            plan.write_text(json.dumps(transcribe.make_plan(root)))
            with self.assertRaisesRegex(ValueError, "coverage mismatch"):
                transcribe.merge(root, plan, root)

    def test_player_escapes_model_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clips = [{"path": "pack/test.wav", "source": "pack", "kind": "announcement", "bank": 0,
                      "label": "phrase_04", "seconds": 1, "content": "speech",
                      "transcript": {"text": "<script>alert(1)</script>", "language": "en",
                                     "review_recommended": True}}]
            transcribe.write_player(root, clips)
            page = (root / "listen.html").read_text()
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
            self.assertNotIn("<script>alert(1)</script>", page)

    def test_player_links_all_three_sit_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tone-restoration.json").write_text(json.dumps({"clips": {"pack/sit.wav": "tones/restored.wav"}}))
            clip = {"path": "pack/sit.wav", "source": "pack", "kind": "announcement", "bank": 0,
                    "label": "phrase_09_sit_02", "seconds": 0.96, "content": "tone",
                    "reference_wav": "../references/sit/example.wav", "transcript": {"text": ""}}
            transcribe.write_player(root, [clip])
            page = (root / "listen.html").read_text()
            self.assertIn('data-restored="true"', page)
            self.assertIn('data-src="tones/restored.wav" data-playback="Restored tone"', page)
            self.assertIn('href="tones/restored.wav" download', page)
            self.assertIn('data-src="pack/sit.wav" data-playback="Direct A-law"', page)
            self.assertIn('data-src="../references/sit/example.wav"', page)


if __name__ == "__main__":
    unittest.main()
