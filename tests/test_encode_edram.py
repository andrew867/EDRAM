from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edram
import encode_edram
import tone_bank


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

    def test_tone_sequence_concatenates_untouched_oem_alaw_codes(self):
        cue = encode_edram.read_tone("cue:page:test")
        image = edram.Image.read(encode_edram.TEMPLATE.with_name("edrmtone.txt80"))
        dtmf = next(raw for entry, raw in tone_bank.records(image) if entry["tone_name"] == "DTMF 5, set 2")
        self.assertEqual(encode_edram.read_tone("cue:page:test,dtmf:5:2"), cue + dtmf)

    def test_voice_encoder_rejects_non_alaw_sources(self):
        for selector in ("howler", "milliwatt", "mwttone:10", "dtmf:5", "cue:test", "sit:firmware:1:5050"):
            with self.subTest(selector=selector), self.assertRaisesRegex(ValueError, "mu-law"):
                encode_edram.read_tone(selector)

    def test_rebuild_native_banks_and_preserve_oem_waveform_bytes(self):
        originals = encode_edram.DATA / "original"
        for bank in ("mwttone", "edrmtone"):
            with self.subTest(bank=bank):
                self.assertEqual(encode_edram.build_tone_bank(bank), (originals / f"{bank}.txt80").read_bytes())

        source = edram.Image.read(originals / "edrmtone.txt80")
        original = list(tone_bank.records(source))
        rebuilt = encode_edram.build_tone_bank("edrmtone", {9: "edrmtone:14"})
        records = edram.parse_srec(rebuilt)
        updated = edram.Image(records)
        result = list(tone_bank.records(updated))
        self.assertEqual(len(result), 64)
        self.assertEqual(result[8][1], original[13][1])
        self.assertEqual(result[9:], original[9:])
        offset = original[8][0]["sample_address"]
        end = offset + len(result[8][1])
        self.assertEqual(updated.data[:offset], source.data[:offset])
        self.assertEqual(updated.data[end:], source.data[end:])
        self.assertEqual(updated.coverage, source.coverage)
        self.assertEqual(int(rebuilt.split()[-1][4:12], 16), encode_edram.word_checksum(r.data for r in records))

    def test_native_bank_rejects_invalid_replacements(self):
        for index, selector, reason in (
            (9, "howler", "same law and sample count"),
            (22, "edrmtone:46", "same law and sample count"),
            (9, "edrmtone:11", "same nominal frequencies"),
            (45, "edrmtone:14", "invalid playable tone index"),
        ):
            with self.subTest(index=index, selector=selector), self.assertRaisesRegex(ValueError, reason):
                encode_edram.build_tone_bank("edrmtone", {index: selector})
        with self.assertRaisesRegex(ValueError, "checksum rule"):
            encode_edram.build_tone_bank("mwttone", {9: "mwttone:14"})

    def test_tone_cli_mixes_with_speech_in_both_transports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav = root / "input.wav"
            edram.write_wav(wav, b"\x00\x01" * 500, "Speech fixture", "")
            for extension in ("bin44", "txt80"):
                with self.subTest(extension=extension):
                    output = root / f"LABTONE.{extension}"
                    encode_edram.main([str(output), "--phrase", "40", str(wav),
                                       "--tone", "41", "cue:page:test", "--tone", "42", "dtmf:5:2"])
                    image = edram.Image.read(output)
                    phrases = {phrase.number: phrase for phrase in image.phrases()}
                    for slot, codes in ((40, encode_edram.read_voice(wav)),
                                        (41, encode_edram.read_tone("cue:page:test")),
                                        (42, encode_edram.read_tone("dtmf:5:2"))):
                        pcm, holes = edram.render(image, phrases[slot])
                        padded = codes.ljust((len(codes) + 255) // 256 * 256, b"\0")
                        self.assertEqual((pcm, holes), (edram.decode(padded), 0))

    def test_invalid_tone_specs_and_duplicate_ids(self):
        for spec in ("", "750@160", "4000@10", "750@0", "750@1.5", "silence@31713", "edrmtone:45", "dtmf:5:3"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                encode_edram.read_tone(spec)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "LABTONE.bin44"
            with self.assertRaises(SystemExit):
                encode_edram.main([str(output), "--tone", "40", "cue:page:test", "--tone", "40", "howler"])
            self.assertFalse(output.exists())

    def test_rejects_reserved_ids_and_exhausted_bank(self):
        with self.assertRaisesRegex(ValueError, "40 to 63"):
            encode_edram.build_load("LABANN", {9: b"\x80"}, "bin44")
        with self.assertRaisesRegex(ValueError, "single-bank voice capacity"):
            encode_edram.build_load("LABANN", {40: bytes(edram.BANK_SIZE)}, "bin44")
