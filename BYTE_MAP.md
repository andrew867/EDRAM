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
| `EACTS0AE`, banks 0 and 1 | 435 bytes in 145 unreferenced words below offset `0x0344`. A common word is `0D 00 01 02`, equivalent to playing page 13 twice if interpreted as a submenu entry. The active directory never points to these words. Their original purpose is unknown. |
| `FSTD0BA`, bank 1 | 66 bytes in 22 words around its malformed SIT menus. Subtracting two from the three misaligned pointers gives recognizable SIT sequences. With only that adjustment, each entry plus its submenu sums to `FE` modulo 256 instead of zero. A repair would require more than moving the pointer. |

The 16-byte identifier area is structurally located, but its full meaning is open. For example, `EAOSS0AF` bank 1 contains `U1X76AF010`, and the tone loads carry `TONE00AA10` or `TONE00AB10`. The loader’s interpretation of all suffixes and fill values is unverified. Byte coverage also leaves open the hardware-specific use of the supplemental DTMF sets, the exact tone cadence and levels, and the format of native `DRAMREC UPLOAD` files. [Malformed menu entries](FORMAT.md#malformed-references) · [Bench status](BENCH_STATUS.md)
