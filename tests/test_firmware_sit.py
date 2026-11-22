from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import edram
import encode_edram
import firmware_sit


XA_CORE = encode_edram.DATA / "xacore"
FIRMWARE = XA_CORE / "firmware"


class FirmwareSITTests(unittest.TestCase):
    def test_srec_and_flat_codes_match_native_staging(self):
        vectors = json.loads((FIRMWARE / "playback-vectors.json").read_text(encoding="utf-8"))
        for name in vectors["firmware_sha256"]:
            srec = (XA_CORE / "srecords" / f"{name}.srec").read_bytes()
            flat = (FIRMWARE / f"{name}.base-000400.bin").read_bytes()
            primary = vectors["builtin_tones"]
            alternate = primary["alternate_selector"]
            for selector, cases in ((primary["selector"], primary["slots"]),
                                    (alternate["value"], alternate["slots"])):
                firmware = edram.parse_firmware_sit(srec, selector)
                flat_firmware = edram.parse_firmware_sit(flat, selector)
                for case in cases:
                    with self.subTest(firmware=name, selector=selector, slot=case["slot"]):
                        tone = firmware.sit(case["slot"] - 7)
                        self.assertEqual(tone, flat_firmware.sit(tone.number))
                        self.assertEqual(len(tone.codes), case["active_codes"])
                        self.assertEqual(hashlib.sha256(tone.codes).hexdigest(), case["active_sha256"])
                        staged = tone.codes.ljust(case["staged_bytes"], b"\0")
                        self.assertEqual(hashlib.sha256(staged).hexdigest(), case["staged_sha256"])
                        delta = [p.record_address - p.stored_address for p in tone.components]
                        self.assertEqual(delta, [0, 0, 0] if selector == 0x4040 else [0x80000, 0, 0])
                        first_codec = firmware_sit.ALAW if selector == 0x5050 else firmware_sit.MULAW
                        self.assertEqual([p.codec for p in tone.components],
                                         [first_codec, firmware_sit.MULAW, firmware_sit.MULAW])

    def test_firmware_cli_exports_active_wavs_and_padded_raw_codes(self):
        path = XA_CORE / "srecords" / "ED16AA07.srec"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edram.main(["--firmware-sit", "--sit-selector", "0x5050", str(path), "-o", tmp])
            folder = root / path.stem
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["firmware_sits"]), 32)
            self.assertEqual([t["slot"] for t in manifest["firmware_continuous"]], [4, 5, 6, 7])
            self.assertEqual(len(manifest["startup_copies"]), 4)
            self.assertEqual(manifest["selector"], 0x5050)
            first = manifest["firmware_sits"][0]
            self.assertEqual([p["samples"] for p in first["components"]], [2192] * 3)
            staged = (folder / first["raw"]).read_bytes()
            self.assertEqual(len(staged), 6656)
            self.assertEqual(staged[6576:], bytes(80))
            with wave.open(str(folder / first["wav"])) as wav:
                self.assertEqual(wav.getnframes(), 6576)
                self.assertEqual(manifest["preview_codec"], "per-component")
                expected = edram.decode(staged[:2192], "alaw-unmasked")
                expected += edram.decode(staged[2192:6576], "mulaw-unmasked")
                self.assertEqual(wav.readframes(6576), expected)
            self.assertIn(f'{path.stem}/sit_01.wav', (root / "listen.html").read_text(encoding="utf-8"))

    def test_builtin_cues_replay_original_pages(self):
        vectors = json.loads((FIRMWARE / "playback-vectors.json").read_text(encoding="utf-8"))
        for name in vectors["firmware_sha256"]:
            image = (XA_CORE / "srecords" / f"{name}.srec").read_bytes()
            for selector in firmware_sit.SELECTORS:
                firmware = edram.parse_firmware_sit(image, selector)
                for case in vectors["builtin_cues"]:
                    cue = firmware.cue(case["slot"])
                    self.assertEqual(len(cue.codes), case["samples"])
                    self.assertEqual(hashlib.sha256(cue.codes).hexdigest(), case["staged_sha256"])
                    self.assertEqual([a for part in cue.components
                                      for a in [part.page_address] * part.repeats], case["page_addresses"])
                    pcm = edram.render_firmware_tone(cue)
                    self.assertEqual(pcm, edram.decode(cue.codes, firmware_sit.MULAW))
                    if cue.slot == 1:
                        self.assertEqual(cue.codes, cue.codes[:256] * 5)
                        self.assertEqual(cue.codes[:256], cue.codes[:32] * 8)
                    else:
                        self.assertEqual(pcm[:16 * 256 * 2], bytes(16 * 256 * 2))

    def test_unsupported_firmware_and_sit_numbers_are_rejected(self):
        with self.assertRaisesRegex(edram.FormatError, "unsupported built-in SIT"):
            edram.parse_firmware_sit(b"\x00\x01")
        for spec in ("sit:page:33", "sit:firmware:0"):
            with self.subTest(spec=spec), self.assertRaisesRegex(ValueError, "1 to 32"):
                encode_edram.read_tone(spec)

    def test_archived_sits_and_explicit_repeat_in_each_transport(self):
        short_sit = encode_edram.read_tone("sit:page:1")
        long_sit = encode_edram.read_tone("sit:page:32")
        image = edram.Image.read(encode_edram.TEMPLATE)
        reserved = {p.number: p for p in image.phrases() if p.number < 40}
        self.assertEqual(short_sit, edram.render_codes(image, reserved[8])[0])
        self.assertEqual(long_sit, edram.render_codes(image, reserved[39])[0])
        self.assertEqual(encode_edram.read_tone("cue:page:test"), edram.render_codes(image, reserved[1])[0])
        self.assertEqual(encode_edram.read_tone("cue:page:prompt"), edram.render_codes(image, reserved[2])[0])
        cycle = short_sit[:512]
        for transport, parse in (("bin44", edram.parse_bin44), ("txt80", edram.parse_srec)):
            with self.subTest(transport=transport):
                raw = encode_edram.build_load("LABSIT", {40: short_sit, 41: long_sit, 42: cycle},
                                              transport, repeats={42: 3})
                load = edram.Image(parse(raw), strict_overlaps=True)
                phrases = {p.number: p for p in load.phrases()}
                for slot in reserved:
                    self.assertEqual(phrases[slot], reserved[slot])
                    self.assertEqual(edram.render_codes(load, phrases[slot]),
                                     edram.render_codes(image, reserved[slot]))
                self.assertEqual(edram.render_codes(load, phrases[40]), (short_sit, 0))
                self.assertEqual(edram.render_codes(load, phrases[41]), (long_sit, 0))
                self.assertEqual(edram.render_codes(load, phrases[42]), (cycle * 3, 0))
                seg, = phrases[42].segments
                self.assertEqual((seg.pages, seg.repeats), (2, 3))
                self.assertEqual(len(load.data), seg.page * edram.PAGE_SIZE + len(cycle))
                self.assertEqual(encode_edram.word_checksum(r.data for r in load.records),
                                 int.from_bytes(raw[-41:-37], "big") if transport == "bin44"
                                 else int(raw.splitlines()[-1][4:12], 16))


    def test_card_playback_selects_firmware_or_bank_by_type(self):
        firmware = edram.parse_firmware_sit((XA_CORE / "srecords" / "ED16AA07.srec").read_bytes(), 0x5050)
        archived = edram.Image.read(encode_edram.TEMPLATE)
        factory = edram.CardPlayback(archived, firmware, first_bank=1)
        self.assertEqual(factory.bank_type, 1)
        self.assertEqual(factory.phrase(1, 1), firmware.cue(1))
        self.assertEqual(factory.phrase(1, 8), firmware.sit(1))
        self.assertEqual(factory.phrase(1, 7).components[0].record_address, 0x4C0700)
        self.assertEqual(factory.phrase(1, 7).components[0].codec, firmware_sit.ALAW)

        codes = encode_edram.read_tone("cue:page:test")
        authored = encode_edram.build_load("LABANN", {40: codes}, "bin44")
        custom = edram.CardPlayback(edram.Image(edram.parse_bin44(authored)), firmware, first_bank=1)
        self.assertEqual(custom.bank_type, 0)
        self.assertEqual(custom.phrase(1, 1), firmware.cue(1))
        self.assertEqual(custom.phrase(1, 8).codes, encode_edram.read_tone("sit:page:1"))
        self.assertEqual(custom.phrase(1, 40).codes, codes)
        self.assertEqual(custom.read(0x440700, 0x900), firmware.startup_read(0x440700, 0x900))

    def test_card_cli_exports_native_continuous_records(self):
        path = encode_edram.DATA / "original" / "mwttone.txt80"
        with tempfile.TemporaryDirectory() as tmp:
            edram.main(["--first-bank", "1", "--slot", "42",
                        "--slot", "49", str(path), "-o", tmp])
            folder = Path(tmp) / path.stem
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["bank_type"], 2)
            self.assertEqual(manifest["firmware"], "ED16AA07")
            self.assertEqual(manifest["selector"], 0x4040)
            self.assertEqual(manifest["load_header"]["offset"], 0x670)
            self.assertEqual(bytes.fromhex(manifest["load_header"]["hex"]), b"TONE00AA10\xff\xff")
            self.assertEqual(len(manifest["startup_copies"]), 4)
            for part, address, samples in zip(manifest["card_slots"], (0x3BCA, 0x379E), (2000, 996), strict=True):
                entry, = part["components"]
                self.assertEqual(entry["record_address"], 0x440000 + address)
                self.assertEqual(entry["codec"], firmware_sit.MULAW)
                self.assertTrue(part["continuous"])
                self.assertNotIn("duration_seconds", part)
                raw = edram.Image.read(path).read_bytes(address, samples + 2, required=True)
                self.assertEqual((folder / part["raw"]).read_bytes(), raw)
                with wave.open(str(folder / part["wav"])) as wav:
                    self.assertEqual(wav.getnframes(), samples)
                    self.assertEqual(wav.readframes(samples), edram.decode(raw[2:], firmware_sit.MULAW))

    def test_default_inspection_uses_firmware_sit_and_file_only_retains_page_menu(self):
        def manifest(*options):
            output = io.StringIO()
            with redirect_stdout(output):
                edram.main([str(encode_edram.TEMPLATE), "--inspect", *options])
            return json.loads(output.getvalue())

        card = manifest("--slot", "8")
        self.assertEqual((card["firmware"], card["selector"], card["first_bank"], card["bank_type"]),
                         ("ED16AA07", 0x4040, 0, 1))
        self.assertEqual(card["load_header"]["ascii"], "ESTD0AA .bin")
        sit, = card["card_slots"]
        self.assertEqual((sit["label"], sit["samples"]), ("Built-in SIT 01", 6576))

        archive = manifest("--as-stored")
        stored = next(p for p in archive["phrases"] if (p["bank"], p["number"]) == (0, 8))
        self.assertEqual(sum(s["pages"] * s["repeats"] * edram.PAGE_SIZE for s in stored["segments"]), 6912)
        self.assertEqual(manifest("--segments"), archive)

    def test_repeat_rejects_unaddressable_ranges(self):
        for codes, repeats, error in ((b"\x82", {41: 2}, "refer to an authored phrase"),
                                      (b"\x82", {40: 256}, "1 to 255"),
                                      (bytes(256 * 256), {40: 2}, "255-page"),
                                      (bytes(256 * 255), {40: 255}, "10-minute")):
            with self.subTest(repeats=repeats), self.assertRaisesRegex(ValueError, error):
                encode_edram.build_load("LABSIT", {40: codes}, "bin44", repeats=repeats)

    def test_page_13_is_zeroed_even_when_present_and_page_16_is_not(self):
        payload = b"\x17" * 256 + b"\x28" * 256 + b"\x39" * 256 + b"\x4A" * 256
        image = edram.Image([edram.Record(0xD00, payload, "G0", 0)])
        self.assertEqual(image.segment_bytes(0, edram.Segment(13, 4, 1)), (bytes(256) + payload[256:], 0))
        self.assertEqual(image.segment_bytes(0, edram.Segment(16, 1, 1)), (payload[-256:], 0))
