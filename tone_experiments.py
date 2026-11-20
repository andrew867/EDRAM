#!/usr/bin/env python3
"""Reject or retain explicit tone decoding hypotheses using reproducible FFT tests."""
import json
from pathlib import Path
import subprocess
import numpy as np
import edram
from analyze_tones import expand, measure


def ffmpeg(args, data):
    p=subprocess.run(["ffmpeg","-v","error"]+args,input=data,capture_output=True,check=True)
    return p.stdout


def pack(values):
    return bytes((values[i]<<4)|values[i+1] for i in range(0,len(values),2))


def main():
    image=edram.Image.read(Path("data/original/estd0aa.bin44"))
    report={"purpose":"Codec hypotheses only. No candidate changes the default decoder.","experiments":{}}
    for attack,loop,target in ((17,18,913.8),(20,21,985.2),(23,24,1370.6),(26,27,1428.5),(29,30,1776.7)):
        attack_raw=image.read_bytes(attack*256,256)
        loop_raw=image.read_bytes(loop*256,512)
        seed=edram.decode(attack_raw)
        encoded_seed=ffmpeg(["-f","s16le","-ar","8000","-ac","1","-i","pipe:0","-c:a","adpcm_g726","-b:a","32k","-f","g726","pipe:1"],seed)
        region={"target_hz":target,"direct":measure(expand(loop_raw,"alaw-unmasked")),"candidates":{}}
        for mapping in ("midrise","signmag","ones_complement"):
            codes=[]
            for raw in loop_raw:
                mag=raw&127
                if mapping=="midrise":
                    value=min(max(mag-1,0),7)|(8 if raw&128 else 0)
                elif mapping=="signmag":
                    value=(mag&7)|(8 if raw&128 else 0)
                else:
                    value=(15-min(mag,7)) if raw&128 else min(mag,7)
                codes.append(value)
            payload=encoded_seed+pack(codes)*4
            pcm=ffmpeg(["-f","g726","-code_size","4","-ar","8000","-i","pipe:0","-f","s16le","pipe:1"],payload)
            y=np.frombuffer(pcm,dtype="<i2").astype(float)
            region["candidates"]["g726_"+mapping]={"whole":measure(y),"sustain":measure(y[256:]),
                "blocks_rms":[float(np.sqrt(np.mean(z*z))) for z in np.array_split(y[256:],8)]}
        report["experiments"][str(attack)]=region
    Path("research/tone-codec-experiments.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:{n:round(c["sustain"]["peak_hz"],2) for n,c in v["candidates"].items()} for k,v in report["experiments"].items()},indent=2))


if __name__=="__main__":
    main()
