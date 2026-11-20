import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edram


def g(kind, address, data):
    raw = bytes([len(data)]) + address.to_bytes(3, "big") + data
    checksum = bytes([(255 - sum(raw)) & 255])
    return kind.encode() + (raw + checksum).ljust(41, b"\0") + b"\x16"


def s(kind, address, data):
    size = {"2": 3, "6": 3, "8": 3}[kind]
    raw = bytes([size + len(data) + 1]) + address.to_bytes(size, "big") + data
    return ("S" + kind + (raw + bytes([(255 - sum(raw)) & 255])).hex() + "\n").encode()


def synthetic_image():
    menu = struct.pack("<HBB", 0x100, 2, 0)
    submenu = struct.pack("<HBBHBB", 17, 2, 2, 13, 1, 1)
    checksum = (-sum(menu + submenu)) & 255
    table = menu[:3] + bytes([checksum]) + b"\xff" * 252
    return edram.Image([
        edram.Record(0, table, "G0", 0),
        edram.Record(0x100, submenu, "G2", 44),
        edram.Record(0x1100, bytes(range(256)) * 2, "G2", 88),
    ])


class ContainerTests(unittest.TestCase):
    def test_short_record_checksum_is_not_at_fixed_byte_42(self):
        raw = g("G0", 0x1234, b"abc") + g("G6", 0xabcdef, b"\x12")
        records = edram.parse_bin44(raw)
        self.assertEqual([(r.address, r.data) for r in records], [(0x1234, b"abc")])

    def test_checksum_corruption_is_rejected(self):
        raw = bytearray(g("G0", 0, b"abc") + g("G6", 0, b"x"))
        raw[6] ^= 1
        with self.assertRaisesRegex(edram.FormatError, "checksum"):
            edram.parse_bin44(raw)

    def test_truncation_and_missing_end_are_rejected(self):
        for data in (g("G0", 0, b"abc")[:-1], g("G0", 0, b"abc")):
            with self.assertRaises(edram.FormatError):
                edram.parse_bin44(data)

    def test_srec_addresses_and_nonstandard_s6_footer(self):
        data = s("2", 0x12345, b"abc") + s("6", 0x40b421, b"\xc5")
        records = edram.parse_srec(data)
        self.assertEqual([(r.address, r.data) for r in records], [(0x12345, b"abc")])
        with self.assertRaisesRegex(edram.FormatError, "checksum"):
            edram.parse_srec(data.replace(b"616263", b"616264"))

    def test_ordered_rewrites_and_strict_overlap_mode(self):
        records = [edram.Record(100, b"abc", "G0", 0), edram.Record(101, b"de", "G2", 44)]
        image = edram.Image(records)
        self.assertEqual(image.read_bytes(100, 3), b"ade")
        self.assertEqual(image.overwrites[0]["changed_bytes"], 2)
        with self.assertRaisesRegex(edram.FormatError, "conflicting"):
            edram.Image(records, strict_overlaps=True)


