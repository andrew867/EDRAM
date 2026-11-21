# EDRAM tone playback

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
| SIT 2, `estd0aa`, bank 0, phrase 09 | [WAV](../audio/estd0aa/bank_00/phrase_09_sit_02.wav) | [WAV](tone-demos/sit-02-restored.wav) | 288 + 288 + 384 ms |
| 750 Hz test, `eacts0ae`, bank 0, phrase 01 | [WAV](../audio/eacts0ae/bank_00/phrase_01.wav) | [WAV](tone-demos/test-750-restored.wav) | 160 ms |
| Shifted 750 Hz test, `jpdmct00`, bank 0, phrase 01 | [WAV](../audio/jpdmct00/bank_00/phrase_01.wav) | [WAV](tone-demos/test-750-restored.wav) | 160 ms |

Both restored 750 Hz examples have identical PCM. The test and three-pulse prompt menu timings correspond to the 160 ms and 992 ms cues in [US6442246B1, Table 1](https://patents.google.com/patent/US6442246B1/en). The separate [Bellcore comparison](../references/README.md) uses nominal standard timings of 274 + 274 + 380 ms for SIT 2.

```sh
python tone_playback.py data/original/estd0aa.bin44 compare/estd0aa
python tone_playback.py data/original/jpdmct00.bin44 compare/jpdmct00
```

The output contains paired WAVs and JSON with the selected addresses, durations, phase fits, gains, and any skipped menus. All 61 reference loads produced 524 WAV pairs, including 284 SIT menus. Each pair had the same frame count. `fstd0ba.bin44` bank 1 phrase 16 has an unsupported SIT-like component order and is skipped. The `eaabs0hc` operator bong uses a different waveform, including its original fade, and remains available in the [main player](../audio/listen.html).
