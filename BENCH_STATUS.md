# EDRAM bench status

The converter, manifest generator, and SLM image writer have passed offline checks. A physical DMS-100 or SL-100 has yet to restore a generated tape image, accept a generated voice load, and play its new phrase. Record each result separately and identify the DMS software release, EDRAM firmware load, and NT1X80 card suffix.

## Verified offline

- `LABANN.tap` contains one named voice entry. Extraction reproduced the 18,216-byte `LABANN.bin44` byte for byte. The entry has 414 logical records of 44 bytes in 36 tape data blocks.
- The original `EDRM0001.loads` was reproduced byte for byte. The companion `.chksum` uses a 16-bit BSD rotating checksum and 512-byte block counts. All 61 voice and tone payload checksums matched. The SLM release procedure restores the named voice file to disk. The sidecars are host-side inventories in the documented workflow.
- The encoder currently targets one factory-style PROM bank based on `ESTD0AA`. It preserves the built-in tone and silence data and writes new speech and tone phrases into slots 40 through 63. The voice area holds 31.712 seconds including per-phrase page padding.

[Encoder and datafill procedure](ENCODING.md) · [Tape layout and release manifests](SLM_TAPE.md) · [Offline corpus results](VALIDATION.json)

## First speech load

- [ ] **Capture a native reference.** Save a known-good announcement as unmodified disk bytes, the switch-written single-file SLM tape image, and its `LISTFL FULL` output. Record the switch release and card suffix. Compare its file code, record metadata, payload word order, and final-block padding with the patch-derived `LABANN.tap`.
- [ ] **Prove delivery to disk.** Read back the written scratch cartridge, list its named voice entry on the DMS, and restore it with `DISKUT RE FILE`. Pass when the restored disk file has a 44-byte logical record length and a binary readback matching the source. If EIU FTP is available, staging over FTP can validate the disk-to-card path while the tape check stays open.
- [ ] **Prove loader acceptance.** On a spare PROM-configured virtual announcement card, confirm the block in `DRAMS`, the announcement in `EDRAMINV`, and the disk location used by `PMLOADS`. Keep the known-good peripheral firmware load in `TMINV`. Capture `LOADPM` and `QUERYPM`. Pass when the load succeeds and the intended file is present on the intended card.
- [ ] **Prove phrase playback.** Bind an external test name to the verified block and internal phrase number with `DRAMREC ASSIGN`. Play it on the lab announcement path and capture the result. Pass when the assigned phrase is intelligible and has the expected duration. Record playback after a subsequent reload separately. The two present `LABANN` phrases are 608 ms and 512 ms after page padding. `ASSIGN` uses whole seconds from 1 to 31. A four-second fixture with speech followed by silence gives exactly 32,000 samples and 125 pages at 8 kHz, which eliminates duration rounding from this test.

If the disk bytes match and the short load fails, compare against an unmodified `ESTD0AA` on the same firmware and configuration. `LABANN` ends at `0x4400` exclusive. The lowest end address across the 59 archived factory `.bin44` files is `0x39c00`. Factory files can stop inside a bank. Minimum accepted coverage for a short custom image remains unknown.

[Nortel EDRAM Voice File Release Document, chapter 2](http://www.dms-100.net/files/telephony/nortel/docs/pdf/297-8991-597.01.02.pdf#page=27) · [Nortel DRAM and EDRAM Guide, chapters 12 and 15](https://www.gbppr.net/bsp/297-1001-527.pdf)

## Follow-up research

| Open item | What would close it |
| --- | --- |
| Native `DRAMREC UPLOAD` and RAM restore | Capture an upload containing a known recording, identify its storage metadata and phrase mapping, and reload it successfully to a RAM-configured card. Factory-style PROM loads have their own acceptance test above. |
| Hardware tone level, cadence, and `EDRMTONE` usage | Capture playback from a real card to measure the output level, timing, and loop behavior. Locate a switch configuration or other operational evidence showing which service selects the two supplemental DTMF sets. The release inventory names `EDRMTONE`. The Nortel guide names `MWTTONE.AA01` for milliwatt and receiver-off-hook service. |
| `MWTTONE` aggregate footer | Explain the archived `.txt80` S6 value by obtaining an intact comparison or the loader's checksum rules. The archived file's per-record checksums and release-inventory checksum already verify. |
| `EDRM0001_INFO.txt` release checksum | Find the version of the metadata file that produced the listed value `03032`, or document the archived mismatch as final. The original tar bytes give `28684`. |
| Incomplete or malformed archive entries | Find originals containing the 17 unavailable phrase payloads and the three malformed `FSTD0BA` bank 1 menus. Keep the gaps visible in export validation. |

[Recovered file format](FORMAT.md) · [Tone playback evidence](research/TONE_PLAYBACK.md)

## Record a bench result

For each completed check, record the test date, switch release, card suffix, firmware load, transfer path, input SHA-256, disk record length and readback SHA-256, and the relevant MAP responses. For playback, also record the selected block, internal phrase number, assigned length, and captured audio duration. Retain the known-good control result alongside the generated-load result.
