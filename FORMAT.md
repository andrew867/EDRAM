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

The examined bank spacing is 0x40000 bytes. A 64-entry, 256-byte phrase menu begins each bank.

| Relative offset | Length | Meaning |
| --- | ---: | --- |
| 0 | 2 | Little-endian submenu offset, relative to bank |
| 2 | 1 | Submenu entry count |
| 3 | 1 | Phrase checksum |

All-ff and all-zero entries are inactive. An active menu's four bytes plus every referenced submenu byte sum to zero modulo 256. Some inactive zero-filled table regions are omitted from transport. Active submenu bytes must be present.

Most submenus start at 0x100; emccs0ca extends two into 0x1000 through 0x1027. Do not assume that submenus end at the filename around 0x670.

Each submenu entry has a little-endian two-byte page number, one-byte page count and one-byte repetition count. The baseline interpretation reads at bank * 0x40000 + page * 256, takes page_count * 256 sample codes, and repeats that whole segment repeat_count times. This interpretation still requires hardware confirmation for tones.

Pages 13 and 16 commonly supply silence. Unaddressed parts of a referenced segment are zero codes and their count is recorded. Wholly absent non-silence segments are unavailable. Sparse partial dumps cannot prove completeness.

Standard SIT menus 8 through 39 combine attack pages 17, 20, 23, 26 and 29 with repeated two-page components beginning at 18, 21, 24, 27 and 30. IDs are bank-local; phrase 8 in another pack may contain speech. SIT labels require the corresponding menu structure rather than just the phrase number.

## Standalone tone banks

The archived S-record images with identifiers `TONE00AA10` and `TONE00AB10` at `0x0670` contain waveform records outside the phrase tables. Each starts with a two-byte big-endian word count, followed by twice that many bytes of companded sample data. The common records sit in a zero-padded region from `0x2100` through `0x5e93`. `TONE00AB10` also has a contiguous chain from `0x5e9e` through `0x11443`.

The exporter recognizes these regions by byte fingerprint and checks that every length word and sample byte is present in the load. The manifests record the exact header address, sample address, byte count, source hash, and selected codec for each record. See [tone playback measurements](research/TONE_PLAYBACK.md) for the law assignment and measured frequencies.

## Malformed references

fstd0ba.bin44, bank 1, has these entries:

| Phrase | Raw entry | Submenu pointer |
| ---: | --- | --- |
| 8 | 36 01 06 1e | 0x0136 |
| 11 | 86 01 08 90 | 0x0186 |
| 20 | 96 02 07 a1 | 0x0296 |

They point two bytes into four-byte entries and produce invalid segment fields. Valid corresponding SIT sequences exist in bank 0, but the converter does not silently patch the source or substitute that bank.

## Decoding status

The speech decoder expands one stored code per sample using standard G.711 A-law after XOR 0x55. Validated SIT and 750 Hz cue menus drive sine synthesis. Standalone tone bank records use the companding law identified for their region and retain the stored sample count.
