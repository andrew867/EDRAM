from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import edram
from archive import sit_reference

ORIGINALS = Path(__file__).resolve().parents[2] / "data" / "original"


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


if __name__ == "__main__":
    unittest.main()
