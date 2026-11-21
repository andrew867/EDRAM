# EDRAM tone bytes and playback

The factory loads contain companded waveform samples. The 750 Hz cue supplies a direct byte-level example. Its sustain holds repeated samples that already follow a 750 Hz carrier when expanded as A-law. The standalone banks store individual waveforms with a length header, including DTMF pairs and a pre-mixed receiver-off-hook howler. These bytes need no oscillator frequency to recover a waveform.

## Phrase tones from menu to WAV

All offsets below refer to the reconstructed image after applying the transport records in file order.

| ESTD0AA bank 0 | Bytes | Meaning |
| --- | --- | --- |
| Phrase 1 at `0x0004` | `04 01 02 D5` | Submenu offset `0x0104`, two entries, checksum `D5` |
| Submenu at `0x0104` | `0E 00 01 02` | Page 14 at `0x0E00`, one page, repeat twice |
| Submenu at `0x0108` | `0F 00 01 03` | Page 15 at `0x0F00`, one page, repeat three times |

The last 128 bytes of page 15 are four exact copies of this 32-byte pattern.

~~~text
02 84 86 87 87 84 02 04 06 06 04 81 84 86 87 86
82 04 06 07 07 04 82 84 86 86 84 01 04 06 07 06
~~~

Unmasked A-law expands the block to 32 signed samples with three rising zero crossings in a circular traversal. That is three cycles in 4 ms, or **750 Hz**. A 32-byte period is evidence of a waveform table. The submenu supplies addresses, range lengths and repeat counts. The WAVE export repeats the 256-byte attack twice and the 256-byte sustain three times, for 1,280 frames (160 ms). It uses each page from its addressed location, including in banks where the recognizable cue bytes begin one byte earlier.

SIT phrase 8 uses attack/sustain pairs with byte addresses `0x1100 / 0x1200`, `0x1700 / 0x1800`, and `0x1D00 / 0x1E00`. Each pair plays one attack page and four copies of a two-page sustain, giving 288 ms per component in the offline model. Page 24 has a repeated 64-byte period with an 11-cycle carrier (1,375 Hz). Nortel Table 4-2 lists 288/384 ms for legacy DRAM and 274/380 ms for EDRAM. The menu's 288 ms short and 384 ms long component lengths match the legacy DRAM column. The EDRAM timing difference is a question for captured card output. [ESTD0AA export manifest](../audio/estd0aa/manifest.json) · [Nortel DRAM and EDRAM Guide, Table 4-2](https://www.gbppr.net/bsp/297-1001-527.pdf#page=59)

At 8 kHz with unmasked A-law, the last 96 samples of the 750 Hz attack measure about 3,648 PCM RMS after removing the DC mean. The last 32 samples of the sustain measure 89 PCM RMS, about 32 dB quieter. Several SIT sustains are also roughly 33 dB below their attacks, while others have a quiet onset and a sustain near the attack level. Full-block replay preserves these differences. [Archived measurements](../archive/measurements/tone-fft-summary.json)

## Standalone records

`MWTTONE` and `EDRMTONE` share 17 records. `EDRMTONE` adds 47 records, including two DTMF sets and two constant-fill records. The two-byte big-endian count at the start of each record is the number of 16-bit words of payload. Each payload word holds two eight-bit sample codes. The exporter checks the archived regions and their record boundaries, then expands samples with the region's identified companding law. In these images, records with headers below `0xB5EA` use unmasked μ-law, and the rest use unmasked A-law. The law assignment comes from the archived waveform analysis. The header has no codec selector.

| Record | Header address | Header bytes | Sample bytes | What decodes |
| --- | --- | --- | --- | --- |
| Shared record 9 | `0x379E` | `01 F2` | 996 | 1004 Hz milliwatt carrier |
| Shared record 10 | `0x3BCA` | `03 E8` | 2,000 | Four-frequency receiver-off-hook howler |
| EDRMTONE record 47 | `0xCA42` | `00 C5` | 394 | DTMF 1, second set, approximately 690 and 1218 Hz |

The 394 samples in a DTMF record can represent whole cycles of both carriers. For DTMF 1, 34 and 60 cycles in 394 samples give about 690.4 and 1,218.3 Hz. The short WAVs contain the stored blocks. Service cadence and level are properties of playback on the card. `EDRMTONE` phrase 41 spans many standalone records. The converter flags that overlap and gives each record its own WAV. Record 1 retains code `0x94` at sample index 3, while the later copy in record 18 contains `0x54` there. [EDRMTONE manifest](../audio/edrmtone/manifest.json) · [MWTTONE manifest](../audio/mwttone/manifest.json)

## What remains on the card

Northern Telecom's patent describes prerecorded tones alongside words and silence in NT1X80AA memory. The Nortel guide names `MWTTONE.AA01` as the data file for the milliwatt and receiver-off-hook feature, with separate PM firmware: `EDRMAE01` or later for NT1X80AA, or `ED16AA01` or later for NT1X80BA. The announcement/tone archive supplies the data files. For SIT specifically, Nortel documents that SITLOAD downloads voice-file data into announcement RAM and that OFCENG.PM_PCM_PROTOCOL_SELECTION selects the coding law. These sources establish what gets loaded and what the waveform bytes carry. They leave open whether firmware or dedicated logic applies the repeats, adjusts gain, or changes the phase, sample selection or cadence. [US6442246B1, description of Fig. 2](https://patents.google.com/patent/US6442246B1/en) · [Nortel DRAM and EDRAM Guide, Tone feature and chapter 14](https://www.gbppr.net/bsp/297-1001-527.pdf)

The [bench checklist](../BENCH_STATUS.md#tone-playback-test) gives a repeat-count test and the settings to record.

Historical sine references and the phase/gain-fitting experiment remain in the [archive](../archive/README.md).
