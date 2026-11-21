from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import edram
from archive import tone_playback


ORIGINALS = Path(__file__).resolve().parents[2] / "data" / "original"


class TonePlaybackTests(unittest.TestCase):
    def test_shifted_750_hz_cue_matches_the_standard_cue(self):
        images = [edram.Image.read(ORIGINALS / name) for name in ("eacts0ae.bin44", "jpdmct00.bin44")]
        restored = []
        adjustments = []
        for image in images:
            phrase = next(p for p in image.phrases(strict=False) if p.segments == tone_playback.TEST_TONE)
            pcm, components = tone_playback.restore(image, phrase, {})
            restored.append(pcm)
            adjustments.append(components[0]["address_adjustment_samples"])
        self.assertEqual(adjustments, [0, -1])
        self.assertEqual(restored[0], restored[1])
        self.assertEqual(len(restored[0]) // 2, 1280)

    def test_sit_2_restores_sustain_without_changing_menu_lengths(self):
        image = edram.Image.read(ORIGINALS / "estd0aa.bin44")
        phrase = next(p for p in image.phrases(strict=False) if p.bank == 0 and p.number == 9)
        restored, components = tone_playback.restore(image, phrase, {})
        direct, _ = edram.render(image, phrase)
        self.assertEqual(len(restored), len(direct))
        self.assertEqual([c["component_samples"] for c in components], [2304, 2304, 3072])
        self.assertEqual([c["address_adjustment_samples"] for c in components], [0, 0, 0])
        self.assertEqual([c["frequency_hz"] for c in components], [921.875, 1375.0, 1781.25])
        self.assertTrue(all(3000 <= c["restored_loop_rms"] <= 4000 for c in components))
