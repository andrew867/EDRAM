# Nortel EDRAM phrase catalog

[nortel-phrases.csv](nortel-phrases.csv) indexes the 191 table pages of Appendix A of Nortel's *DRAM and EDRAM Guide*, publication 297-1001-527, Standard 13.06, August 1999. The export covers 55 voice loads, including reserved slots and entries that could not be linked confidently to a WAV. [The player](../audio/listen.html) and [transcript export](../audio/transcripts.csv) use the verified archive matches.

| Column | Meaning |
| --- | --- |
| `load` | Voice file basename in the archive |
| `bank` | Local bank index in the extracted load. Appendix A generally calls this the virtual card. |
| `phrase` | Decimal phrase ID within that bank |
| `nortel_name` | Nortel phrase-name field when documented |
| `catalog_note` | Short summary or component label based on the manual |
| `printed_page` | Page number printed in the manual |
| `pdf_page` | One-based PDF viewer page in the linked copy |
| `pcm_sha256` | SHA-256 of the direct codec expansion's PCM frames. SIT metadata retains that hash when the player uses synthesized audio. |
| `catalog_duration_seconds` | Total duration published by Nortel, or the sole printed duration |
| `component_durations_seconds` | Individually listed component durations, separated by pipes |
| `catalog_kind` | Speech, tone, silence, reserved, or unspecified |
| `archive_status` | Archive match, unconfirmed, conflicting print rows, no archive audio, or reserved |
| `category` | A catalog description such as vacant code |
| `intonation` | Printed intonation or the documented label for its digit family in the same bank |
| `transcript_text` | Archive transcription selected after the spoken words match the printed script |
| `transcript_basis` | Agreement with the original recognizer, a second Whisper pass, or a spoken-digit match |

The catalog uses load, bank and phrase ID to match the appendix. Documented digit ranges are expanded to individual IDs. Where the durations differ substantially, matching spoken words can confirm a row. Conflicting rows can be looked up by source page. Only archive matches carry a PCM hash, which protects custom replacements using the same filename and phrase ID.

Transcript selection compares the audio recognition with the full catalog wording after normalizing punctuation and spoken digits. A second Whisper pass on selected differences receives the WAV and its language. The player uses an updated transcript when the spoken wording agrees. The export retains changed originals in `asr_text` and labels corrections with `text_source`. Intonation and category are printed details stored separately from the spoken words.

For example, `EAOSS0AF` bank 1 phrase 4 is `AVRE08`. In `EACCS0AH` bank 1, phrase 21 is `ENG0` with flat A intonation and phrase 31 is `CENF0` with falling intonation. Nortel prints two conflicting names for `EACCS0AH` bank 1 phrase 38. Both source rows are listed with blank PCM hashes. Appendix A has no phrase tables for `EDRMTONE`, `ESTD0AA`, `FSTD0BA`, `JPDMCT00`, `MWTTONE`, or `SMRG101C`.

An installed switch assigns its own aliases in `DRAMPHRS`. `DRAMREC` → `ASSIGNDUMP COMMANDS` shows the office's aliases, DRAM numbers, loaded blocks and phrase IDs. Those installed block numbers come from the switch configuration.

Rebuild the player with `python transcribe.py index audio`. The CSV accompanies the transcripts and can be used independently of the player.

- [Nortel guide, Appendix A](https://www.gbppr.net/bsp/297-1001-527.pdf#page=251)
- [Nortel guide, DRAMREC and DRAMPHRS](https://www.gbppr.net/bsp/297-1001-527.pdf#page=191)
