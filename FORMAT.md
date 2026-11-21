# Recovered EDRAM format

See the [byte map](BYTE_MAP.md) for a file-to-image walkthrough, an annotated spoken phrase, and the archive coverage audit.

This describes the examined EDRM0001 version 010 files, not every historical DRAM/EDRAM format.

## G-record transport

Every binary record is 44 bytes.

| Offset | Length | Meaning |
| --- | ---: | --- |
| 0 | 2 | ASCII G0, G2 or G6 |
| 2 | 1 | Valid payload count, 1 to 36 |
| 3 | 3 | Big-endian destination address for G0/G2 |
| 6 | count | Valid data |
| 6 + count | 1 | Checksum |
| remaining through 42 | variable | Padding |
| 43 | 1 | 0x16 terminator |

The sum from byte 2 through the checksum is 0xff modulo 256. Short-record checksums are not at fixed byte 42. G0 is the first data record, G2 continues loading, and G6 is a non-data footer. G6 has count 1 and holds a four-byte big-endian sum starting at offset 3. Add every G0/G2 payload as unsigned big-endian 16-bit words, including records that rewrite an earlier address, and keep the low 32 bits. This verifies all 59 bin44 loads in the reference archive.

Reconstruct addressed memory rather than concatenating payloads. Omitted regions are zero-filled under the factory-file policy. Apply records in order; later writes replace earlier bytes. Changed-byte rewrites occur in astd0ab, estd0aa and fstd0ba.

## S-record transport

The txt80 files contain S2 ASCII data with standard byte count, 24-bit address and one's-complement checksum. Their final S6 records have count 5 and carry a four-byte value. The bin44 payload sum also verifies `edrmtone.txt80`. The observed `mwttone.txt80` footer differs from the sum of its included records, although its individual record checksums pass. Newly encoded text loads use the sum verified against `edrmtone.txt80`. The parser also accepts ordinary S1/S3 data and S7/S8/S9 termination framing.

## Menus

Each `0x40000`-byte bank begins with a 256-byte phrase directory. The **phrase number is the slot index**, so its four-byte entry starts at `bank_base + 4 × phrase_number`. The entry gives a byte offset to the first submenu word and how many words to read in order.

| Offset in the directory entry | Width | Meaning |
| --- | ---: | --- |
| `0` | 2 bytes | Little-endian submenu byte offset relative to the bank base |
| `2` | 1 byte | Number of four-byte submenu entries |
| `3` | 1 byte | Checksum byte |

All-`FF` and all-`00` directory entries are inactive. For an active slot, the four directory bytes plus all `4 × count` selected submenu bytes sum to zero modulo 256. The submenu bytes must be present in the address records. The submenu area usually begins at `0x0100`. `EMCCS0CA` has two submenus at `0x1000–0x1027`, beyond the identifier near `0x0670`.

### Submenu entry layout

| Offset in the submenu entry | Width | Meaning |
| --- | ---: | --- |
| `0` | 2 bytes | Little-endian starting sample page |
| `2` | 1 byte | Number of consecutive pages in this range |
| `3` | 1 byte | Repeat count. The converter copies the whole range this many times. |

The converter reads `page_count × 256` sample codes starting at `bank_base + page × 0x100` and repeats that range `repeat_count` times before advancing to the next entry. At 8 kHz, 256 sample codes represent 32 ms.

For example, `ESTD0AA` bank 0 phrase 8 has directory bytes `34 01 06 20` at `0x0020`. It points to six entries starting at `0x0134`. The first two entries, `11 00 01 01` and `12 00 02 04`, say to play page `0x11` once, then play the two-page range `0x12 through 0x13` four times. The offline converter expands those sample codes to 2,304 frames, or 288 ms at 8 kHz. It uses the stored waveform and menu timing for every SIT. [Worked speech offsets](BYTE_MAP.md#follow-a-real-spoken-announcement) · [SIT playback notes](research/TONE_PLAYBACK.md)

Pages 13 and 16 in decimal commonly supply silence. Unaddressed parts of a referenced segment are supplied as zero codes and counted in the manifest. The converter flags a wholly absent non-silence segment as unavailable. [Page filenames and unwritten ranges](BYTE_MAP.md#why-a-page-can-be-missing-from-segments)

Standard SIT menus 8 through 39 combine attack pages 17, 20, 23, 26 and 29 with repeated two-page components beginning at 18, 21, 24, 27 and 30. IDs are bank-local, and phrase 8 in another pack may contain speech. SIT labels require the corresponding menu structure.

## Standalone tone banks

The archived S-record images with identifiers `TONE00AA10` and `TONE00AB10` at `0x0670` contain waveform records outside the phrase tables. Each starts with a two-byte big-endian word count, followed by twice that many bytes of companded sample data. The common records sit in a zero-padded region from `0x2100` through `0x5e93`. `TONE00AB10` also has a contiguous chain from `0x5e9e` through `0x11443`.

The exporter recognizes these regions by byte fingerprint and checks that every length word and sample byte is present in the load. The manifests record the exact header address, sample address, byte count, source hash, and selected codec for each record. Phrase and segment WAV export skips ranges that overlap identified standalone records. See [tone playback measurements](research/TONE_PLAYBACK.md) for the law assignment and measured frequencies.

## Malformed references

fstd0ba.bin44, bank 1, has these entries:

| Phrase | Raw entry | Submenu pointer |
| ---: | --- | --- |
| 8 | 36 01 06 1e | 0x0136 |
| 11 | 86 01 08 90 | 0x0186 |
| 20 | 96 02 07 a1 | 0x0296 |

They point two bytes into four-byte entries and produce invalid segment fields. Valid corresponding SIT sequences exist in bank 0, but the converter does not silently patch the source or substitute that bank.

## Decoding status

Phrase samples, including SITs and cues, expand one code per sample. The default uses standard G.711 A-law after XOR 0x55. Standalone tone records use the companding law identified for each region and retain the stored sample count and all source codes. Tone names and measured frequencies are metadata.
