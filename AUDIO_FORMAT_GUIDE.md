# How EDRAM stores announcements and tones

An EDRAM audio load is a set of writes to specific addresses in the card’s data store. Once those writes are applied, the resulting image contains sample bytes and the structures that tell the card which bytes to play. This guide follows the `EDRM0001` version 010 archive. Nortel describes announcement data and the card’s application firmware as separate loads. [Nortel DRAM and EDRAM Guide, chapter 3](https://www.gbppr.net/bsp/297-1001-527.pdf)

## From file to audio

| File | What it carries |
| --- | --- |
| `.bin44` | Fixed 44-byte binary records. `G0` and `G2` carry an address and payload. `G6` carries a file checksum. |
| `.txt80` | Text S-records. The archived tone files use `S2` for addressed bytes and `S6` for the footer. |
| `.loads` and `.chksum` | Release inventory and package checksum files. A `.loads` entry names a file. A `.chksum` entry checks the bytes of that file as distributed. |
| `.wav` | The converter’s output. It contains 8 kHz, 16-bit mono PCM ready to listen to. |

The record address determines where its bytes go, and a later write can replace an earlier one. The converter reconstructs the image before looking up any phrase. The transport extension identifies the record framing. The structures inside the image determine how audio is found. [Record fields and checksums](FORMAT.md) · [Release inventories](SLM_TAPE.md#release-manifests-and-the-slm-restore-path)

## A spoken phrase is a list of sample ranges

Each bank begins with 64 four-byte phrase entries. An active entry points to a submenu. Each four-byte submenu entry specifies a starting page, the number of consecutive pages to read, and how many times to repeat that range. One page holds 256 sample codes, or 32 ms at 8 kHz. The same range can appear in multiple phrases.

Take `EAOSS0AF`, bank 1, phrase 4. Nortel calls this phrase `AVRE08`, “Has been temporarily disconnected.” Its path through the file is short enough to follow by hand. [Nortel phrase catalog, PDF page 307](https://www.gbppr.net/bsp/297-1001-527.pdf#page=307) · [Export manifest](audio/eaoss0af/manifest.json)

| Step | Bytes or result |
| --- | --- |
| Find phrase 4 | Bank 1 starts at `0x40000`. Its phrase 4 entry starts at `0x40010`. |
| Read the phrase entry | `38 01 01 CB` points to bank-relative offset `0x0138`, with one submenu entry and checksum byte `CB`. |
| Read the submenu | `BF 02 39 01` means page `0x02BF`, 57 pages, play once. |
| Read and decode | The range starts at `0x6BF00`. It covers 14,592 sample codes and plays for 1.824 seconds. |

Speech uses unmasked G.711 A-law in these files. XOR each stored byte with `0x55` before passing it to a standard A-law decoder. The manifest tracks zero-fill for sparse regions. A wholly absent speech segment is flagged as unavailable. Recorded cues such as the calling-card bong also use phrase ranges. [Sample addressing and sparse data](FORMAT.md#menus) · [Recorded cue examples](research/TONE_PLAYBACK.md#cues-in-the-phrase-tables)

## SITs and the 750 Hz cues use phrase menus too

The factory SIT menus reuse short attack and sustain ranges. In `ESTD0AA`, bank 0, phrase 8, the first component plays page 17 once, followed by four repetitions of the two-page range starting at page 18. Similar pairs select the other two pitches. Expanding those pages directly gives 288 ms per component. For the default WAV, the converter recognizes the menu and renders SIT 1 at 913.8, 1370.6, and 1776.7 Hz, each for 274 ms, using Nortel’s EDRAM timing. The recognized 750 Hz test and prompt cues also use waveform synthesis in the default export. [ESTD0AA manifest](audio/estd0aa/manifest.json) · [Nortel Table 4-2](https://www.gbppr.net/bsp/297-1001-527.pdf#page=59) · [Playback measurements](research/TONE_PLAYBACK.md)

## Standalone tone banks have their own record boundaries

`MWTTONE` and `EDRMTONE` share 17 waveform records. `EDRMTONE` adds 47 records, including two sets of 16 DTMF keys and two constant-fill records. Each tone header contains a big-endian 16-bit **word count**, followed by two companded sample bytes per word. The exporter selects unmasked μ-law or A-law by region based on waveform measurements. [Tone-bank layout](FORMAT.md#standalone-tone-banks) · [EDRMTONE record manifest](audio/edrmtone/manifest.json)

The receiver off-hook howler is record 10. At `0x3BCA`, the header is `03 E8`, or 1,000 words. The 2,000 sample bytes begin at `0x3BCC` and contain all four frequencies already mixed together. That produces a 250 ms WAV at 8 kHz. Trunk cadence and output level still require card measurements. Nortel documents the `MWTTONE` application for receiver off-hook and milliwatt test service. [Howler WAV](audio/mwttone/tone-bank/tone_10.wav) · [Nortel guide, chapter 14](https://www.gbppr.net/bsp/297-1001-527.pdf#page=179)

This also explains the jumble in `EDRMTONE` bank 0, phrase 41. Its two large page ranges, `0x6A00` to `0xBFFF` and `0xC000` to `0x114FF`, run across tone headers, other tones, and both DTMF sets. Reading them as one phrase decodes all those bytes together. The player’s **Tone banks** view uses the individual record boundaries and displays one playable WAV per record. [Phrase and tone record manifest](audio/edrmtone/manifest.json)

## What the encoder writes

`--phrase` takes a speech WAV and `--tone` takes a generated sequence or an archived tone record. Both write ordinary announcement phrases into slots 40 through 63 of the `ESTD0AA` template. The encoder stores A-law sample codes, pads to 256-sample boundaries, and builds the address records and checksums. An archived μ-law howler becomes A-law audio in a phrase slot. Playback of custom loads on a physical switch remains a bench question. [Encoder examples](ENCODING.md#encode-tone-phrases) · [Bench status](BENCH_STATUS.md)
