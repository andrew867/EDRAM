# Nortel EDRAM converter

**First alpha** · [v0.2.0-alpha.1](https://github.com/andrew867/EDRAM/releases/tag/v0.2.0-alpha.1) · [Release notes](CHANGELOG.md)

Decode speech and tones directly from the sample bytes in Nortel DMS-100 and SL-100 loads. The converter reconstructs the addressed image from `.bin44` or `.txt80` records, expands the stored G.711 codes to 8 kHz, 16-bit mono PCM, and follows the phrase menu's page and repeat counts. Standalone tones use the sample range given by each record header. Python 3.10 or newer is sufficient.

## Listen to the firmware tones

Each firmware player contains 32 SITs, two 750 Hz cues, and four continuous tones decoded from the Nortel startup tables. Download the repository and open the player locally. Both players include raw sample-code downloads and WAVs decoded with the law identified for each waveform.

- [Firmware player with selector 0x4040](data/xacore/firmware/audio/4040/listen.html)
- [Firmware player with selector 0x5050](data/xacore/firmware/audio/5050/listen.html)

## Listen to the announcement-load archive

Clone or download the repository and open [audio/listen.html](audio/listen.html) locally. Search by load, phrase number, transcript, or Nortel mnemonic such as AVRE08. Use **Tones** for SITs, cues and alerts. Use **Tone banks** for individual DTMF keys, milliwatt carriers and the receiver off-hook howler.

This player presents the bytes and menus of the archived announcement and tone loads. That includes speech, SITs, the 750 Hz cues, DTMF, milliwatt tones, and the receiver off-hook howler. Tone names, frequencies, and transcripts annotate those recordings. The WAVs keep the stored levels and the lengths implied by the menus. [Worked byte map](BYTE_MAP.md#follow-real-tone-data) · [Nortel phrase catalog](references/NORTEL_PHRASES.md)

The [XA-Core player](data/xacore/audio/listen.html) covers the recovered PTSI Cellular announcements and DTM test recordings, and links to both firmware players. The [phrase catalog](data/xacore/audio/catalog.csv) identifies the load, slot, and source of each clip.

## Decode a load as stored

~~~sh
python edram.py data/original/estd0aa.bin44 -o decoded --segments
python edram.py data/original/estd0aa.bin44 --inspect
~~~

Pass a directory to decode all supported loads inside it. The `--segments` option also writes each distinct referenced page range once. Each load gets a folder with WAVs, `phrases.csv`, and `manifest.json`. The manifest has source and PCM hashes, page addresses and repeat counts, counts of unwritten sample addresses, and reasons for rejected references. Standalone tone previews go in `tone-bank/`. Use `--raw-tones` for the original word-count headers and sample bytes. The [encoder](ENCODING.md#rebuild-a-native-standalone-tone-bank) can rebuild native MWTTONE and EDRMTONE loads. Use a fresh output directory for a clean comparison.

| What you need | Start here |
| --- | --- |
| How a phrase becomes a WAV | [Audio format guide](AUDIO_FORMAT_GUIDE.md) |
| Exact fields, checksums and byte offsets | [Format reference](FORMAT.md) and [worked byte map](BYTE_MAP.md) |
| Stored tone levels and SIT timing | [Tone measurements](research/TONE_PLAYBACK.md) |
| Create a custom single-bank voice load | [Encoder guide](ENCODING.md) |
| Pack or inspect a tape image | [SLM tape guide](SLM_TAPE.md) and [nine-track and IOM DAT comparison](SLM_TAPE.md#ibm-tape-labels-and-the-observed-slm-format) |
| Extract an XA-Core disk or inspect recovered loads | [XA-Core disk extraction and EDRAM files](data/xacore/README.md) |
| Analyze the NT1X80 firmware or map custom announcements | [XA-Core firmware](research/XA_CORE_FIRMWARE.md) and [CLLI mapping](research/XA_CORE_CLLI.md) |
| Reimplement the loader and playback behavior | [EDRAM behavior specification](research/EDRAM_BEHAVIOR_SPEC.md), [C playback reference](reference/edram/playback.c), and [firmware evidence](research/EDRAM_FIRMWARE_EVIDENCE.md) |
| Test a new load on an NT1X80 card | [Bench checklist](BENCH_STATUS.md) |
| Earlier experiments and superseded interpretations | [Archive](archive/README.md) |

## Preview a load on the card

~~~sh
python edram.py --card-playback data/xacore/srecords/ED16AA07.srec --slot 1 --slot 8 data/original/estd0aa.bin44 -o card-voice
python edram.py --card-playback data/xacore/srecords/ED16AA07.srec --first-bank 1 --slot 42 --slot 49 data/original/mwttone.txt80 -o card-tones
~~~

The card preview models an accepted load. It seeds RAM banks 0 through 7, applies the load writes, and follows the slot routing selected by the loaded bank's internal tag. Each input file is previewed as a separate load. `--first-bank` uses zero-based physical RAM numbering. `--playback-selector` defaults to `0x4040`. At `0x5050` the first waveform reference moves two banks above the address in the firmware descriptor. The preview reports unavailable records when its input lacks the resolved waveform. The manifest includes addresses, sample laws, and the firmware digest. [Firmware startup and playback routing](research/EDRAM_BEHAVIOR_SPEC.md#firmware-download-and-startup)

## Decode built-in firmware SITs

~~~sh
python edram.py --firmware-tones data/xacore/srecords/ED16AA07.srec -o decoded-firmware
python edram.py --firmware-tones --sit-selector 0x5050 data/xacore/srecords/EDRMAE11.srec -o decoded-selector-5050
~~~

Each firmware export includes 38 WAVs and a manifest with startup addresses, sample laws and hashes. Finite clips include the padded staged bytes. Continuous clips include the complete length-prefixed waveform record and play as loops. Both firmware builds are supported as S-records or flat binaries. Use `--inspect` for JSON output. [Firmware SIT format](FORMAT.md#built-in-firmware-sits)

## Verify an extraction

~~~sh
python verify_corpus.py data/original audio --check-player
python edram.py data/original -o decoded --segments
python verify_corpus.py data/original decoded --check-player
python -m unittest discover -s tests -v
~~~

The reference run verifies 5,377 WAVs against the PCM decoded from 61 loads and checks all 59 binary G6 payload sums. The searchable archive indexes all 5,377 WAVs. A fresh decoder run builds a smaller player for full phrases and standalone tone records. The verifier also reports missing payloads, invalid menus, and ranges that cross standalone tone records. Actual card timing and level still need a hardware capture. [Verification report](VALIDATION.json) · [Independent FFmpeg check](research/TONE_PLAYBACK.md#independent-waveform-check)

## Transcribe and rebuild the player

After re-exporting to `audio/`, run `python transcribe.py index audio` to rebuild the player using the checked-in transcripts. To transcribe a new collection, install the optional Whisper dependencies and run the three stages below.

~~~sh
python -m pip install -r requirements-transcription.txt
python transcribe.py plan decoded --plan transcription-plan.json
python transcribe.py run decoded --plan transcription-plan.json --model small --output transcripts-part-0.json
python transcribe.py merge decoded --plan transcription-plan.json --parts .
~~~

Transcription deduplicates identical PCM and saves checkpoints. Review flags identify clips that need listening. The JSON keeps model text and segment metrics when catalog wording is shown in the player.

## Source and license

The reference loads in `data/original/` come from EDRM0001 version 010. Joe Z documented the G-record and unmasked A-law interpretations. Nortel 297-1001-527 describes DRAM and EDRAM services and catalogs the factory phrases. The MIT license covers this repository's implementation, tests and documentation. The original recordings and load files retain their respective ownership. [Source archive and hash](data/README.md) · [Joe Z's notes](http://www.dms-100.net/telephony/nortel/dms-100/edram/) · [Nortel DRAM and EDRAM Guide](https://www.gbppr.net/bsp/297-1001-527.pdf)
