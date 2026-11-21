# Building a custom EDRAM voice load

`encode_edram.py` builds a new load for a single virtual announcement bank, using the archived `ESTD0AA` as its template. It carries over the reserved phrase tables below phrase 40 and their referenced tone and silence data. Assign voice WAVs or tone sequences to decimal phrase IDs 40 through 63. The remaining voice space in the bank holds 253,696 samples, or 31.712 seconds including page padding.

```sh
ffmpeg -i greeting.wav -ar 8000 -ac 1 -c:a pcm_s16le greeting-8k.wav
python encode_edram.py LABANN.bin44 --phrase 40 greeting-8k.wav
python encode_edram.py LABANN.txt80 --phrase 40 greeting-8k.wav
python edram.py LABANN.bin44 -o preview
```

Repeat `--phrase ID WAV` for other entries in the same load. The internal name defaults to the uppercase output stem and can be set with `--name`. The encoder writes a new output file and reports an error if that path already exists. Voice samples are unmasked G.711 A-law and padded to 256-sample pages. The encoder writes both record and file checksums and reads the complete result back through the decoder.

The output targets the factory-style announcement load path. Hardware acceptance on SL-100 and DMS-100 releases remains untested. `DRAMREC` can also record directly into RAM. Its `UPLOAD` format needs a switch-produced sample before it can be encoded faithfully.

## Encode tone phrases

Combine repeatable `--phrase ID WAV` and `--tone ID SPEC` arguments. Each ID identifies a distinct phrase. Separate components within a tone phrase with commas. The whole phrase is padded to the next 256-sample page.

~~~sh
python encode_edram.py LABTONE.bin44 --phrase 40 greeting-8k.wav \
    --tone 41 "750@160,silence@96,350+440@250" \
    --tone 42 howler --tone 43 "dtmf:5:2"
~~~

| Tone component | Audio placed in the phrase |
| --- | --- |
| `750@160` or `350+440@250` | One or more simultaneous frequencies in Hz for a whole number of milliseconds. Frequencies must be above 0 Hz and below 4,000 Hz. |
| `silence@96` | 96 ms of silence. |
| `howler` or `milliwatt` | The shared bank's receiver off-hook howler or 1004 Hz carrier, at the stored length. |
| `dtmf:5` or `dtmf:5:2` | Key 5 from either archived DTMF set. Keys 0 through 9, A through D, star, and pound are available. Set 1 is the default. |
| `mwttone:11` or `edrmtone:62` | Any playable record by its one-based number in the Tone banks view. |

For a new user-specified tone, the encoder writes generated samples. They use a short edge taper and a combined PCM peak limit of 5,000 before quantization. Archived A-law records retain their codes. Archived mu-law records are decoded and requantized to the announcement load's A-law format. Each stored record contributes its recorded samples, so the switch's tone-service cadence and output level are outside this encoding path.

The output uses regular announcement phrase playback in either `.bin44` or `.txt80` format. The factory tone and SIT slots below 40 are retained. Use [Tone playback notes](research/TONE_PLAYBACK.md) for record measurements and hardware status.

## Moving a load onto a switch

| Path | What to verify |
| --- | --- |
| EIU FTP | The EIU guide's record-length extension convention maps `.bin44` to binary with a 44-byte logical record length. Confirm the target DMS filename and logical record length on the SLM volume. Compare bytes after a round trip. |
| SLM tape | Use the [SLM tape tool and bench procedure](SLM_TAPE.md) to inspect tape images, append native entries, and build a lab tape around a `.bin44` load. The file should restore through `DISKUT` with logical record length 44 before the EDRAM is loaded. |
| Audio through an announcement recording trunk | `DRAMREC CONNECT` and `RECORD` can capture playback from a workstation fed into the provisioned headset or recording path. `PLAYBACK` verifies the result, and `UPLOAD` creates a native recovery file. |

For an EIU equipped with the 15-pin AUI paddleboard, the documented external interface is an AUI media access unit. A twisted-pair MAU and a switch port that supports 10 Mb/s half duplex provide a connection to a modern workstation. Check the MAU and `HEARTBEAT` setting together. The EIU supports both inbound and outbound FTP. Appendix C describes manually setting binary mode and `SITE LRECL 44` from a workstation when automatic record length detection is disabled.

For a factory-style bench test, stage the file under a new load name on the applicable PM load volume. Verify how that software release resolves the file in `PMLOADS`, and point `EDRAMINV` at it on a spare PROM-configured virtual announcement bank in `DRAMS`. The PM firmware name remains the `TMINV` load. At the MAP PM level, post the target DTM, busy it, run `LOADPM`, and return it to service after the load passes. Check `QUERYPM`, then assign and play the test phrase through the lab announcement path. `LOADPM` temporarily takes the target DTM out of service.

The upload and reload procedures for RAM recordings are in printed pages 12-47 through 12-62 of the [DRAM and EDRAM Guide, 297-1001-527](https://www.gbppr.net/bsp/297-1001-527.pdf). The [EIU User Guide, 297-8991-910](https://www.gbppr.net/bsp/297-8991-910.pdf), Appendix C covers FTP and logical record lengths. The Nortel *EDRAM Peripheral Module Software Release Document Voice Files*, 297-8991-597, chapter 2 covers tape staging and the voice file update procedure.
