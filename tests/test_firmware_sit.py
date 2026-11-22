import hashlib
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

    def test_firmware_cli_exports_active_wavs_and_padded_raw_codes(self):
        path = XA_CORE / "srecords" / "ED16AA07.srec"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edram.main(["--firmware-sit", "--sit-selector", "0x5050", str(path), "-o", tmp])
            folder = root / path.stem
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["firmware_sits"]), 32)
            self.assertEqual(manifest["selector"], 0x5050)
            first = manifest["firmware_sits"][0]
            self.assertEqual([p["samples"] for p in first["components"]], [2192] * 3)
            staged = (folder / first["raw"]).read_bytes()
            self.assertEqual(len(staged), 6656)
            self.assertEqual(staged[6576:], bytes(80))
            with wave.open(str(folder / first["wav"])) as wav:
                self.assertEqual(wav.getnframes(), 6576)
                self.assertEqual(wav.readframes(6576), edram.decode(staged[:6576], manifest["preview_codec"]))
            self.assertIn(f'{path.stem}/sit_01.wav', (root / "listen.html").read_text(encoding="utf-8"))

    def test_unsupported_firmware_and_sit_numbers_are_rejected(self):
        with self.assertRaisesRegex(edram.FormatError, "unsupported built-in SIT"):
            edram.parse_firmware_sit(b"\x00\x01")
        for spec in ("sit:page:33", "sit:firmware:0"):
            with self.subTest(spec=spec), self.assertRaisesRegex(ValueError, "1 to 32"):
                encode_edram.read_tone(spec)

    def test_both_sit_sources_and_explicit_repeat_in_each_transport(self):
        page_codes = encode_edram.read_tone("sit:page:1")
        firmware_codes = encode_edram.read_tone("sit:firmware:1")
        image = edram.Image.read(encode_edram.TEMPLATE)
        reserved = {p.number: p for p in image.phrases() if p.number < 40}
        self.assertEqual(page_codes, edram.render_codes(image, reserved[8])[0])
        self.assertEqual(encode_edram.read_tone("cue:test"), edram.render_codes(image, reserved[1])[0])
        self.assertEqual(encode_edram.read_tone("cue:prompt"), edram.render_codes(image, reserved[2])[0])
        self.assertEqual(len(page_codes), 6912)
        self.assertEqual(len(firmware_codes), 6576)
        cycle = b"\x82" * 256 + b"\x96" * 256
        for transport, parse in (("bin44", edram.parse_bin44), ("txt80", edram.parse_srec)):
            with self.subTest(transport=transport):
                raw = encode_edram.build_load("LABSIT", {40: page_codes, 41: firmware_codes, 42: cycle},
                                              transport, repeats={42: 3})
                load = edram.Image(parse(raw), strict_overlaps=True)
                phrases = {p.number: p for p in load.phrases()}
                for slot in reserved:
                    self.assertEqual(phrases[slot], reserved[slot])
                    self.assertEqual(edram.render_codes(load, phrases[slot]),
                                     edram.render_codes(image, reserved[slot]))
                self.assertEqual(edram.render_codes(load, phrases[40]), (page_codes, 0))
                self.assertEqual(edram.render_codes(load, phrases[41]), (firmware_codes + bytes(80), 0))
                self.assertEqual(edram.render_codes(load, phrases[42]), (cycle * 3, 0))
                seg, = phrases[42].segments
                self.assertEqual((seg.pages, seg.repeats), (2, 3))
                self.assertEqual(len(load.data), seg.page * edram.PAGE_SIZE + len(cycle))
                self.assertEqual(encode_edram.word_checksum(r.data for r in load.records),
                                 int.from_bytes(raw[-41:-37], "big") if transport == "bin44"
                                 else int(raw.splitlines()[-1][4:12], 16))

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
