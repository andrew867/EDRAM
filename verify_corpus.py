#!/usr/bin/env python3
"""Validate a reference extraction against load files and every WAV payload."""
import argparse
import hashlib
import json
from pathlib import Path
import wave
import edram
import tone_bank


def verify(source_dir: Path, output: Path):
    result = {"sources": 0, "memory_banks": 0, "validated_phrase_menus": 0, "sit_wavs": 0,
              "cue_wavs": 0, "tone_bank_wavs": 0,
              "phrase_wavs": 0, "segment_wavs": 0, "unavailable_phrases": 0,
              "tone_bank_overlaps": 0, "invalid_menu_entries": 0, "phrase_duration_seconds": 0,
              "unit_tests": "run separately", "files": []}
    for path in edram.input_paths([str(source_dir)]):
        image = edram.Image.read(path)
        phrases = image.phrases(strict=False)
        folder = output / path.stem
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert manifest["source_sha256"] == digest, path
        assert len(manifest["phrases"]) == len(phrases), path
        assert manifest["invalid_phrases"] == image.invalid_phrases, path
        banks = len({p.bank for p in phrases})
        result["sources"] += 1
        result["memory_banks"] += banks
        result["validated_phrase_menus"] += len(phrases)
        result["invalid_menu_entries"] += len(image.invalid_phrases)
        standalone = list(tone_bank.records(image))
        ranges = tone_bank.record_ranges(entry for entry, _ in standalone)
        exported = 0
        for phrase, entry in zip(phrases, manifest["phrases"]):
            assert (entry["bank"], entry["number"]) == (phrase.bank, phrase.number)
            if entry["status"] != "exported":
                try:
                    edram.render(image, phrase, manifest["codec"])
                    edram.check_voice_ranges(phrase.bank, phrase.segments, ranges)
                except edram.FormatError as error:
                    assert entry["reason"] == str(error)
                    key = "tone_bank_overlaps" if isinstance(error, edram.ToneBankOverlap) else "unavailable_phrases"
                    result[key] += 1
                    continue
                raise AssertionError(f"unexpectedly unavailable: {path} {phrase.number}")
            edram.check_voice_ranges(phrase.bank, phrase.segments, ranges)
            expected, implicit = edram.render(image, phrase, manifest["codec"])
            with wave.open(str(folder / entry["wav"])) as wav:
                assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (8000, 1, 2)
                assert wav.getnframes() == entry["samples"] == sum(s.samples for s in phrase.segments)
                pcm = wav.readframes(wav.getnframes())
            assert pcm == expected
            assert hashlib.sha256(pcm).hexdigest() == entry["pcm_sha256"]
            assert implicit == entry["implicit_zero_samples"]
            tone = edram.tone_metadata(image, phrase, expected, manifest["codec"])
            assert all(entry[key] == value for key, value in tone.items())
            result["sit_wavs"] += "_sit_" in edram.phrase_name(phrase)
            result["cue_wavs"] += "tone_components" in tone
            result["phrase_wavs"] += 1
            result["phrase_duration_seconds"] += len(pcm) / 16000
            exported += 1
        for entry in manifest["segments"]:
            bank = entry["bank"]
            segment = edram.Segment(entry["page"], entry["pages"], 1)
            try:
                data, implicit = image.segment_bytes(bank, segment)
                edram.check_voice_ranges(bank, (segment,), ranges)
            except edram.FormatError as error:
                assert entry["status"] == "unavailable" and entry["reason"] == str(error)
                result["tone_bank_overlaps"] += isinstance(error, edram.ToneBankOverlap)
                continue
            assert entry["status"] == "exported" and entry["implicit_zero_samples"] == implicit
            with wave.open(str(folder / entry["wav"])) as wav:
                assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (8000, 1, 2)
                assert wav.getnframes() == entry["pages"] * 256
                pcm = wav.readframes(wav.getnframes())
            assert pcm == edram.decode(data, manifest["codec"])
            result["segment_wavs"] += 1
        for entry, (expected, raw) in zip(manifest.get("tone_bank", ()), standalone, strict=True):
            assert all(entry[key] == value for key, value in expected.items())
            if not entry["wav"]:
                continue
            pcm = edram.decode(raw, entry["codec"])
            with wave.open(str(folder / entry["wav"])) as wav:
                assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (8000, 1, 2)
                assert wav.getnframes() == entry["samples"]
                assert wav.readframes(wav.getnframes()) == pcm
            assert hashlib.sha256(pcm).hexdigest() == entry["pcm_sha256"]
            result["tone_bank_wavs"] += 1
        result["files"].append({"source": path.name, "sha256": digest, "banks": banks,
                                "valid_menus": len(phrases), "exported_phrases": exported,
                                "invalid_menus": image.invalid_phrases,
                                "overwritten_bytes": sum(e["changed_bytes"] for e in image.overwrites)})
    assert len(list(output.rglob("*.wav"))) == result["phrase_wavs"] + result["segment_wavs"] + result["tone_bank_wavs"], "unexpected stale WAV files"
    result["phrase_duration_seconds"] = round(result["phrase_duration_seconds"], 6)
    result["status"] = "passed"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = verify(args.source, args.output)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    main()
