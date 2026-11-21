# Nortel EDRAM phrase catalog

[nortel-phrases.csv](nortel-phrases.csv) indexes archived WAVs against Appendix A of Nortel's *DRAM and EDRAM Guide*, publication 297-1001-527, Standard 13.06, August 1999. It covers 2,055 announcements across 55 archived loads. Nortel prints names for 821 of the matched entries. Short catalog summaries and links to the relevant manual page appear alongside the existing machine transcripts in [the player](../audio/listen.html).

| Column | Meaning |
| --- | --- |
| `load` | Voice file basename in the archive |
| `bank` | Local bank index in the extracted load. Appendix A generally calls this the virtual card. |
| `phrase` | Decimal phrase ID within that bank |
| `nortel_name` | Nortel phrase-name field when documented and matched |
| `catalog_note` | Short summary or component label based on the manual |
| `printed_page` | Page number printed in the manual |
| `pdf_page` | One-based PDF viewer page in the linked copy |
| `pcm_sha256` | SHA-256 of the archived WAV's PCM frames |

The catalog uses load, bank and phrase ID to match the appendix. Documented digit ranges are expanded to individual IDs. Large discrepancies between the documented and extracted duration, conflicting rows, and undocumented slots are omitted. Minor differences can occur between the documented and archived loads. The PCM hash keeps a custom replacement with the same filename and phrase ID from inheriting the stock description.

For example, `EACTS0AE` bank 0 phrase 12 has the printed mnemonic `plsdep`. `ECLS10AJ` bank 1 phrase 4 has catalog content and a source page with an empty phrase-name column. Nortel prints two conflicting names for `EACCS0AH` bank 1 phrase 38, so that entry is omitted. The catalog has no entries for `EDRMTONE`, `ESTD0AA`, `FSTD0BA`, `JPDMCT00`, `MWTTONE`, or `SMRG101C`.

An installed switch assigns its own aliases in `DRAMPHRS`. `DRAMREC` → `ASSIGNDUMP COMMANDS` shows the office's aliases, DRAM numbers, loaded blocks and phrase IDs. Those installed block numbers come from the switch configuration.

Rebuild the player with `python transcribe.py index audio`. The CSV accompanies the transcripts and can be used independently of the player.

- [Nortel guide, Appendix A](https://www.gbppr.net/bsp/297-1001-527.pdf#page=251)
- [Nortel guide, DRAMREC and DRAMPHRS](https://www.gbppr.net/bsp/297-1001-527.pdf#page=191)
