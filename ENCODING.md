# Building a custom EDRAM voice load

`encode_edram.py` builds a new load for a single virtual announcement bank, using the archived `ESTD0AA` as its template. It carries over the reserved phrase tables below phrase 40 and their referenced tone and silence data. Assign one or more voice WAVs to decimal phrase IDs 40 through 63. The remaining voice space in the bank holds 253,696 samples, or 31.712 seconds including page padding.

```sh
ffmpeg -i greeting.wav -ar 8000 -ac 1 -c:a pcm_s16le greeting-8k.wav
python encode_edram.py LABANN.bin44 --phrase 40 greeting-8k.wav
python encode_edram.py LABANN.txt80 --phrase 40 greeting-8k.wav
python edram.py LABANN.bin44 -o preview
```

Repeat `--phrase ID WAV` for other entries in the same load. The internal name defaults to the uppercase output stem and can be set with `--name`. The encoder writes a new output file and reports an error if that path already exists. Voice samples are unmasked G.711 A-law and padded to 256-sample pages. The encoder writes both record and file checksums and reads the complete result back through the decoder.

The output targets the factory-style announcement load path. Hardware acceptance on SL-100 and DMS-100 releases remains untested. `DRAMREC` can also record directly into RAM. Its `UPLOAD` format needs a switch-produced sample before it can be encoded faithfully.

## Moving a load onto a switch

| Path | What to verify |
| --- | --- |
| EIU FTP | The EIU guide's record-length extension convention maps `.bin44` to binary with a 44-byte logical record length. Confirm the target DMS filename and logical record length on the SLM volume. Compare bytes after a round trip. |
| Serial MAP terminal | A `.txt80` file is ASCII S-records. Send a short file into the switch editor with paced lines and compare the saved records with the source before loading. |
| SLM tape | The release guide uses `DISKUT` to list a cartridge and restore files to an SLM disk volume. The workstation needs the switch's tape directory, file marks and record organization as well as a compatible drive. Capture a known-good tape's records and file marks before constructing a new one. |
| Audio through an announcement recording trunk | `DRAMREC CONNECT` and `RECORD` can capture playback from a workstation fed into the provisioned headset or recording path. `PLAYBACK` verifies the result, and `UPLOAD` creates a native recovery file. |

For an EIU equipped with the 15-pin AUI paddleboard, the documented external interface is an AUI media access unit. A twisted-pair MAU and a switch port that supports 10 Mb/s half duplex provide a connection to a modern workstation. Check the MAU and `HEARTBEAT` setting together. The EIU supports both inbound and outbound FTP. Appendix C describes manually setting binary mode and `SITE LRECL 44` from a workstation when automatic record length detection is disabled.

For a factory-style bench test, stage the file under a new load name on the applicable PM load volume. Verify how that software release resolves the file in `PMLOADS`, and point `EDRAMINV` at it on a spare PROM-configured virtual announcement bank in `DRAMS`. The PM firmware name remains the `TMINV` load. At the MAP PM level, post the target DTM, busy it, run `LOADPM`, and return it to service after the load passes. Check `QUERYPM`, then assign and play the test phrase through the lab announcement path. `LOADPM` temporarily takes the target DTM out of service.

The upload and reload procedures for RAM recordings are in printed pages 12-47 through 12-62 of the [DRAM and EDRAM Guide, 297-1001-527](https://www.gbppr.net/bsp/297-1001-527.pdf). The [EIU User Guide, 297-8991-910](https://www.gbppr.net/bsp/297-8991-910.pdf), Appendix C covers FTP and logical record lengths. The Nortel *EDRAM Peripheral Module Software Release Document Voice Files*, 297-8991-597, chapter 2 covers tape staging and the voice file update procedure.
