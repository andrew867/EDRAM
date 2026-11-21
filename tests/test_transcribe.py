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

    def test_player_joins_catalog_only_to_the_matching_announcement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog.csv"
            catalog.write_text(
                "load,bank,phrase,nortel_name,catalog_note,printed_page,pdf_page,pcm_sha256\n"
                "pack,0,4,NAME,<catalog text>,17-35,285,original\n",
                encoding="utf-8",
            )
            clip = {"path": "pack/test.wav", "source": "pack", "kind": "announcement",
                    "bank": 0, "label": "phrase_04_sit_01", "seconds": 1, "content": "speech",
                    "pcm_sha256": "original", "transcript": {"text": "Existing transcription"}}
            transcribe.write_player(root, [clip], catalog_path=catalog)
            page = (root / "listen.html").read_text(encoding="utf-8")
            self.assertIn("<code>NAME</code>", page)
            self.assertIn("#page=285", page)
            self.assertIn("&lt;catalog text&gt;", page)
            self.assertIn('<span class="words">Existing transcription</span>', page)
            transcribe.write_player(root, [dict(clip, pcm_sha256="replacement")], catalog_path=catalog)
            self.assertNotIn("<code>NAME</code>", (root / "listen.html").read_text(encoding="utf-8"))

    def test_player_links_only_stored_sit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tone-restoration.json").write_text(json.dumps({"clips": {"pack/sit.wav": "tones/restored.wav"}}))
            clip = {"path": "pack/sit.wav", "source": "pack", "kind": "announcement", "bank": 0,
                    "label": "phrase_09_sit_02", "seconds": 0.96, "content": "tone",
                    "reference_wav": "../references/sit/example.wav", "transcript": {"text": ""}}
            transcribe.write_player(root, [clip])
            page = (root / "listen.html").read_text(encoding="utf-8")
            self.assertIn('data-tone="true"', page)
            self.assertIn('data-src="pack/sit.wav"', page)
            self.assertIn('href="pack/sit.wav" download', page)
            self.assertNotIn("restored.wav", page)
            self.assertNotIn("example.wav", page)

    def test_players_use_decoded_tones_instead_of_raw_bank_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "edrmtone"
            folder.mkdir()
            raw = {"bank": 0, "wav": "bank_00/phrase_41.wav", "label": "phrase_41",
                   "duration_seconds": 7.328, "segments": [{"page": 106, "pages": 86}]}
            speech = dict(raw, bank=1, wav="bank_01/phrase_41.wav")
            fragment = {"bank": 0, "page": 106, "pages": 86, "wav": "segments/bank_00_page_006a_pages_086.wav"}
            tone = {"index": 22, "wav": "tone-bank/tone_22.wav", "tone_name": "DTMF D, set 1",
                    "frequencies_hz": [934, 1624.4], "header_address": 0x6b26, "sample_address": 0x6b28,
                    "samples": 394, "codec": "mulaw-unmasked"}
            manifest = {"source": "edrmtone.txt80", "sample_rate": 8000, "phrases": [raw, speech],
                        "segments": [fragment], "tone_bank": [tone]}
            (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            clips = [
                {"path": "edrmtone/" + entry["wav"], "source": "edrmtone", "kind": kind,
                 "bank": entry["bank"], "label": "phrase_41", "seconds": 7.328,
                 "content": "speech", "transcript": {"text": ""}}
                for entry, kind in ((raw, "announcement"), (speech, "announcement"), (fragment, "segment"))
            ]
            for write_index in (lambda: transcribe.write_player(root, clips),
                                lambda: edram.write_browser(root, [manifest])):
                with self.subTest(write_index=write_index):
                    write_index()
                    page = (root / "listen.html").read_text(encoding="utf-8")
                    self.assertNotIn(raw["wav"], page)
                    self.assertNotIn(fragment["wav"], page)
                    self.assertIn(speech["wav"], page)
                    self.assertIn('data-src="edrmtone/tone-bank/tone_22.wav"', page)
                    self.assertIn("DTMF D, set 1", page)

    def test_catalog_transcript_preserves_asr_and_checks_hash(self):
        entry = {"transcript_text": "Zero", "transcript_basis": "catalog-checked-digit",
                 "intonation": "falling", "printed_page": "17-49"}
        catalog = {("pack", 1, 31, "original"): entry}
        asr = {"text": "0", "status": "transcribed", "review_recommended": True}
        clip = {"kind": "announcement", "source": "pack", "bank": 1, "label": "phrase_31",
                "pcm_sha256": "original", "content": "speech", "transcript": asr}
        other = dict(clip, pcm_sha256="different")
        self.assertTrue(transcribe.apply_nortel_transcripts([clip, other], catalog))
        self.assertEqual(clip["transcript"]["text"], "Zero")
        self.assertEqual(clip["transcript"]["asr_text"], "0")
        self.assertEqual(clip["transcript"]["intonation"], "falling")
        self.assertEqual(other["transcript"], asr)
        self.assertFalse(transcribe.apply_nortel_transcripts([clip, other], catalog))
        self.assertTrue(transcribe.apply_nortel_transcripts([clip, other], {}))
        self.assertEqual(clip["transcript"], asr)


if __name__ == "__main__":
    unittest.main()
