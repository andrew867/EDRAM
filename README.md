# Nortel EDRAM converter

Extract individual announcements and reusable audio segments from DMS-100 / SL-100 EDRAM load files. Supports binary bin44 G-records and ASCII Motorola S-record txt80 files. Python 3.10 or newer; the converter itself has no dependencies.

Speech extraction uses Joe Z's unmasked A-law mapping. Recognized SIT menus render as three synthesized sine waves using Nortel's documented EDRAM frequencies and durations. [Tone playback notes](research/TONE_PLAYBACK.md) describe the menu interpretation and earlier waveform experiments.

## Listen and search

The reference import workflow writes original files under [data/original](data/original), all extracted WAVs under [audio](audio), and a searchable player at [audio/listen.html](audio/listen.html). Download or clone the repository and open that HTML file locally; GitHub's source preview does not execute its audio player.

Choose **Tones and comparisons** to browse SIT, the corrected 750 Hz cues, the recorded alert and calling-card tones, and the standalone `MWTTONE` and `EDRMTONE` waveforms. Tone rows show their pitches or timing and link to the WAV for each load.

The transcription workflow uses multilingual Whisper small through faster-whisper, with voice activity detection, identical-PCM deduplication, six independent processing shards, per-segment timestamps and review flags. It processes announcements and reusable speech fragments. Known tone components and silence receive descriptive labels. JSON and CSV transcripts accompany the HTML player.

Search the player by a Nortel mnemonic such as `AVRE08` or browse source pages from the [phrase catalog](references/NORTEL_PHRASES.md). Where the audio transcription and Nortel's script agree, the player shows the catalog-checked reading with available intonation or category labels. The transcript export preserves the original recognition when the display text changes.

A listener identified eaabs0hc.bin44, bank 0, phrase 4 as the calling-card / operator bong with fade. Tone FFT measurements are recorded in [research](research).

## Convert

~~~sh
python fetch_samples.py samples
python edram.py samples -o decoded --segments
python -m unittest discover -s tests -v
python verify_corpus.py samples decoded --json VALIDATION.json
~~~

To use an existing archive, supply --archive /path/to/edram.tar.gz to fetch_samples.py. To inspect menus without writing audio, use python edram.py samples/estd0aa.bin44 --inspect.

Output is 8 kHz, 16-bit mono PCM WAV with source and codec metadata. Every source has its own folder, every bank its own subfolder. Manifests retain source hashes, addresses, checksums, segment order and repetition counts, implicit zero-fill counts, ordered memory rewrites, invalid menus and unavailable references. `--segments` exports each referenced segment once without repeats. `--raw-sit` bypasses SIT synthesis. `--raw-tones` expands all phrase tone bytes directly. Recognized standalone tone bank records export to a `tone-bank/` subfolder with their measured companding law.

Existing output folders require explicit --overwrite. Prefer a new directory when changing settings; overwrite does not delete obsolete or unrelated files.

## Encode a voice load

[The voice-load encoder](ENCODING.md) builds a named single-bank `.bin44` or `.txt80` file from 8 kHz mono PCM WAVs. It uses the factory-style ESTD0AA structure and verifies the generated file locally. Switch acceptance remains untested.

[The SLM tape tool](SLM_TAPE.md) lists and extracts archived tape files, appends existing entries, and builds experimental `.bin44` bench images. The documentation records the recovered labels, byte ordering, checksums, and the tape-to-disk path used before `LOADPM`.

[The bench checklist](BENCH_STATUS.md) records the remaining DMS acceptance checks and tone research.

## Reference extraction

| Result | Count |
| --- | ---: |
| Load files | 61 |
| Memory banks | 118 |
| Valid nonempty phrase menus | 2,890 |
| Announcement WAVs | 2,873 |
| Segment WAVs | 2,432 |
| Missing phrase payloads, skipped | 17 |
| Structurally invalid menus, flagged | 3 |

The 2,873 announcement WAVs include 285 SIT renders covering 32 sequences and 240 corrected 750 Hz cues. The standalone banks add 79 waveform WAVs, with 17 records common to both files.

The two txt80 tone files contain menus referencing speech absent from those files. Those announcements are unavailable instead of fabricated as silence. In fstd0ba.bin44, bank 1, phrases 8, 11 and 20 have misaligned pointers; their raw entries and reasons remain in invalid_phrases.

The import job verifies the complete extraction against these baseline counts and reads every WAV to check its format, frame count and PCM hash. VALIDATION.json records the result. A successful numerical audit is not a human listening review.

## Audio decoding and remaining work

The default alaw-unmasked expansion is byte-for-byte equivalent to standard G.711 A-law after XOR 0x55. All 256 input values match an independent FFmpeg reference. The explicit mulaw-unmasked option expands standard mu-law after XOR 0x7f for diagnostic comparisons; it is not automatic codec detection.

The older DRAM architecture is documented as using four-bit ADPCM. That alone does not establish a standard packed G.726 or IMA stream in these particular EDRAM files. No ADPCM decoder is currently implemented. A local G.726 trial failed to recover the speech that the unmasked G.711 expansions recovered.

SIT attack pages and repeated pages have markedly different levels under direct byte expansion. The default SIT renderer interprets the menu and generates the specified tones at a fixed digital level. Original hardware gain and sample-byte playback remain unverified. [SIT derivation and measurements](research/TONE_PLAYBACK.md)

[T7316 ringer synthesis](ringer/README.md) implements four measured BCM set ringer patterns as a small C99 DSP renderer.

## Transcribe locally

~~~sh
python -m pip install -r requirements-transcription.txt
python transcribe.py plan decoded --plan transcription-plan.json
python transcribe.py run decoded --plan transcription-plan.json --model small --output transcripts-part-0.json
python transcribe.py merge decoded --plan transcription-plan.json --parts .
~~~

The run command can resume its checkpoint. Review flags expose weak language detection, low model scores, unusual repetition and empty recognition results. These scores are heuristics, not calibrated accuracy percentages. All raw ASR text and segment metrics remain in transcripts.json.

## Format and provenance

See [FORMAT.md](FORMAT.md) for the recovered transport and menu layout.

Prior work: [Joe Z's EDRAM investigation](http://www.dms-100.net/telephony/nortel/dms-100/edram/), including the original unmasked A-law approach and G-record observations.

Original archive: [SL-100 files](http://www.dms-100.net/files/telephony/nortel/SL100/samples/EDRAM/) and [DMS-100 files](http://www.dms-100.net/files/telephony/nortel/DMS100/samples/EDRAM/).

Archive SHA-256: 88ab9decafafbb71642e5b58b9be91d1f9d6d801f00d838f1f16347506c27bf8.

Nortel reference: [297-1001-527, DRAM and EDRAM Guide](https://www.gbppr.net/bsp/297-1001-527.pdf), Standard 13.06, August 1999, printed pages 2-8 and 4-7 through 4-11.

The converter is a new Python implementation. Joe's C code, proprietary firmware and Nortel source code are not incorporated. The MIT license covers the new code, tests and documentation only; original load files and recordings retain their respective ownership.

## SIT comparison signals

The [waveform and FFT comparison](research/sit-waveform-fft.svg) shows the direct A-law baseline beside the documented sine synthesis. [Reference documentation](references/README.md) records the frequencies, durations and generation settings. Re-export the archive and rebuild the player using the existing transcripts with these commands.

~~~sh
python edram.py data/original -o audio --segments --overwrite
python tone_playback.py data/original audio --archive
python transcribe.py index audio
python verify_corpus.py data/original audio
~~~
