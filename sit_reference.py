#!/usr/bin/env python3
"""Generate explicitly labelled Bellcore SIT comparison signals from validated menus."""
import argparse
from array import array
import json
import math
from pathlib import Path
import sys
import edram

FREQUENCIES = {17:913.8,20:985.2,23:1370.6,26:1428.5,29:1776.7}
DURATION_MS = {9:274,12:380}


def profile(segments):
    groups=[]
    for s in segments:
        if s["page"] in FREQUENCIES and s["pages"]==1 and s["repeats"]==1:
            groups.append({"page":s["page"],"blocks":1})
        elif groups and s["page"]==groups[-1]["page"]+1:
            groups[-1]["blocks"]+=s["pages"]*s["repeats"]
        else:
            raise ValueError("menu does not match the supported SIT component structure")
    if len(groups)!=3 or groups[0]["page"] not in (17,20) or groups[1]["page"] not in (23,26) or groups[2]["page"]!=29:
        raise ValueError("menu does not contain a valid three-component SIT")
    return [{"frequency_hz":FREQUENCIES[g["page"]],"duration_ms":DURATION_MS[g["blocks"]]} for g in groups]


def synthesize(parts,peak=5000):
    samples=array("h")
    for p in parts:
        count=round(p["duration_ms"]*edram.RATE/1000)
        for n in range(count):
            envelope=min(1.0,n/16,(count-1-n)/16)
            samples.append(round(peak*envelope*math.sin(2*math.pi*p["frequency_hz"]*n/edram.RATE)))
    if sys.byteorder!="little":
        samples.byteswap()
    return samples.tobytes()


def generate(audio,output):
    output.mkdir(parents=True,exist_ok=True)
    index={"notice":"Generated Bellcore comparison signals, not recovered EDRAM sample decoding.",
           "peak_pcm":5000,"edge_ramp_ms":2,"inter_component_gap_ms":0,
           "sources":["Bellcore SR-2275, Issue 3, December 1997, table 6-45",
                      "Nortel 297-1001-527, printed pages 4-9 through 4-11"],
           "clips":{},"profiles":{}}
    for path in sorted(audio.glob("*/manifest.json")):
        m=json.loads(path.read_text(encoding="utf-8"))
        for p in m["phrases"]:
            if not p["wav"] or "_sit_" not in p["label"]:
                continue
            parts=profile(p["segments"])
            name="_".join(f'{x["frequency_hz"]:g}Hz_{x["duration_ms"]}ms' for x in parts)+".wav"
            if name not in index["profiles"]:
                pcm=synthesize(parts)
                edram.write_wav(output/name,pcm,"GENERATED Bellcore SIT reference",
                    "Generated comparison signal, not decoded source audio; peak=5000 PCM; ramps=2ms.")
                index["profiles"][name]={"components":parts,"samples":len(pcm)//2,"duration_seconds":len(pcm)/16000}
            original=(Path(path.parent.name)/p["wav"]).as_posix()
            index["clips"][original]={"path":(Path("..")/output/name).as_posix(),"components":parts}
    (output/"index.json").write_text(json.dumps(index,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"reference_profiles":len(index["profiles"]),"mapped_original_clips":len(index["clips"])}))
    return index


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio",type=Path)
    parser.add_argument("--output",type=Path,default=Path("references/sit"))
    args=parser.parse_args()
    generate(args.audio,args.output)


if __name__=="__main__":
    main()
