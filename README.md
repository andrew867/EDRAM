# Nortel EDRAM converter

**First alpha** · [v0.2.0-alpha.1](https://github.com/andrew867/EDRAM/releases/tag/v0.2.0-alpha.1) · [Release notes](CHANGELOG.md)

Extract speech and tones from DMS-100 and SL-100 announcement loads. The converter reads binary .bin44 and text S-record .txt80 files and writes 8 kHz, 16-bit mono WAVs. It runs on Python 3.10 or newer with the standard library.

## Listen to the archive

Clone or download the repository and open [audio/listen.html](audio/listen.html) locally. Search by load, phrase number, transcript, or Nortel mnemonic such as AVRE08. Use **Tones** for SITs, cues and alerts. Use **Tone banks** for individual DTMF keys, milliwatt carriers and the receiver off-hook howler.

The player uses the decoded waveform for every clip. It shows Nortel catalog wording where the recording matches it, and machine transcripts with review flags elsewhere. [Nortel phrase catalog](references/NORTEL_PHRASES.md)

## Decode a load

~~~sh
python edram.py data/original/estd0aa.bin44 -o decoded --segments
python edram.py data/original/estd0aa.bin44 --inspect
~~~

Pass a directory to decode all supported loads inside it. The `--segments` option also writes each distinct referenced page range once. Each load gets a folder with WAVs, `phrases.csv`, and `manifest.json`. The manifest has source and PCM hashes, page addresses and repeat counts, counts of unwritten sample addresses, and reasons for rejected references. Standalone tone payloads go in `tone-bank/`. Use a fresh output directory for a clean comparison.

| What you need | Start here |
| --- | --- |
| How a phrase becomes a WAV | [Audio format guide](AUDIO_FORMAT_GUIDE.md) |
| Exact fields, checksums and byte offsets | [Format reference](FORMAT.md) and [worked byte map](BYTE_MAP.md) |
| Stored tone levels and SIT timing | [Tone measurements](research/TONE_PLAYBACK.md) |
| Create a custom single-bank voice load | [Encoder guide](ENCODING.md) |
| Pack or inspect a tape image | [SLM tape guide](SLM_TAPE.md) |
| Test a new load on an NT1X80 card | [Bench checklist](BENCH_STATUS.md) |
| Earlier experiments and superseded interpretations | [Archive](archive/README.md) |

## Verify an extraction

~~~sh
python edram.py data/original -o decoded --segments
python verify_corpus.py data/original decoded
python -m unittest discover -s tests -v
~~~

The reference run covers 61 loads and verifies 5,377 WAVs against the decoded source PCM. It reports missing payloads, invalid menus and page ranges that cross standalone tone records. Card playback, including SIT timing and level, needs a hardware comparison. [Verification report](VALIDATION.json)

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

The separate [T7316 ringer model](ringer/README.md) reproduces four patterns measured from a BCM set recording.
