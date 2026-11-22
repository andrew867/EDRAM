# XA-Core EDRAM firmware

`ED16AA07` and `EDRMAE11` were recovered from XA-Core FTFS volumes. The [source archive](../data/xacore/README.md) records their origins and preserves the original disk files and S-record text.

## Load the firmware

| Load | S2 records | Supplied bytes | Stub at 0x000412 jumps to | Stub at 0x000418 jumps to |
| --- | ---: | ---: | --- | --- |
| ED16AA07 | 3,449 | 54,607 | 0x011F5E | 0x011E78 |
| EDRMAE11 | 3,446 | 54,561 | 0x011F6E | 0x011E88 |

Open the [mapped ELF or flat binary files](../data/xacore/firmware/) in IDA or Ghidra. They carry a big-endian Motorola 68k mapping and name 0x000412 as a practical entry for analysis. For a raw .bin import, set the base address to **0x000400** and create code at 0x000412 and 0x000418. Each flat file is 116,054 bytes and fills absent S2 ranges with zero. [firmware/address-map.json](../data/xacore/firmware/address-map.json) records all 38 supplied byte ranges per load, the two jump targets, the output hashes and the original S6 footer. The footer supplies no verified entry address. Both outputs were checked against every byte of every S2 record.

These loads call code outside the supplied address ranges. The ELF mappings and entry labels facilitate analysis. The images lack the surrounding ROM/runtime and have no verified hardware reset vector.

Ghidra 12.2 analyzed the images with the big-endian `68000:BE:32:default` language. It identified 168 functions in ED16AA07 and 166 in EDRMAE11. The [ED16AA07 decompilation](../data/xacore/firmware/ED16AA07.ghidra.c.txt) and [EDRMAE11 decompilation](../data/xacore/firmware/EDRMAE11.ghidra.c.txt) include the entry stubs and ten selected routines per image. Ghidra inferred the variable types and calling conventions. The function names are annotations.

## What the firmware establishes

All addresses below refer to ED16AA07 unless both versions are listed. Names are descriptive labels assigned during the review.

| Address | Behavior supported by the instructions |
| --- | --- |
| 0x011978 in both loads | Takes a little-endian 24-bit destination offset from peripheral message bytes 9–11. The message payload starts at byte 12. The routine derives the bank using the high-water offset and a stride of 0x40000 bytes. |
| 0x011A2E in ED16AA07 | Computes the bank address as 0x400000 plus the bank index shifted left 18 bits. On the first write to the bank it clears seven 256-byte pages at the base and 0x3F0 pages starting at base + 0x1000. |
| 0x011A86 in ED16AA07 | The payload write excludes bank offsets 0x700–0xFFF. Bytes before and after that window can be copied, with the copy length and source pointer adjusted at the boundary. This window includes the missing cue pages. |
| 0x0117DE in both loads | Registers the bank in a directory of 32-byte entries, copies its eight-byte name and records an integrity sum. |
| 0x00EACA in both loads | Sums unsigned big-endian 16-bit words over the specified inclusive address range. Bank registration and verification apply this routine to separated ranges that exclude the internal bookkeeping area. |
| 0x01A42E / 0x01A400 | Iterates 32 bank positions at a 256 KiB stride and compares the computed sum with the directory entry. |
| 0x01A7DC / 0x01A7AE | Copies whole 256-byte pages. The underlying routine uses unrolled 68k longword moves. |

The disk's 259-byte wrapper and G records are host-side file formats. The firmware routine at 0x011978 sees the peripheral message and contained payload. Its protected region explains why replacing omitted cue bytes with source silence would lose information. Four disk backups contain audio bytes outside the pages referenced by the active menus. The [behavior specification](EDRAM_BEHAVIOR_SPEC.md) traces the loader, application queue, page repeats, and built-in tone path. The [firmware evidence](EDRAM_FIRMWARE_EVIDENCE.md) gives routine addresses and reproduction steps. On-wire PCM and interrupt timing still need a card trace.

[Nortel 297-1001-527](https://www.gbppr.net/bsp/297-1001-527.pdf), chapters 3 and 12, documents loading firmware and announcement files separately and uploading customer-recorded content.

## Reproduce the conversion

Run from the repository root.

```sh
python xacore_firmware.py data/xacore/srecords decoded/xacore/firmware
```

The [Ghidra review script](../data/xacore/firmware/ReviewEdram.java) accepts `seed` before analysis and `export <output-directory>` after analysis. Import the two files named `*.m68k.elf` as big-endian 68k ELF files. The address map keeps the firmware jump targets and the original Nortel S6 footers alongside the derived hashes.
