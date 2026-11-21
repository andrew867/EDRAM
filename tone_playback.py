#!/usr/bin/env python3
"""Render A/B comparisons for source-matched EDRAM tone loops."""

import argparse
from dataclasses import asdict
import hashlib
from itertools import groupby
import json
import math
from pathlib import Path
import struct

import edram
import sit_reference


# Attack page -> (loop page count, whole-cycle period in samples, measured Hz).
# The tail of the loop contains a steady period. Its start may include quiet samples.
TONE_LAYOUT = {
    14: (1, 32, 750.0),
    17: (2, 512, 921.875),
    20: (2, 512, 984.375),
    23: (2, 64, 1375.0),
    26: (2, 128, 1437.5),
    29: (2, 256, 1781.25),
}

# The standard 750 Hz attack and loop are sometimes stored one byte earlier.
# Match the full 512 bytes before substituting either address.
TEST_TONE_SHA256 = "2b6876311c7f97ba8bd33bc8af224ae2f3484fa4146e0c2f3a11536133672f68"
TEST_TONE = (edram.Segment(14, 1, 2), edram.Segment(15, 1, 3))
PROMPT_TONE = (
    (edram.Segment(13, 1, 16),)
    + (edram.Segment(14, 1, 1), edram.Segment(15, 1, 2), edram.Segment(13, 1, 1)) * 2
    + (edram.Segment(14, 1, 1), edram.Segment(15, 1, 2), edram.Segment(13, 1, 4))
)


def samples(raw):
    return tuple(sample for (sample,) in struct.iter_unpack("<h", edram.decode(raw)))


def centered(values):
    mean = sum(values) / len(values)
    return [value - mean for value in values]


def rms(values):
    return math.sqrt(sum(value * value for value in values) / len(values))


def align_loop(attack_tail, cycle):
    """Find the loop phase and gain that best match the final attack samples."""
    reference = centered(attack_tail)
    reference_rms = rms(reference)
    if reference_rms == 0:
        raise edram.FormatError("constant tone attack")
    correlation, phase, gain = 0, 0, 0
    for position in range(len(cycle)):
        window = centered([cycle[i % len(cycle)] for i in range(position - len(reference), position)])
        window_rms = rms(window)
        if window_rms == 0:
            continue
        covariance = sum(a * b for a, b in zip(reference, window)) / len(reference)
        score = covariance / (reference_rms * window_rms)
        if score > correlation:
            correlation, phase, gain = score, position, covariance / window_rms**2
    return correlation, phase, gain


def tone_templates(image, bank, attack_page):
    pages, period, frequency = TONE_LAYOUT[attack_page]
    attack_raw, attack_holes = image.segment_bytes(bank, edram.Segment(attack_page, 1, 1))
    loop_raw, loop_holes = image.segment_bytes(bank, edram.Segment(attack_page + 1, pages, 1))
    if attack_holes > 128 or loop_holes:
        raise edram.FormatError(f"insufficient addressed audio for tone page {attack_page}")
    address = bank * edram.BANK_SIZE + attack_page * edram.PAGE_SIZE
    adjustment = 0
    if attack_page == 14 and hashlib.sha256(attack_raw + loop_raw).hexdigest() != TEST_TONE_SHA256:
        candidate = image.read_bytes(address - 1, edram.PAGE_SIZE * 2)
        if hashlib.sha256(candidate).hexdigest() == TEST_TONE_SHA256:
            attack_raw, loop_raw = candidate[:edram.PAGE_SIZE], candidate[edram.PAGE_SIZE:]
            adjustment = -1
    attack = samples(attack_raw)
    loop = samples(loop_raw)
    tail = attack[-96:]
    cycle = centered(loop[-period:])
    correlation, phase, gain = align_loop(tail, cycle)
    # Avoid applying this experiment to speech or a bank with a different tone layout.
    carrier = abs(sum(value * complex(math.cos(i * math.tau * frequency / edram.RATE),
                                      math.sin(i * math.tau * frequency / edram.RATE))
                      for i, value in enumerate(cycle)))
    if correlation < 0.95 or not 0.5 <= gain <= 65 or carrier < 0.6 * period * rms(cycle):
        raise edram.FormatError(f"waveform does not match expected tone page {attack_page}")

    return attack, cycle, {
        "attack_page": attack_page, "loop_page": attack_page + 1, "loop_period_samples": period,
        "frequency_hz": frequency, "tail_match": round(correlation, 5), "loop_start_phase": phase,
        "gain_db": round(20 * math.log10(gain), 3), "gain": gain,
        "attack_steady_rms": round(rms(centered(tail)), 2),
        "direct_loop_rms": round(rms(centered(loop)), 2),
        "restored_loop_rms": round(gain * rms(cycle), 2),
        "address_adjustment_samples": adjustment,
        "attack_address": address + adjustment,
        "loop_address": address + adjustment + edram.PAGE_SIZE,
    }


