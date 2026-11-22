# Assigning the recovered XA-Core announcements to CLLIs

Use an announcement CLLI for each message you want the DMS to play. A file such as `ANN1` carries a menu with several internal phrase slots. Central-control datafill connects an external phrase name to one of those slots, then includes that phrase in an announcement track.

The [load inventory](../data/xacore/README.md#xa-core-spare-volumes) identifies both disk copies. In all four saved PTSI Guymon `*_XA` snapshots from the spare's `IMAGE` volume, the names `ANN1` through `ANN8` occur in order in adjacent records, starting at file offset `0x04EC7FD8` and spaced 18 bytes apart. The historical DTM number, card, and announcement CLLI assignments are unverified.

## Suggested names

These are proposed identifiers for cataloging or testing the recovered audio. Slot numbers are decimal and local to the file. The [player](../data/xacore/audio/listen.html) and [full catalog](../data/xacore/audio/catalog.csv) include the remaining slots and fragments.

| Suggested CLLI | Source file | Internal slot | Decoded duration (s) | Message |
| --- | --- | ---: | ---: | --- |
| `PTSINIS` | `ANN1` | 9 | 8.992 | Number out of service |
| `PTSI611` | `ANN1` | 18 | 14.016 | PTSI service inquiries and 611 |
| `PTSIMOBOFF` | `ANN2` | 9 | 12.000 | Mobile off or outside coverage |
| `PTSINOTOLL` | `ANN3` | 9 | 10.016 | Mobile lacks toll calling |
| `PTSIINVALID` | `ANN4` | 9 | 11.008 | Invalid cellular number |
| `PTSILOCAL` | `ANN5` | 9 | 11.008 | Local mobile call |
| `PTSIEMERG` | `ANN6` | 9 | 15.008 | Historical emergency dialing instructions |
| `PTSITOLLBILL` | `ANN7` | 9 | 22.016 | Oklahoma Panhandle toll billing |
| `PTSIROAM` | `ANN8` | 9 | 14.016 | Automatic roaming call delivery |
| `PTSITENDIG` | `ANN8` | 23 | 12.000 | Dial all ten digits |

In every `ANN` load, slot 8 is only the first 0.992 seconds of slot 9. Some other entries are overlapping or partial recordings. Use the full message slot for the track. For a fresh recording of the 22.016-second `ANN7` message, Nortel's procedure calls for splitting announcements longer than 18 seconds into equal-length phrases. Use the registered duration when restoring an existing phrase. [Nortel 297-1001-527, chapter 12](https://www.gbppr.net/bsp/297-1001-527.pdf)

## DMS datafill and playback

1. In `TABLE EDRAMINV`, use `LIST ALL` to identify the DTM and card that hold each filename. Nortel's custom-file reload procedure uses `ADD DTM <dtm> <card> ANN <filename>` when the source filename needs an inventory entry. The destination card must be datafilled as RAM in `DRAMS` for the applicable peripheral loads. The file-relative `bank_00` in the extraction leaves the installed card number unspecified. [Nortel 297-1001-527, pages 12-41, 12-54 to 12-60](https://www.gbppr.net/bsp/297-1001-527.pdf)
2. In `DRAMREC`, use `DISPLAY <dtm> <card>` to read `PHRASE_EXT`, `PHRASE_INT`, and `LENGTH`. When restoring to another DTM and assigning a new external phrase name, Nortel documents `RECORD <name> <length> PAD <dtm> <card> <internal_phrase> FORCE`. For the first test, use `ANN1` slot 9 with an external name such as `PTSI01NIS`. Use the established DTM, card, and length from the switch and verify the phrase with `PLAYBACK <dtm> PTSI01NIS`. [Nortel 297-1001-527, pages 12-53 and 12-61 to 12-62](https://www.gbppr.net/bsp/297-1001-527.pdf)
3. Define `PTSINIS` in `CLLI` and `ANNS`, assign its announcement member in `ANNMEMS`, and place `PTSI01NIS` in the corresponding `DRAMTRK.PHSLIST`. Use a working custom announcement on the target switch as the template for the member fields. [Nortel 297-1001-527, pages 12-68 to 12-69](https://www.gbppr.net/bsp/297-1001-527.pdf) · [Nortel 297-8021-350 vol. 1, treatment table overview](https://telecom.wiki/download/attachments/819545/297-8021-350_V1_I18.02.pdf)