class PhraseTests(unittest.TestCase):
    def test_repeat_order_and_implicit_silence(self):
        image = synthetic_image()
        phrase = image.phrases()[0]
        pcm, implicit = edram.render(image, phrase)
        expected = edram.decode(bytes(range(256)) * 2) * 2 + edram.decode(bytes(256))
        self.assertEqual(pcm, expected)
        self.assertEqual(implicit, 256)
        self.assertEqual(len(pcm) // 2, 1280)

    def test_phrase_checksum_is_independently_checked(self):
        image = synthetic_image()
        image.data[0x103] ^= 1
        with self.assertRaisesRegex(edram.FormatError, "phrase checksum"):
            image.phrases()

    def test_wholly_missing_speech_is_not_fabricated(self):
        with self.assertRaisesRegex(edram.FormatError, "unavailable"):
            synthetic_image().segment_bytes(0, edram.Segment(40, 1, 1))

    def test_missing_active_submenu_bytes_are_rejected(self):
        image = synthetic_image()
        image.coverage[0x103] = 0
        with self.assertRaisesRegex(edram.FormatError, "missing table"):
            image.phrases()

    def test_inactive_zero_table_regions_may_be_omitted(self):
        image = synthetic_image()
        image.data[128:256] = bytes(128)
        image.coverage[128:256] = bytes(128)
        self.assertEqual(len(image.phrases()), 1)

    def test_invalid_menu_is_reported_in_tolerant_mode(self):
        image = synthetic_image()
        image.data[4:8] = b"\x02\x01\x01\x00"
        self.assertEqual(len(image.phrases(strict=False)), 1)
        self.assertEqual(image.invalid_phrases[0]["number"], 1)

    def test_submenu_extension_at_0x1000(self):
        image = synthetic_image()
        submenu = image.read_bytes(256, 8)
        entry = struct.pack("<HBB", 0x1000, 2, 0)
        entry = entry[:3] + bytes([(-sum(entry + submenu)) & 255])
        other = edram.Image([
            edram.Record(0, entry + b"\xff" * 252, "G0", 0),
            edram.Record(0x1000, submenu, "G2", 44), image.records[-1],
        ])
        self.assertEqual(other.phrases()[0].menu_address, 0x1000)

    def test_oversized_phrase_is_rejected_before_rendering(self):
        submenu = struct.pack("<HBB", 17, 255, 255)
        entry = struct.pack("<HBB", 256, 1, 0)
        entry = entry[:3] + bytes([(-sum(entry + submenu)) & 255])
        image = edram.Image([
            edram.Record(0, entry + b"\xff" * 252, "G0", 0),
            edram.Record(256, submenu, "G2", 44),
        ])
        with self.assertRaisesRegex(edram.FormatError, "10-minute"):
            image.phrases()

    def test_partial_sparse_segment_is_zero_filled_and_counted(self):
        image = synthetic_image()
        image.coverage[0x1100:0x1124] = bytes(36)
        image.data[0x1100:0x1124] = bytes(36)
        data, missing = image.segment_bytes(0, edram.Segment(17, 2, 1))
        self.assertEqual(missing, 36)
        self.assertEqual(data[:36], bytes(36))

    def test_bank_local_addressing(self):
        image = synthetic_image()
        shifted = [edram.Record(r.address + edram.BANK_SIZE, r.data, r.kind, r.location) for r in image.records]
        banked = edram.Image(shifted)
        phrase = banked.phrases()[0]
        self.assertEqual(phrase.bank, 1)
        self.assertEqual(edram.render(banked, phrase), edram.render(image, image.phrases()[0]))

    def test_speech_phrase_eight_is_not_automatically_a_sit(self):
        phrase = edram.Phrase(0, 8, 0, 0, (edram.Segment(17, 80, 1),))
        self.assertEqual(edram.phrase_name(phrase), "phrase_08")

    def test_known_g711_values(self):
        self.assertEqual([edram.alaw_sample(v) for v in (0, 1, 0x10, 0x20, 0x7f, 0x80, 0xff)],
                         [-8, -24, -264, -528, -32256, 8, 32256])
        self.assertEqual([edram.mulaw_sample(v) for v in (0, 1, 0x10, 0x7f, 0x80, 0xff)],
                         [0, -8, -132, -32124, 0, 32124])

    def test_all_codes_match_independent_ffmpeg_reference(self):
        expected = {
            "alaw-unmasked": "7efdb7dabf62897e6ed84ab72a5b157aba20272f5657acef6ce77ad73bc154a7",
            "mulaw-unmasked": "e2d2c92e162fc9653ace1b29af55884317bde6ba323ac1ddd12c13b5ec03a7f5",
        }
        for codec, digest in expected.items():
            self.assertEqual(hashlib.sha256(edram.decode(bytes(range(256)), codec)).hexdigest(), digest)

    def test_pcm_wave_with_metadata_is_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            expected = edram.decode(bytes(range(256)))
            edram.write_wav(path, expected, "Test", "Source and codec")
            with wave.open(str(path)) as wav:
                self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (8000, 1, 2))
                self.assertEqual(wav.readframes(256), expected)
            self.assertIn(b"Source and codec", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
