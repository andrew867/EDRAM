# EDRAM byte map

Read this in two address spaces. A **file offset** counts bytes in the `.bin44` or `.txt80` on disk. An **image address** tells the loader where to put decoded payload bytes. The phrase menus and audio offsets are in the image. The examples use the archived `EDRM0001` version 010 files. All address ranges below are inclusive.

## On disk, starting at byte 0

### Binary `.bin44`

Every record occupies `0x2C` bytes. In `EAOSS0AF`, the first `G0` record starts at file offset `0x0000`. It places 36 bytes at image addresses `0x0000–0x0023`, so the first nine phrase entries are already inside that record.

| Offset in a record | What it contains | First record in `EAOSS0AF` |
| --- | --- | --- |
| `0x00–0x01` | Record type | `47 30`, ASCII `G0` |
| `0x02` | Payload byte count | `24` hex, or 36 bytes |
| `0x03–0x05` | Big-endian image destination for `G0` or `G2` | `00 00 00` |
| `0x06` onward | Bytes written to the image | Starts `00 01 01 D0`, the image's first phrase entry |
| `0x06 + count` | One-byte record checksum | `C7` at offset `0x2A` |
| After checksum through `0x2A` | Padding in short records | Empty for this full record. All padding bytes in the 59 archived binary files were zero. |
| `0x2B` | Record terminator | `16` |

