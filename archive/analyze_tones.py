#!/usr/bin/env python3
"""Measure original EDRAM tone pages without modifying their samples."""
from pathlib import Path
import json
import math
import wave
import numpy as np
import edram


def expand(raw, codec):
    return np.frombuffer(edram.decode(raw, codec), dtype="<i2").astype(float)


def measure(y):
    if not len(y):
        return {}
    y=y-y.mean()
    spectrum=np.abs(np.fft.rfft(y*np.hanning(len(y)),n=65536))**2
    f=np.fft.rfftfreq(65536,1/8000)
    peak=int(np.argmax(spectrum[1:])+1)
    freq=float(f[peak])
    t=np.arange(len(y))/8000
    design=np.array([np.sin(2*np.pi*freq*t),np.cos(2*np.pi*freq*t),np.ones(len(y))]).T
    fit=design@np.linalg.lstsq(design,y,rcond=None)[0]
    residual=float(np.sum((y-fit)**2)/max(np.sum(y*y),1))
    rms=float(np.sqrt(np.mean(y*y)))
    top=np.argsort(spectrum)[-10:][::-1]
    return {"samples":len(y),"rms":rms,"peak":float(max(abs(y))),"peak_hz":freq,
            "sinusoidal_fit_residual_db":10*math.log10(max(residual,1e-20)),
            "rms_dbfs":20*math.log10(max(rms,1e-10)/32768),
            "rms_by_32_samples":[round(float(np.sqrt(np.mean(z*z))),3) for z in np.array_split(y,max(1,len(y)//32))],
            "top_fft_bins_hz":[round(float(f[k]),3) for k in top]}


def main():
    root=Path("data/original")
    output=Path("archive/measurements")
    output.mkdir(exist_ok=True)
    report={"status":"baseline measurement, not corrected playback","files":{}}
    for name in ("estd0aa","astd0ab","fstd0ba","edrmtone","mwttone","eaabs0hc"):
        suffix=".txt80" if name in ("edrmtone","mwttone") else ".bin44"
        image=edram.Image.read(root/(name+suffix))
        regions={}
        for page,pages in ((14,1),(15,1),(17,1),(18,2),(20,1),(21,2),(23,1),(24,2),(26,1),(27,2),(29,1),(30,2)):
            raw=image.read_bytes(page*256,pages*256)
            key=f"page_{page:02x}_pages_{pages}"
            regions[key]={"raw_hex":raw.hex(),"code_values":sorted(set(raw)),
                          "alaw":measure(expand(raw,"alaw-unmasked")),
                          "mulaw":measure(expand(raw,"mulaw-unmasked"))}
        phrases=image.phrases(strict=False)
        wanted=[p for p in phrases if p.bank==0 and (p.number==8 or name=="eaabs0hc" and p.number==4)]
        phrase_reports=[]
        for p in wanted:
            pcm,_=edram.render(image,p)
            y=np.frombuffer(pcm,dtype="<i2").astype(float)
            phrase_reports.append({"number":p.number,"metrics":measure(y),
                                   "segments":[{"page":s.page,"pages":s.pages,"repeats":s.repeats,
                                                "metrics":measure(expand(image.segment_bytes(p.bank,s)[0],"alaw-unmasked"))} for s in p.segments]})
        report["files"][name]={"regions":regions,"phrases":phrase_reports}
    (output/"tone-fft-baseline.json").write_text(json.dumps(report,indent=2)+"\n")
    summary={}
    for name,data in report["files"].items():
        summary[name]={key:{mode:{"peak_hz":v[mode]["peak_hz"],"rms_dbfs":v[mode]["rms_dbfs"],"fit_db":v[mode]["sinusoidal_fit_residual_db"]} for mode in ("alaw","mulaw")} for key,v in data["regions"].items()}
    (output/"tone-fft-summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary["estd0aa"],indent=2))


if __name__=="__main__":
    main()
