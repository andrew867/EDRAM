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
