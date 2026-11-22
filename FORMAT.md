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

The sum from byte 2 through the checksum is 0xff modulo 256. Short-record checksums are not at fixed byte 42. G0 is the first data record, G2 continues loading, and G6 is a non-data footer. G6 has count 1 and holds a four-byte big-endian sum starting at offset 3. Add every G0/G2 payload as unsigned big-endian 16-bit words, including records that rewrite an earlier address, and keep the low 32 bits. The corpus verifier checks the aggregate sum for all 59 `.bin44` loads in the reference archive. The ordinary decoder validates the framing and each record's one-byte checksum.

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

For example, `ESTD0AA` bank 0 phrase 8 has directory bytes `34 01 06 20` at `0x0020`. It points to six entries starting at `0x0134`. The first two entries, `11 00 01 01` and `12 00 02 04`, say to play page `0x11` once, then play the two-page range `0x12 through 0x13` four times. The offline converter expands those sample codes to 2,304 frames, or 288 ms at 8 kHz. The announcement-load decoder uses the stored waveform and menu timing. [Worked tone offsets](BYTE_MAP.md#follow-real-tone-data) · [SIT component layout](research/TONE_PLAYBACK.md#sit-component-layout)

The native player emits 256 zero codes for page 13 even when source bytes are present. The decoder applies the same rule within a page range. It also supplies zero codes for unaddressed bytes and counts them in the manifest. Wholly unwritten page 16 remains an accepted archive silence reference, and any present page 16 bytes are copied normally. The converter flags a wholly absent non-silence segment as unavailable. [Page filenames and unwritten ranges](BYTE_MAP.md#why-a-page-can-be-missing-from-segments)

Standard SIT menus 8 through 39 combine attack pages 17, 20, 23, 26 and 29 with repeated two-page components beginning at 18, 21, 24, 27 and 30. IDs are bank-local, and phrase 8 in another pack may contain speech. SIT labels require the corresponding menu structure.

## Firmware startup RAM

The `0x0418` entry is part of the verified successful firmware-download sequence. It clears the nine protected pages in each of the first eight banks before copying the firmware's 750 Hz pages and length-prefixed waveform records. The standard announcement loader excludes write offsets `0x0700–0x0FFF` relative to the start of the load transaction. For live slot selection, replay the initialized RAM and bank type rather than reading those offsets straight from the archival load. [Startup and slot selection](research/EDRAM_BEHAVIOR_SPEC.md#firmware-download-and-startup)

## Built-in firmware SITs

The firmware directories in `ED16AA07` and `EDRMAE11` have built-in SIT slots 8 through 39, shown by the decoder as SITs 1 through 32. Each entry points to three eight-byte descriptors. Each descriptor starts with a zero word, a big-endian 24-bit waveform address, and a big-endian 24-bit duration in eight-sample units. Its waveform record starts with a big-endian word count. The sample payload is twice that count in bytes.

| Duration field | Active samples | At 8 kHz |
| --- | ---: | ---: |
| `0x000112` | 2,192 | 274 ms |
| `0x00017C` | 3,040 | 380 ms |

In the tested profile, the firmware loops the waveform to fill each duration, joins the components within the same output buffer, and zero-pads the last 256-byte staging block. Selector `0x4040` uses the descriptor addresses as stored. With `0x5050`, the first component's record address is increased by `0x80000`. The next two use their stored addresses. Both tests used runtime byte `[0x000001] = 1` with no bank-specific waveform override. [Behavior specification](research/EDRAM_BEHAVIOR_SPEC.md#built-in-tone-playback) and [firmware evidence](research/EDRAM_FIRMWARE_EVIDENCE.md)

The waveform records at their stored addresses expand as unmasked G.711 mu-law. The first record relocated by selector `0x5050` expands as unmasked G.711 A-law. The decoder picks the law per component from the resolved record. The loaded announcement tables have their own sample encoding.

The firmware's two 750 Hz cues use ordinary absolute page descriptors. Slot 1 plays page `0x400800` five times for 160 ms. Slot 2 uses the same waveform for all three bursts, with silence from startup-cleared page `0x400700`. The waveform expands as unmasked mu-law. Both recovered builds stage identical cue bytes under the tested selectors.

Use `edram.py --firmware-tones` to export the cues, continuous slots and SITs. Each finite clip's `.staged.bin` contains the exact padded codes. A continuous clip's `.record.bin` contains its original word count and payload, and its WAV contains one waveform cycle record. Use `--card-playback` with a load to apply startup RAM, the protected write exclusion, and bank-type routing. The on-wire law and gain need a card capture. [Usage](README.md#decode-built-in-firmware-sits)

## Standalone tone banks

The archived S-record images with identifiers `TONE00AA10` and `TONE00AB10` at `0x0670` contain waveform records outside the phrase tables. Each starts with a two-byte big-endian word count, followed by twice that many bytes of companded sample data. The common records sit in a zero-padded region from `0x2100` through `0x5e93`. `TONE00AB10` also has a contiguous chain from `0x5e9e` through `0x11443`.

The exporter checks each region against the known layout of record addresses and lengths and verifies that all bytes are present. The same layout applies when a waveform has been replaced in place. The manifests record the exact header address, sample address, byte count, source hash, and selected codec for each record. Phrase and segment WAV export skips ranges that overlap identified standalone records. See [tone playback measurements](research/TONE_PLAYBACK.md) for the law assignment and measured frequencies.

## Malformed references

The archived `FSTD0BA` bank 1 SIT directory differs from bank 0 in four slots. The 960 bytes containing all 32 SIT submenus (bank-relative `0x0134` through `0x04F3`) and the 3,840 bytes containing their waveforms are identical across both banks.

| Phrase (decimal) | Bank 1 directory address | Archived entry | Verified replacement |
| ---: | --- | --- | --- |
| 8 | `0x40020` | `36 01 06 1E` | `34 01 06 20` |
| 11 | `0x4002C` | `86 01 08 90` | `84 01 08 92` |
| 16 | `0x40040` | `10 02 07 31` | `14 02 07 29` |
| 20 | `0x40050` | `96 02 07 A1` | `94 02 07 A3` |

For slots 8, 11, and 20, the raw pointer starts two bytes into the intended submenu word. The raw checksum sums to zero because the shifted window drops `11 00` at the start of the first word and picks up the same two bytes from the next SIT. Subtracting two from the pointer changes the sum to `FE`. The replacement therefore changes the pointer **and** the checksum. Slot 16 starts one full word early. The original checksum still passes, but its menu begins with the previous SIT's last page and omits the final two-page sustain. The literal export is 736 ms. The corrected menu gives 960 ms, matching bank 0 and the other factory copies.

The [repair tool](repair_fstd0ba.py) accepts the hash of the archived `FSTD0BA` and writes a new `.bin44` using the four bank 0 directory entries. It checks the repaired entries against their own bank 1 submenus and rebuilds the transport checksums. Eight addressed bytes change, all in the directory. The archive and default decode retain the original data.

~~~sh
python repair_fstd0ba.py data/original/fstd0ba.bin44 FSTD0BA-fixed.bin44
python edram.py FSTD0BA-fixed.bin44 -o decoded --segments
~~~

All four recovered bank 1 WAVs match the corresponding bank 0 PCM. The repair has been checked offline. [Regression test](tests/test_repair_fstd0ba.py) · [SIT component layout](research/TONE_PLAYBACK.md#sit-component-layout)

## Decoding status

Phrase samples, including SITs and cues, expand one code per sample. The default uses standard G.711 A-law after XOR 0x55. Standalone tone records use the companding law identified for each region and retain the stored sample count and all source codes. Tone names and measured frequencies are metadata.