`G2` records continue the addressed writes. `G6` closes the file. Its count byte is `01`, offsets `0x03–0x06` hold the 32-bit big-endian payload sum, `0x07` holds the record checksum, and `0x08–0x2A` are padding. In `EAOSS0AF` the footer begins at file offset `0x96640` and starts `47 36 01 4E 56 14 A1 A5`. When records write the same address, the last write determines the final image byte. [EAOSS0AF source](data/original/eaoss0af.bin44) · [Checksum rules](FORMAT.md#g-record-transport)

### Text `.txt80`

The first two characters on disk are `S2`, ASCII bytes `53 32`. In both tone files, the first line decodes as count `1C`, address `000000`, 24 payload bytes, and checksum `0F`. The first payload bytes decode to `00 01 01 D0` at image address `0x0000`, just like the binary example. These archived files end with an `S6` footer carrying a four-byte checksum. The `MWTTONE` footer still disagrees with the calculated payload sum. [S-record details](FORMAT.md#s-record-transport)

## In the image, starting at address 0

This is the bank 0 map for `ESTD0AA`, the encoder’s reference. Image banks are `0x40000` bytes apart. Add `0x40000` to a bank-relative offset when following a bank 1 phrase. The exact extent of each used region varies by load.

| Bank-relative range | What occupies it in `ESTD0AA` |
| --- | --- |
| `0x0000–0x00FF` | Phrase directory with 64 entries of four bytes each. Each active entry has a submenu pointer, an entry count, and a checksum. |
| `0x0100–0x065B` | Active submenus. Each entry is four bytes with a little-endian page number, page count, and repeat count. |
| `0x065C–0x066F` | Twenty explicitly stored `FF` bytes between the last submenu and identifier. |
| `0x0670–0x067F` | Identifier area. `ESTD0AA` contains `ESTD0AA .bin` and four `FF` bytes. |
| `0x0680–0x0CFF` | Unwritten range in this load. |
| `0x0D00–0x0FFF` | Page 13 is a silence reference. Pages 14 and 15 hold the reused 750 Hz cue material. |
| `0x1000–0x10FF` | Unwritten page 16 in this load. `EMCCS0CA` uses `0x1000–0x1027` for two validated submenus, so the gap is load-dependent. |
| `0x1100–0x1FFF` | SIT attack and sustain pages referenced by the phrase menus. |
| `0x2000–0x20FF` | Unwritten page 32 in this load. Other loads reference page 32. |
| `0x2100–0x3FFFF` | Sample pages referenced by later phrases. Addressed records leave holes within some sample ranges. |

In the two standalone tone loads, the area at `0x2100` instead contains the common tone-bank region. The first length header is at `0x2136`. `EDRMTONE` adds records at `0x5E9E–0x11443`. These records use a big-endian word count followed by that many pairs of sample bytes. A raw phrase range can cross multiple tone records. The player uses the record boundaries to play the individual tones. [ESTD0AA export manifest](audio/estd0aa/manifest.json) · [Tone-bank layout](FORMAT.md#standalone-tone-banks)

## Follow a real spoken announcement

`EAOSS0AF` bank 1, phrase 4 (`AVRE08`) is a one-segment example. The records below are the records that supply the shown bytes.

| Step | Image address | File offset | What the bytes mean |
| --- | --- | --- | --- |
| Find phrase 4 | `0x40010` | `0x4A9EE` | `38 01 01 CB` points to bank-relative `0x0138`. It specifies one submenu entry and checksum byte `CB`. |
| Read the submenu | `0x40138` | `0x4AB56` | `BF 02 39 01` means page `0x02BF`, 57 pages, one play-through. |
| Locate the first sample | `0x6BF00` | `0x4B402` | Add `0x02BF × 0x100` to bank base `0x40000`. This `G2` payload begins with several zero codes before the voice. |
| Read the sample range | `0x6BF00–0x6F7FF` | Across multiple records | `57 × 256` gives 14,592 sample codes, or 1.824 seconds at 8 kHz. |

The converter finds five holes within that sample range, totaling 288 unwritten addresses. It fills those with zero codes and records the count. Speech uses unmasked G.711 A-law, equivalent to XOR with `0x55` before standard A-law expansion. The decoded WAV uses 16-bit mono PCM. [Phrase manifest](audio/eaoss0af/manifest.json) · [AVRE08 WAV](audio/eaoss0af/bank_01/phrase_04.wav)

## Why the file and the image have different amounts of space

The `44` in `.bin44` is the logical **record length**. Nortel’s FTP naming convention uses a numeric suffix for record length, so `.bin99` would describe a different record size in that convention. An EDRAM load carries addressed writes, and its last data record can stop inside a logical bank. In this archive, 56 of the 59 binary loads do. For example, `SMRG101C` ends just before address `0x39C00`, leaving `0x39C00–0x3FFFF` unwritten in its logical bank. Nortel describes the NT1X80 EDRAM announcement data as downloadable, with RAM used for phrase storage. The loader’s treatment of unsent addresses remains unverified. [Nortel EIU User Guide, Appendix C](https://www.gbppr.net/bsp/297-8991-910.pdf) · [Nortel DRAM and EDRAM Guide, chapters 3 and 12](https://www.gbppr.net/bsp/297-1001-527.pdf)

`ESTD0AA` illustrates how a file can be larger than its logical bank even with holes.

| Quantity | Bytes | What they represent |
| --- | ---: | --- |
| On-disk `.bin44` file length | 356,092 | All binary records, including the final `G6`. |
| Addressed payload in those records | 290,792 | Includes 31,696 bytes written to addresses already seen. |
| Data-record framing plus `G6` | 64,780 | Eight framing bytes per data record, plus the 44-byte footer. |
| Padding in short data records | 520 | Bytes carried on disk that do not write to the image. |
| Logical image bank extent | 262,144 | `0x00000–0x3FFFF`. |
| Distinct image addresses actually written | 259,096 | Payload coverage after accounting for overlapping writes. |
| Unwritten image addresses | 3,048 | No record supplies those addresses. The offline converter fills holes with zero codes where needed to render a phrase. |

The 501 bytes from the coverage audit are another quantity. They were explicitly loaded, have values other than `00` and `FF`, and fall outside the structures the audit marked. That count excludes record padding and all unwritten addresses.

`ESTD0AA` has 12 inactive phrase slots, while valid phrases already reference every sample page from `0x21` to `0x3FF`. Adding an announcement needs a directory slot, submenu space, and sample pages. The encoder makes room by rebuilding the custom-phrase area from `0x2100`, using the template’s reserved entries and tone pages. [Encoder layout](ENCODING.md) · [Loaded-byte coverage audit](#where-the-map-is-still-incomplete)

## Why a page can be missing from `segments`

`--segments` exports one single-pass WAV for each distinct referenced `(bank, starting page, page count)` range. In `bank_00_page_0012_pages_002.wav`, `0012` is **hexadecimal**, and `002` is a **decimal page count**. That file contains pages `0x12` and `0x13` together. Repeat counts live in the phrase submenus and are applied when building the full phrase. [ESTD0AA segment WAVs](audio/estd0aa/segments) · [Segment and phrase manifest](audio/estd0aa/manifest.json)

| Page in `ESTD0AA`, bank 0 | Image range | Reason for the export result |
| --- | --- | --- |
| `0x0A`, decimal 10 | `0x0A00–0x0AFF` | Unwritten, with no phrase reference. |
| `0x0D`, decimal 13 | `0x0D00–0x0DFF` | Unwritten, but referenced as silence. The exporter writes a one-page silence segment with 256 zero-filled sample codes. |
| `0x10`, decimal 16 | `0x1000–0x10FF` | Unwritten, with no phrase reference. This is the missing `page_0010` in the listing. |
| `0x13`, decimal 19 | `0x1300–0x13FF` | Written and used by ranges that start at `0x12`. No segment begins at `0x13`. |

Page `0x10` has different uses in other loads. `EAOSS0AF` references it as silence, and `EMCCS0CA` stores two submenus at the start of that page. The filename list reflects each load’s actual phrase references. [EAOSS0AF manifest](audio/eaoss0af/manifest.json) · [EMCCS0CA manifest](audio/emccs0ca/manifest.json)

## Where the map is still incomplete

The coverage audit counted distinct addresses actually supplied by the 61 archive files across 118 parsed banks. It marked the phrase directories, validated submenus, 16-byte identifier areas, the sample ranges referenced by valid phrases, and recognized tone records. An address matched by two structures was counted once. Unwritten addresses and file framing were outside the tally.

| Loaded addresses | Count |
| --- | ---: |
| Within one of the mapped structures | 24,648,110 |
| Outside those structures with value `FF` | 118,528 |
| Outside those structures with value `00` | 339 |
| Outside those structures with another value | 501 |
| **Total** | **24,767,478** |

All 501 remaining bytes occur in four-byte, submenu-shaped words in two loads. The counts below exclude `00` and `FF` bytes within those words.

| Load | What remains open |
| --- | --- |
| `EACTS0AE`, banks 0 and 1 | 435 bytes in 145 unreferenced words below offset `0x0344`. A common word is `0D 00 01 02`. No active directory entry references these words. |
| `FSTD0BA`, bank 1 | 66 bytes in 22 words around its malformed SIT menus. The original entries fail submenu validation. The decoder leaves the source bytes untouched. |

The 16-byte identifier area is structurally located, but its full meaning is open. For example, `EAOSS0AF` bank 1 contains `U1X76AF010`, and the tone loads carry `TONE00AA10` or `TONE00AB10`. The loader’s interpretation of all suffixes and fill values is unverified. Byte coverage also leaves open the hardware-specific use of the supplemental DTMF sets, the exact tone cadence and levels, and the format of native `DRAMREC UPLOAD` files. [Malformed menu entries](FORMAT.md#malformed-references) · [Bench status](BENCH_STATUS.md)
