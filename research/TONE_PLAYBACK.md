# EDRAM tone playback

The default converter and the WAVs in the source bank folders render recognized SITs as three sine waves. The validated menu identifies each tone's pitch and short or long duration. The rendered tones use the EDRAM timings in [Nortel's Table 4-2](https://www.gbppr.net/bsp/297-1001-527.pdf#page=59). The [Appendix A table beginning at PDF page 288](https://www.gbppr.net/bsp/297-1001-527.pdf#page=288) lists the same pitches with the 288 and 384 ms DRAM timings.

| Component | Low | High |
| --- | ---: | ---: |
| First | 913.8 Hz | 985.2 Hz |
| Second | 1370.6 Hz | 1428.5 Hz |
| Third | 1776.7 Hz | |

Each EDRAM component is 274 ms or 2,192 frames when short, and 380 ms or 3,040 frames when long. The WAVs use 8 kHz mono PCM with a peak value of 5,000, a 2 ms taper at each edge, and adjacent components. Level in dBm depends on the playback path. `--raw-sit` retains direct codec expansion for byte-level analysis.

In `fstd0ba.bin44` bank 1 phrase 16, the valid-checksum pointer starts one four-byte slot early and omits the final sustain. The renderer recognizes the archived file hash and the exact anomalous menu. It uses bank 0's SIT 9 sequence, corroborated by Nortel, with 913.8 Hz for 380 ms followed by 1370.6 Hz and 1776.7 Hz for 274 ms each.

The re-export contains 285 SIT WAVs and all 32 pitch and duration profiles. An FFT audit of the 855 components measured each peak within 0.01 Hz of its specified pitch. Every component contained exactly 2,192 or 3,040 frames, including its edge tapers.

## Earlier loop experiment

In the archived text loads, all 22,036 addressed bytes of `mwttone.txt80` match the same addresses in `edrmtone.txt80` except the identifier byte at `0x0677`. Thus the shared tone region is byte-identical. Chapter 14 describes a distinct use of the NT1X80 to provide milliwatt and receiver-off-hook services, including test-trunk card emulation. The timing and output coding of those services require hardware characterization. A build of a voice load carries through the stored template tones verbatim.

The phrase menus specify byte-page addresses and repeats. This experiment uses the same menu-derived duration as the direct A-law export and models each recognized tone as an attack followed by a steady loop. It keeps the first attack page, takes a whole-cycle waveform from the stored loop, and fits loop phase and gain against the final 96 samples of the attack. A 1 ms release taper reduces clicks at transitions. This is a reconstruction from stored data. Native EDRAM hardware behavior remains unverified.

| Stored tone | Standard bank offset of loop | Measured frequency | Loop fit gain |
| --- | ---: | ---: | ---: |
| Test cue | `0x0f00` | 750 Hz | +32.14 dB |
| First SIT, low | `0x1200` | 921.875 Hz | +32.90 dB |
| First SIT, high | `0x1500` | 984.375 Hz | +32.59 dB |
| Second SIT, low | `0x1800` | 1375 Hz | +33.44 dB |
| Second SIT, high | `0x1b00` | 1437.5 Hz | 0 dB |
| Third SIT | `0x1e00` | 1781.25 Hz | 0 dB |

The six loop-to-attack correlations are at least 0.981. The first three SIT rows in the table sustain the expected frequency at roughly 33 dB below their attack. The two zero-gain SIT loops contain a quieter onset before their steady section. Repeating either full loop reintroduces the onset periodically, which adds sidebands and makes the third tone rougher. The experimental renderer repeats the steady waveform at the phase where the attack ends. The tone region is identical in `estd0aa.bin44` and `edrmtone.txt80` over addresses `0x0e00` through `0x1fff`.

The 750 Hz cue also has a separate addressing issue. Across 118 banks, its 512-byte attack and loop occur at `0x0e00` in 95 banks and precisely one byte earlier in 23 banks. The renderer adjusts that address only when all 512 candidate bytes match the standard cue fingerprint. The standard SIT components use the page addresses listed above.

| Example | Direct A-law | Restored loop | Menu duration |
| --- | --- | --- | ---: |
| SIT 2, `estd0aa`, bank 0, phrase 09 | [Historical WAV](https://github.com/andrew867/EDRAM/blob/c7933d2/audio/estd0aa/bank_00/phrase_09_sit_02.wav) | [WAV](tone-demos/sit-02-restored.wav) | 288 + 288 + 384 ms |
| 750 Hz test, `eacts0ae`, bank 0, phrase 01 | [WAV](../audio/eacts0ae/bank_00/phrase_01.wav) | [WAV](tone-demos/test-750-restored.wav) | 160 ms |
| Shifted 750 Hz test, `jpdmct00`, bank 0, phrase 01 | [WAV](../audio/jpdmct00/bank_00/phrase_01.wav) | [WAV](tone-demos/test-750-restored.wav) | 160 ms |

Both restored 750 Hz examples have identical PCM. The test and three-pulse prompt menu timings correspond to the 160 ms and 992 ms cues in [US6442246B1, Table 1](https://patents.google.com/patent/US6442246B1/en). The separate [Bellcore comparison](../references/README.md) uses nominal standard timings of 274 + 274 + 380 ms for SIT 2.

```sh
python tone_playback.py data/original/estd0aa.bin44 compare/estd0aa
python tone_playback.py data/original/jpdmct00.bin44 compare/jpdmct00
```

The experiment exports paired WAVs and JSON with addresses, durations, phase fits, gains, and skipped menus. Across the 61 reference loads it generates 524 pairs, including 284 SIT menus with the original page timings. The French pointer anomaly is omitted from the loop experiment. The `eaabs0hc` operator bong uses its stored waveform, including the fade, in the [main player](../audio/listen.html).
