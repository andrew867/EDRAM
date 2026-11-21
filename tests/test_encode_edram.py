from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edram
import encode_edram


class EncoderTests(unittest.TestCase):
    def test_inverse_of_every_stored_alaw_code(self):
        for code in range(256):
            self.assertEqual(encode_edram.alaw_encode(edram.alaw_sample(code)), code)

    def test_factory_footer_counts_repeated_addresses(self):
        data = encode_edram.TEMPLATE.read_bytes()
        records = edram.parse_bin44(data)
        footer = int.from_bytes(data[-41:-37], "big")
        self.assertEqual(footer, 0xd2b6f296)
        self.assertEqual(encode_edram.word_checksum(r.data for r in records), footer)
        self.assertNotEqual(encode_edram.word_checksum([edram.Image(records).data]), footer)

    def test_bin44_and_txt80_pack_the_same_voice_and_tones(self):
        voice = b"\x82\x04\x30" * 21761  # More than 255 pages.
        template = edram.Image.read(encode_edram.TEMPLATE)
        for fmt, parse in (("bin44", edram.parse_bin44), ("txt80", edram.parse_srec)):
            with self.subTest(transport=fmt):
                data = encode_edram.build_load("LABANN", {40: voice, 63: b"\x80"}, fmt)
                records = parse(data)
                image = edram.Image(records, strict_overlaps=True)
                phrases = {p.number: p for p in image.phrases()}
                self.assertEqual(image.read_bytes(0x670, 12), b"LABANN  .bin")
                self.assertEqual(image.read_bytes(0xd00, 0x1300), template.read_bytes(0xd00, 0x1300))
                self.assertEqual([s.pages for s in phrases[40].segments], [255, 1])
                self.assertEqual(set(n for n in phrases if n >= 40), {40, 63})
                pcm, holes = edram.render(image, phrases[40])
                self.assertEqual(pcm, edram.decode(voice + b"\0" * (-len(voice) % edram.PAGE_SIZE)))
                self.assertEqual(holes, 0)
                if fmt == "bin44":
                    footer = int.from_bytes(data[-41:-37], "big")
                else:
                    footer = int(data.splitlines()[-1][4:12], 16)
                self.assertEqual(footer, encode_edram.word_checksum(r.data for r in records))

    def test_rejects_reserved_ids_and_exhausted_bank(self):
        with self.assertRaisesRegex(ValueError, "40 to 63"):
            encode_edram.build_load("LABANN", {9: b"\x80"}, "bin44")
        with self.assertRaisesRegex(ValueError, "single-bank voice capacity"):
            encode_edram.build_load("LABANN", {40: bytes(edram.BANK_SIZE)}, "bin44")
