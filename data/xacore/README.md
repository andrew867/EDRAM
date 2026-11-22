# EDRAM files from XA-Core disks

These files come from `0000.img.xz`, `0001.img.xz`, and `XA-core-spare.img.xz` in [Joe Z's XA-Core disk archive](http://www.dms-100.net/files/telephony/nortel/SL100/hdd/index.txt). The [disk extractor](../../xacore_ftfs.py) reads native `DSK1` disks and `FTFS` volumes. It checks directory pages and file descriptors, follows direct and indirect extents, and restores byte order within 16-bit words.

The [original files](original/) keep their XA-Core filenames and logical bytes, including record wrappers. Identical copies across disks and volumes share one archived file. [SHA256SUMS](SHA256SUMS) covers the original files and the two firmware text exports.

| Load | Source | What the file contains |
| --- | --- | --- |
| `ASTD0AB`, `ESTD0AA` | `0000/PMLD`, `0001/PMLD` | Factory announcement loads. Each matches its `data/original/*.bin44` copy byte for byte. |
| `DTM_BK3` | `0000/PMLD`, `0001/PMLD` | Wrapped G-record announcement load with seven valid phrase entries. |
| `ED16AA07` | `0000/PMLD`, `0001/PMLD`, spare `PMLD` and `UPGRADE` | EDRAM firmware with 3,449 S2 records and one Nortel S6 footer. |
| `EDRMAE11` | Spare `PMLD` and `UPGRADE` | EDRAM firmware with 3,446 S2 records and one Nortel S6 footer. |
| `ANN1` through `ANN8` | Spare `PMLD` and `UPGRADE` | Eight wrapped G-record announcement loads. Each has seven to nine valid phrase entries. |

The [S-record text exports](srecords/) preserve the record addresses, data, and per-line checksums. Each original firmware file stores the text in 84-byte disk records with a four-byte prefix and space padding. All individual S-record checksums passed. The final S6 line carries the original Nortel footer.

Each `DTM_BK3` and `ANN*` disk record is 259 bytes. The first four bytes are `00 4c 2c 00`, followed by a 44-byte G record and 211 spaces. For offline decoding, copy the 44-byte records and set their last byte to `0x16`. The addressed data and per-record checksums carry over unchanged. The native files above preserve the original final byte of each record.

## XA-Core spare volumes

| FTFS volume | First LBA (512-byte sectors) | Capacity | Announcement files |
| --- | ---: | ---: | --- |
| `PMLD` | 2,048,019 | 500 MiB | `ANN1` through `ANN8` |
| `UPGRADE` | 3,072,019 | 300 MiB | Byte-for-byte matches of all eight `PMLD` files |

Use the spare's `PMLD` copies to reproduce the audio analysis. The two `DTM_BK3` copies in `0000/PMLD` and `0001/PMLD` also match byte for byte.

## Play the recordings

Clone or download the repository and open [audio/listen.html](audio/listen.html). Use the filter to find a load, phrase number or transcript. [audio/catalog.csv](audio/catalog.csv) includes paths, page references, PCM checksums and duration measurements. The [transcript data](audio/asr.jsonl) contains unedited machine output. Listen to overlapping phrases and test recordings before relying on that text.

| Material | Result |
| --- | ---: |
| Checksum-valid menu slots | 71 across 9 loads |
| Direct phrase WAVs | 53, comprising 35 speech slots and 18 silence slots |
| Unreferenced recorded fragments | 4, one each in ANN4, ANN5, ANN6 and DTM_BK3 |
| Individual referenced segment WAVs | 249 |

All 35 speech slots differ from the decoded reference waveforms in the repository's 61 original EDRAM load files. The 18 silence slots match factory silence. Slot 08 is the first 0.992 seconds of slot 09 in all nine backups. Several longer entries also overlap or begin mid-message, so slot counts include excerpts and repeated material.

ANN1 through ANN8 contain a set of PTSI Cellular recordings for the Oklahoma Panhandle. The prompts cover the mobile service area, 611, toll billing, emergency dialing, follow-me roaming and automatic call delivery. ANN7 slot 09 explicitly names PTSI Cellular and the Oklahoma Panhandle. A [contemporary Panhandle newspaper](https://newspapers.swco.ttu.edu/server/api/core/bitstreams/899cb423-d31d-4b93-a334-6ff15049a416/content) connects that service name with the Guymon cellular switch. The recordings' dates are unknown. DTM_BK3 slot 09 begins with a spoken test announcement. Slot 16 contains another short spoken test fragment. The unreferenced pages include more recorded audio.

The menus for slots 01 and 02 reference pages 14 and 15, which all nine backups omit. The [firmware player](firmware/audio/4040/listen.html) contains the 750 Hz test tone and three-burst prompt decoded from the built-in sample page at `0x400800`. Both recovered firmware builds produce the same cue bytes.

Each phrase WAV expands the stored unmasked A-law codes at 8,000 samples/s and applies the menu repeats. The unreferenced fragments concatenate the surviving pages in address order. The exact original offsets are in [audio/extra-audio.json](audio/extra-audio.json).

The [firmware review](../../research/XA_CORE_FIRMWARE.md) covers the two 68k loads. [CLLI mapping](../../research/XA_CORE_CLLI.md) lists suggested message names and traces the DMS tables used to bind them.

## Reproduce the audio export

Run this from the repository root. The output includes the unwrapped records, decoded audio, unreferenced fragments, and exact waveform comparisons. The archived listening catalog includes transcript and phrase labels added after the extract.

```sh
python xacore_audio.py data/xacore/original data/original decoded/xacore
```

## List or extract files

Run the following from the repository root with Python 3.10 or newer. The extractor accepts a raw disk image or a single-stream XZ image. Extraction creates a new output directory with one subdirectory per volume containing files. Use `--volume` or `--name` to select specific files.

```sh
python xacore_ftfs.py 0001.img.xz --volume PMLD
python xacore_ftfs.py 0001.img.xz --volume PMLD --name ED16AA07 --extract edram-load
python xacore_ftfs.py XA-core-spare.img.xz --extract xa-core-spare-files
```

| Disk | Files extracted | Logical bytes |
| --- | ---: | ---: |
| `0000.img.xz` | 1,101 | 1,588,502,839 |
| `0001.img.xz` | 1,248 | 1,542,783,959 |
| `XA-core-spare.img.xz` | 1,315 | 2,378,245,619 |

The MIT license covers the new tools and documentation. The recovered loads retain their respective ownership.