def groups_for(phrase):
    entries = phrase.segments
    if entries in (TEST_TONE, PROMPT_TONE):
        for voiced, group in groupby(entries, key=lambda segment: segment.page in (14, 15)):
            count = sum(segment.samples for segment in group)
            yield 14 if voiced else None, count
    elif "_sit_" in edram.phrase_name(phrase):
        try:
            # Check the three pitches and supported short/long menu shapes.
            sit_reference.profile([asdict(segment) for segment in entries])
        except (KeyError, ValueError) as exc:
            raise edram.FormatError("SIT-like menu has an unsupported component order") from exc
        page = None
        count = 0
        for segment in entries:
            if segment.page in TONE_LAYOUT:
                if page is not None:
                    yield page, count
                page, count = segment.page, 0
            count += segment.samples
        yield page, count


def restore(image, phrase, templates):
    output = bytearray()
    diagnostics = []
    for page, count in groups_for(phrase):
        if page is None:
            output.extend(bytes(count * 2))
            continue
        key = (phrase.bank, page)
        if key not in templates:
            templates[key] = tone_templates(image, phrase.bank, page)
        attack, cycle, info = templates[key]
        gain, phase = info["gain"], info["loop_start_phase"]
        continuation = [gain * cycle[(phase + i) % len(cycle)] for i in range(count - len(attack))]
        rendered = [*attack, *continuation]
        # Taper the final millisecond to avoid clicks at transitions or playback stop.
        for i in range(8):
            rendered[-1 - i] *= i / 8
        for value in rendered:
            output.extend(struct.pack("<h", max(-32768, min(32767, round(value)))))
        diagnostics.append({**info, "component_samples": count})
    return bytes(output), diagnostics


def export(source, output):
    image = edram.Image.read(source)
    results = {"source": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "interpretation": "experimental loop restoration from the stored waveform and menu timing",
               "comparisons": [], "skipped": []}
    templates = {}
    for phrase in image.phrases(strict=False):
        try:
            restored, diagnostics = restore(image, phrase, templates)
        except edram.FormatError as exc:
            results["skipped"].append({"bank": phrase.bank, "phrase": phrase.number, "reason": str(exc)})
            continue
        if not restored:
            continue
        filename = f"bank_{phrase.bank:02d}_{edram.phrase_name(phrase)}"
        direct, _ = edram.render(image, phrase)
        if len(direct) != len(restored):
            raise ValueError(f"restoration changed menu timing for {filename}")
        paths = {"direct_wav": filename + "_direct.wav", "restored_wav": filename + "_restored.wav"}
        edram.write_wav(output / paths["direct_wav"], direct, filename, "Direct EDRAM A-law expansion")
        edram.write_wav(output / paths["restored_wav"], restored, filename,
                        "Experimental phase-aligned EDRAM loop restoration; original hardware playback is unverified")
        results["comparisons"].append({**paths, "samples": len(restored) // 2, "components": diagnostics})
    output.mkdir(parents=True, exist_ok=True)
    (output / "tone-restoration.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = export(args.source, args.output)
    print(f"{len(result['comparisons'])} tone comparisons, {len(result['skipped'])} skipped")


if __name__ == "__main__":
    main()
