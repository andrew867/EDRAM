# Superseded EDRAM interpretations

The current decoder, byte map and bench checklist describe the observations and tests that remain useful. This page records earlier leads.

| Earlier interpretation | Current evidence |
| --- | --- |
| Familiar SIT and 750 Hz menus justified replacing the exported samples with generated waveforms. | The cue's 32-byte period and the SIT sample pages already carry waveforms. The active decoder uses the sample bytes. The nominal comparisons are in [examples](examples). |
| A fitted gain and phase could reproduce the card's sustain loop. | The model fits the stored attack and sustain with a gain, phase and release taper. The card's behavior remains unmeasured. See the [historical notes](measurements/TONE_PLAYBACK_HISTORICAL.md). |
| Legacy DRAM four-bit ADPCM suggested a G.726 or IMA speech decoder for these EDRAM loads. | The archived speech expands as unmasked G.711. The [alternate codec experiments](tone_experiments.py) are exploratory. |
| Matching SIT menu durations proved reuse of legacy DRAM audio. | The offline lengths match Nortel's legacy DRAM column. The origin of the bytes and the card's physical SIT timing remain open. |
| The 750 Hz EDRAM cue might be related to the BCM T7316 low-fast ringer. | Both recordings contain 750 Hz energy. A relationship between the features has no supporting evidence. |
| Subtracting two from malformed FSTD0BA bank 1 pointers could recover the sequences. | The shifted sequences resemble SIT menus, but still checksum to FE. The active converter reports the originals as invalid. |
| SLM label offsets 172 and 178 might describe disk allocation. | Their arithmetic relationship matches the tested tapes. Disk allocation meaning remains unverified. |
| Pasting text S-records through the serial MAP editor might substitute for binary load staging. | This was an untested idea. The documented paths are EIU FTP, named SLM tape restore and native DRAMREC recording. |

The earlier tone treatment also silenced the lead-in of one Spanish CLASS busy cue and changed one code in shared tone record 1. The current export preserves both original byte sequences. [Current tone notes](../research/TONE_PLAYBACK.md)
