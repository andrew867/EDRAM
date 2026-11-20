# SIT baseline FFT findings

The baseline unmasked A-law playback has a repeat-section level defect. These measurements reproduce across the standard, French standard and standalone tone loads.

| Component | Attack frequency, Hz | Sustain frequency, Hz | Attack RMS, dBFS | Sustain RMS, dBFS |
| --- | ---: | ---: | ---: | ---: |
| First, low | 922.12 | 921.88 | -19.55 | -51.83 |
| First, high | 984.38 | 984.38 | -20.28 | -52.34 |
| Second, low | 1374.88 | 1375.00 | -20.27 | -52.88 |
| Second, high | 1437.38 | 1437.50 | -20.23 | -19.82 |
| Third | 1781.13 | 1781.25 | -20.51 | -19.90 |

The first three sustain components lose approximately 32 dB relative to the attack pages. The fourth and fifth do not. The low sustain codes span approximately 0 through 8 in magnitude, unlike the attack codes. The nominal frequencies are stable across the attack and sustain sections. Merely selecting mu-law does not remove the discrepancy.

These facts identify where the baseline render fails, but they do not identify a justified hardware decoding rule. In particular, separately normalizing every section would hide the problem rather than establish the original representation. No such normalization is applied in the converter.

Repetition interpretation, potential stateful decoding, representation changes within tone blocks, and load-time transformations remain under investigation. A known working-hardware recording or EDRAM firmware would distinguish these possibilities.

The source measurements, raw tone bytes and reproducible analysis are retained in tone-fft-baseline.json, tone-fft-summary.json and ../analyze_tones.py.

A further menu-order anomaly occurs in fstd0ba.bin44, bank 1, phrase 16. Its four-byte pointer is aligned and the additive checksum validates, but the selected component order does not match a supported three-tone SIT. The reference generator reports this case and supplies no guessed parameters. Thus 284 source entries map to 32 documented comparison profiles; one SIT-like menu remains unsupported, in addition to the three misaligned menus already rejected by the extractor.

Stateful G.726 tests seeded the decoder from the initial PCM page and tried three explicit mappings of the following codes. Their spectra were broad and inconsistent with clean SITs; no mapping corrected the representation. Results are in tone-codec-experiments.json.
