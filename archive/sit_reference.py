#!/usr/bin/env python3
"""Interpret Nortel SIT menus and synthesize the documented EDRAM tones."""
import argparse
from array import array
import json
import math
import os
from pathlib import Path
import sys
FREQUENCIES = {17: 913.8, 20: 985.2, 23: 1370.6, 26: 1428.5, 29: 1776.7}
SHORT_MS = 274
LONG_MS = 380
FSTD0BA_SHA256 = "aeb0d58e7c4a1db4ec09bf8d5246b7e2408654f255483e80939715b0099b99cd"


def profile(segments):
    return profile_from_entries(tuple((s["page"], s["pages"], s["repeats"]) for s in segments))


def profile_from_entries(entries):
    parts = []
    for allowed in ((17, 20), (23, 26), (29,)):
        if len(entries) < 2:
            raise ValueError("missing SIT attack or sustain")
        page = entries[0][0]
        if page not in allowed or entries[0] != (page, 1, 1):
            raise ValueError("unexpected SIT attack page")
        loop = page + 1
        if entries[1] == (loop, 2, 4):
            duration = SHORT_MS
            entries = entries[2:]
        elif entries[1:3] == ((loop, 2, 5), (loop, 1, 1)):
            duration = LONG_MS
            entries = entries[3:]
        else:
            raise ValueError("unexpected SIT sustain pattern")
        parts.append({"frequency_hz": FREQUENCIES[page], "duration_ms": duration})
    if entries:
        raise ValueError("unexpected data following the third SIT component")
    return parts


def archived_profile(segments, *, source_hash, bank, phrase):
    entries = tuple((s["page"], s["pages"], s["repeats"]) for s in segments)
    if (source_hash, bank, phrase) == (FSTD0BA_SHA256, 1, 16):
        # This exact image's bank 1 pointer starts one slot early. The final
        # sustain is just beyond its span. Bank 0 and Nortel's SIT9 agree.
        if entries == ((30, 1, 1), (17, 1, 1), (18, 2, 5), (18, 1, 1),
                       (23, 1, 1), (24, 2, 4), (29, 1, 1)):
            return profile_from_entries((*entries[1:], (30, 2, 4))), "fstd0ba-bank-0-sit9"
    return profile_from_entries(entries), "menu"


def synthesize(parts, peak=5000, *, rate=8000):
    samples=array("h")
    for p in parts:
        count = round(p["duration_ms"] * rate / 1000)
        ramp = round(rate * 0.002)
        step = math.tau * p["frequency_hz"] / rate
        for n in range(count):
            envelope = min(1.0, n / ramp, (count - 1 - n) / ramp)
            samples.append(round(peak * envelope * math.sin(step * n)))
    if sys.byteorder!="little":
        samples.byteswap()
    return samples.tobytes()


def generate(audio,output):
    import edram

    output.mkdir(parents=True,exist_ok=True)
    index={"notice":"Generated Bellcore comparison signals, not recovered EDRAM sample decoding.",
           "peak_pcm":5000,"edge_ramp_ms":2,"inter_component_gap_ms":0,
           "sources":["Bellcore SR-2275, Issue 3, December 1997, table 6-45",
                      "Nortel 297-1001-527, printed pages 4-9 through 4-11"],
           "clips":{},"profiles":{},"unsupported_menus":[]}
    for path in sorted(audio.glob("*/manifest.json")):
        m=json.loads(path.read_text(encoding="utf-8"))
        for p in m["phrases"]:
            if not p["wav"] or "_sit_" not in p["label"]:
                continue
            try:
                parts, _ = archived_profile(p["segments"], source_hash=m["source_sha256"],
                                            bank=p["bank"], phrase=p["number"])
            except (ValueError, KeyError) as exc:
                index["unsupported_menus"].append({"source":m["source"],"bank":p["bank"],"phrase":p["number"],"reason":str(exc)})
                continue
            name="_".join(f'{x["frequency_hz"]:g}Hz_{x["duration_ms"]}ms' for x in parts)+".wav"
            if name not in index["profiles"]:
                pcm=synthesize(parts)
                edram.write_wav(output/name,pcm,"GENERATED Bellcore SIT reference",
                    "Generated comparison signal, not decoded source audio; peak=5000 PCM; ramps=2ms.")
                index["profiles"][name]={"components":parts,"samples":len(pcm)//2,"duration_seconds":len(pcm)/16000}
            original=(Path(path.parent.name)/p["wav"]).as_posix()
            index["clips"][original]={"path":Path(os.path.relpath(output/name,audio)).as_posix(),"components":parts}
    (output/"index.json").write_text(json.dumps(index,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"reference_profiles":len(index["profiles"]),"mapped_original_clips":len(index["clips"])}))
    return index


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio",type=Path)
    parser.add_argument("--output",type=Path,default=Path("archive/examples/sit"))
    args=parser.parse_args()
    generate(args.audio,args.output)


if __name__=="__main__":
    main()
