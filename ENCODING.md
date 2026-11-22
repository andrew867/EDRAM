# Building a custom EDRAM voice load

`encode_edram.py` builds a new load for a single virtual announcement bank, using the archived `ESTD0AA` as its template. It carries over the reserved phrase tables below phrase 40 and their referenced tone and silence data. Assign voice WAVs or tone sequences to decimal phrase IDs 40 through 63. The remaining voice space in the bank holds 253,696 samples, or 31.712 seconds including page padding.

```sh
ffmpeg -i greeting.wav -ar 8000 -ac 1 -c:a pcm_s16le greeting-8k.wav
python encode_edram.py LABANN.bin44 --phrase 40 greeting-8k.wav
python encode_edram.py LABANN.txt80 --phrase 40 greeting-8k.wav
python edram.py LABANN.bin44 -o preview
```

Repeat `--phrase ID WAV` for other entries in the same load. The internal name defaults to the uppercase output stem and can be set with `--name`. The encoder writes a new output file and reports an error if that path already exists. Voice samples are unmasked G.711 A-law and padded to 256-sample pages. The encoder writes both record and file checksums and reads the complete result back through the decoder.

Both recovered firmware builds accepted new `.bin44` and `.txt80` loads and staged their authored sample bytes in the correct order. At startup the card supplies its own built-in samples in protected RAM. An ordinary load leaves that window in place. Full switch delivery and on-wire playback still need bench verification. `DRAMREC` can also record directly into RAM. Its `UPLOAD` format needs a switch-produced sample before it can be encoded faithfully.

## Encode tone phrases

Combine repeatable `--phrase ID WAV` and `--tone ID SPEC` arguments. A tone phrase takes stored OEM A-law codes. Separate multiple sources within one phrase with commas. The announcement format pads the sequence to the next 256-sample page.

~~~sh
python encode_edram.py LABTONE.bin44 --phrase 40 greeting-8k.wav --tone 41 cue:page:test --tone 42 sit:page:1
python encode_edram.py LABRPT.txt80 --tone 40 cue:page:test --repeat 40 4
~~~

| Tone component | Stored source |
| --- | --- |
| `cue:page:test` or `cue:page:prompt` | ESTD0AA page-based cues. The original sample levels and page skips or repeats carry into the phrase. |
| `sit:page:1` through `sit:page:32` | ESTD0AA page-based SIT sequences from slots 8 through 39. |
| `dtmf:5:2` | Key 5 from the A-law DTMF set. This embeds the waveform in an ordinary phrase with page padding. |
| `edrmtone:47` | An A-law tone-bank waveform by its one-based record index. |

The voice bank format uses A-law. The encoder rejects μ-law and mixed-law tone sources, including `howler`, `milliwatt`, `cue:test` and `sit:firmware:1`. The [firmware exporter](README.md#decode-built-in-firmware-sits) provides the original built-in tone bytes. The card plays its built-in slot 1 cue directly after a custom announcement is loaded. Factory type 1 banks also dispatch slots 4 through 39 through the firmware directory. In a custom bank with an ordinary name, those higher reserved slots follow the bank-local menus. The encoded custom slots 40 through 63 carry their stored A-law sample codes in writable pages. Use [card playback](README.md#preview-a-load-on-the-card) to check which address and law a slot will use. For native milliwatt and howler loads, use `--tone-bank` below.

`--repeat ID COUNT` stores one range and writes its native repeat count. A two-page range AB with count 4 emits ABABABAB. Padding belongs to each repetition. The count is 1 through 255 and a repeated range may span up to 255 pages.

## Rebuild a native standalone tone bank

~~~sh
python encode_edram.py MWTTONE.txt80 --tone-bank mwttone
python encode_edram.py EDRMTONE.txt80 --tone-bank edrmtone
python edram.py EDRMTONE.txt80 --raw-tones -o decoded-tones
~~~

Both rebuilds reproduce their archived input byte for byte, including addresses, native record lengths, sample codes, S-record checksums, and footer. The optional raw export contains the big-endian word count followed by its exact companded payload for every recognized tone, including constant-fill records.

EDRMTONE also supports a same-size substitution from an OEM record with the same companding law and nominal frequencies. For example, to use the OEM record 14 level variant of the 1004 Hz carrier in record 9:

~~~sh
python encode_edram.py LABTONE.txt80 --tone-bank edrmtone --replace-tone 9 edrmtone:14
~~~

The substitution retains the original tone-bank identifier and destination address and recalculates transport checksums. The firmware routes the carrier through the original slot with the replacement codes. Both recovered 68k builds loaded and replayed the tested substitution at selector `0x4040`. MWTTONE is available for unchanged rebuilds. Its archived aggregate S6 value disagrees with the sum computed from the included records, so generating a modified MWTTONE file requires a verified host-side checksum rule. [Firmware evidence](research/EDRAM_FIRMWARE_EVIDENCE.md#standalone-tone-bank-playback)

## Moving a load onto a switch

| Path | What to verify |
| --- | --- |
| EIU FTP | The EIU guide's record-length extension convention maps `.bin44` to binary with a 44-byte logical record length. Confirm the target DMS filename and logical record length on the SLM volume. Compare bytes after a round trip. |
| SLM tape | Use the [SLM tape tool and bench procedure](SLM_TAPE.md) to inspect tape images, append native entries, and build a lab tape around a `.bin44` load. The file should restore through `DISKUT` with logical record length 44 before the EDRAM is loaded. |
| Audio through an announcement recording trunk | `DRAMREC CONNECT` and `RECORD` can capture playback from a workstation fed into the provisioned headset or recording path. `PLAYBACK` verifies the result, and `UPLOAD` creates a native recovery file. |

For an EIU equipped with the 15-pin AUI paddleboard, the documented external interface is an AUI media access unit. A twisted-pair MAU and a switch port that supports 10 Mb/s half duplex provide a connection to a modern workstation. Check the MAU and `HEARTBEAT` setting together. The EIU supports both inbound and outbound FTP. Appendix C describes manually setting binary mode and `SITE LRECL 44` from a workstation when automatic record length detection is disabled.

For a factory-style bench test, stage the file under a new load name on the applicable PM load volume. Verify how that software release resolves the file in `PMLOADS`, and point `EDRAMINV` at it on a spare PROM-configured virtual announcement bank in `DRAMS`. The PM firmware name remains the `TMINV` load. At the MAP PM level, post the target DTM, busy it, run `LOADPM`, and return it to service after the load passes. Check `QUERYPM`, then assign and play the test phrase through the lab announcement path. `LOADPM` temporarily takes the target DTM out of service.

The upload and reload procedures for RAM recordings are in printed pages 12-47 through 12-62 of the [DRAM and EDRAM Guide, 297-1001-527](https://www.gbppr.net/bsp/297-1001-527.pdf). The [EIU User Guide, 297-8991-910](https://www.gbppr.net/bsp/297-8991-910.pdf), Appendix C covers FTP and logical record lengths. The Nortel *EDRAM Peripheral Module Software Release Document Voice Files*, 297-8991-597, chapter 2 covers tape staging and the voice file update procedure.
