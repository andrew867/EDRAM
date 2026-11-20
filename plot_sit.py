#!/usr/bin/env python3
"""Plot stored SIT rendering beside its explicitly generated reference."""
from pathlib import Path
import json
import wave
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sit_reference import generate
import edram


def main():
    generate(Path("audio"),Path("references/sit"))
    image=edram.Image.read(Path("data/original/estd0aa.bin44"))
    phrase=next(p for p in image.phrases() if p.bank==0 and p.number==9)
    raw,_=edram.render(image,phrase)
    a=np.frombuffer(raw,dtype="<i2").astype(float)
    refs=json.loads(Path("references/sit/index.json").read_text())
    ref=refs["clips"]["estd0aa/bank_00/phrase_09_sit_02.wav"]["path"]
    with wave.open(str(Path("audio")/ref)) as w:
        b=np.frombuffer(w.readframes(w.getnframes()),dtype="<i2").astype(float)
    fig,axes=plt.subplots(3,1,figsize=(11,9),layout="constrained")
    def rms_envelope(y):
        width=80
        chunks=[y[i:i+width] for i in range(0,len(y),width)]
        return np.array([(i*width+len(z)/2)/8000 for i,z in enumerate(chunks)]),np.array([np.sqrt(np.mean(z*z)) for z in chunks])
    ta,ea=rms_envelope(a)
    axes[0].plot(ta,ea,linewidth=1.5)
    axes[0].fill_between(ta,ea,alpha=.2)
    axes[0].set(title="Stored EDRAM interpretation, unmasked A-law, SIT 2",ylabel="10 ms RMS (PCM)",xlabel="Time (s)",ylim=(0,4500))
    tb,eb=rms_envelope(b)
    axes[1].plot(tb,eb,linewidth=1.5,color="#168b65")
    axes[1].fill_between(tb,eb,alpha=.2,color="#168b65")
    axes[1].set(title="Generated Bellcore reference: 913.8 / 1370.6 / 1776.7 Hz, 274 / 274 / 380 ms",ylabel="10 ms RMS (PCM)",xlabel="Time (s)",ylim=(0,4500))
    for page,label in ((17,"First attack"),(18,"First sustain"),(29,"Third attack"),(30,"Third sustain")):
        size=512 if page in (18,30) else 256
        y=np.frombuffer(edram.decode(image.read_bytes(page*256,size)),dtype="<i2").astype(float)
        sp=np.abs(np.fft.rfft((y-y.mean())*np.hanning(len(y)),n=32768))
        sp=20*np.log10(np.maximum(sp/(np.sum(np.hanning(len(y)))/2)/32768,1e-9))
        freq=np.fft.rfftfreq(32768,1/8000)
        axes[2].plot(freq,sp,label=label,linewidth=1)
    axes[2].set(xlim=(500,2300),ylim=(-110,0),xlabel="Frequency (Hz)",ylabel="Amplitude (dBFS), Hann gain corrected",title="Attack and sustain spectra on the same scale")
    axes[2].legend()
    fig.savefig("research/sit-waveform-fft.svg")
    fig.savefig("research/sit-waveform-fft.png",dpi=150)


if __name__=="__main__":
    main()
