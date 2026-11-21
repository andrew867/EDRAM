# Nortel SLM tape images and EDRAM voice loads

`slm_tape.py` inventories, extracts, and combines the observed Nortel 512-byte SLM tape files. It runs on Linux and Windows with Python 3.10 or newer. It also builds an experimental tape entry around a `.bin44` voice load. The file-level encoder and tape image pass offline round trips. Restoring a new voice entry on a DMS-100 or SL-100 remains a bench test.

## Recording media and image framing

A physical tape drive handles the recording medium. The host transfers records and filemarks. On Linux, the `st` driver supports variable-record I/O through devices such as `/dev/nst0`. A read in variable-block mode obtains one record and a write makes one record. `MTWEOF` writes a filemark. Check the drive and cartridge generation on both ends. Nortel lists different cartridges for different SLM generations, and the XA-Core product guide lists DAT as a mass-storage option. [Linux SCSI tape driver](https://docs.kernel.org/scsi/st.html) · [Nortel 297-8001-546](https://www.gbppr.net/bsp/297-8001-546.pdf) · [SL-100 product guide](https://www.manualslib.com/manual/1184407/Nortel-Sl-100.html?page=28)

An E11 image wraps a record in two identical little-endian 32-bit lengths. A single zero word is a tape mark. A single `0xffffffff` word can indicate end of medium. SIMH's standard image variant pads odd-length records before the trailing word. These SLM images use only even 512-byte records, so the two representations coincide. A 512-byte tape record occupies 520 bytes in the image, excluding tape marks. The `.xz` suffix is a compression layer over the entire image. [Open SIMH image formats](https://opensimh.org/simdocs/simh_doc.html)

`tapecopy` unwraps the image and writes individual records and marks to a tape device. Its upstream Linux implementation attempts `MTSETDENSITY 0x02` on open and ignores a failed density change. For DDS replay, use a build that leaves density selection to the chosen drive, for example by removing the `mt_setden` ioctl call in `tapeio.c` and retaining variable-block setup. Use a scratch cartridge for replay. [tapecopy source](https://github.com/brouhaha/tapeutils/blob/master/tapecopy.c) · [Tape I/O source](https://github.com/brouhaha/tapeutils/blob/master/tapeio.c)

## Native layout observed in the archive

The archive has a single 512-byte `VOL1` record followed by a tape mark. Each file takes three tape files in succession.

1. A 512-byte `HDR1` record, followed by a mark.
2. The file data in consecutive 512-byte records, followed by a mark.
3. A 512-byte `EOF1` record, followed by a mark.

Both reference images then have two additional zero words after the final trailer group. The writer preserves the input's terminal markers. The scanner validates framing and every label checksum as it reads the image, and rejects incomplete groups, unsupported layouts and mismatched lengths.

| Reference image | Volume | Named entries | Tape records including labels | Logical record length |
| --- | --- | ---: | ---: | ---: |
| `0314-patches.tap.xz` | `PATS` | 166 patch files | 6,787 | 128 |
| `0101-sl-100-sept-23.tap.xz` | `SEP03` | 2 office backup datasets, `_XA` and `_MS` | 468,139 | 1020 |

The compressed source SHA-256 values are `7c5c7fef7977b31315209eca2ab8008955ef15e004fe55a1edc4389c960985b0` for the [patch tape](http://www.dms-100.net/files/telephony/nortel/DMS100/tapes/0314-patches/) and `f4aa5956e8189fc68056bf4a7f04f1fbe92c4a04049a0a08395acaf1a7792513` for the [SL-100 backup](http://www.dms-100.net/files/telephony/nortel/DMS100/tapes/0101-sl-100-sept-23/). The reference images stay outside the source repository.

### Label fields

Offsets are zero-based from the start of the 512-byte payload. Numeric fields below are read directly from raw tape bytes as big-endian integers. To display a text field, exchange adjacent bytes within each 16-bit word. For example, the raw bytes `44 48 31 52` at offset 2 give `HDR1` after word swapping. The E11 framing words are independent of this text ordering.

| Offset | Width | Value or field |
| ---: | ---: | --- |
| 0 | 2 | `00 01` in all examined labels |
| 2 | 4 | Word-swapped ASCII label ID `VOL1`, `HDR1` or `EOF1` |
| 6 | 32 | Word-swapped volume name in `VOL1`, right-padded with spaces |
| 6 | 2 | One-based file ordinal in `HDR1` and `EOF1` |
| 8 | 32 | Word-swapped file name in `HDR1` and `EOF1`, right-padded with spaces |
| 40 | 28 | Word-swapped timestamp text and terminator in file labels |
| 68 | 16 | Word-swapped owner field in file labels |
| 86 | 4 | File bytes before the final tape block's padding |
| 90 | 4 | Number of data tape records |
| 94 | 2 | Tape record size, 512 in both samples |
| 96 | 2 | File code, `0x000b` on the patch tape and `0x000a` on the office backup tape |
| 164 | 4 | Word-swapped ASCII marker `LFS0` |
| 168 | 2 | Logical file record length |
| 172 | 2 | Observed difference between logical record length and the value at 178 |
| 178 | 2 | Logical record length plus the value at 172 |
| 180 | 4 | Number of logical records in the file |
| 184 | 2 | Final block byte remainder in `EOF1`, zero when the last block is full. `HDR1` has zero here in these samples. |
| 510 | 2 | Low 16 bits of the sum of the preceding 255 unsigned big-endian 16-bit words |

The checksum formula matches all 338 labels. Across 168 files, `size = logical record length × logical record count`, `tape blocks = ceil(size / 512)` and `EOF1 remainder = size % 512`. The patch record length and value at 178 are 128 and 130. The office backup values are 1020 and 1030. In particular, the 1020-byte records require fewer tape blocks than rounding each record up to 1024 bytes would use. The label relationship at 172 and 178 is established. Its role in disk record allocation remains inferred, and the on-tape byte count uses the logical length at 168.

For `CBM12PGT$PATCH`, 353 logical records of 128 bytes produce 45,184 file bytes, stored in 89 tape blocks with 128 bytes used in the last block. Its pair-swapped payload begins with an intelligible `BADMBI PPC` marker. The 2019 `_XA` file has 227,831 logical records of 1020 bytes and a final remainder of 36. All examined padding bytes after the declared size were zero.

Nortel's *Magnetic Tape Reference Manual*, 297-1001-118, documents 9-track and IOM DAT magnetic tape, tape-mark conventions, and the IBM-style 80-byte EBCDIC labels in those formats. The 512-byte word-swapped `LFS0` layout above comes from the SLM samples. The two layouts need separate readers and label generators. [Nortel 297-1001-118, chapters 2 and 3](https://www.gbppr.net/bsp/297-1001-118.pdf)

## Work with an existing image

`list` verifies the directory and framing. `extract` writes the declared file bytes, excluding tape block padding. It swaps each tape word by default, with `--raw-words` available for byte-order comparisons. `append` copies complete entries from a second image and updates their file ordinal and label checksums in the destination. Existing bytes up to the output's append point are copied verbatim. All writes use new output paths and refuse duplicate file names.

```sh
python slm_tape.py list 0314-patches.tap.xz
python slm_tape.py extract 0314-patches.tap.xz 'CBM12PGT$PATCH' patch.bin
python slm_tape.py append base.tap new.tap --from 0314-patches.tap.xz --file 'CBM12PGT$PATCH'
```

Use `append` when a native entry is available. It preserves its file code, logical-record attributes, and payload exactly, including on-tape byte order. Both compressed and uncompressed inputs are accepted. Edits produce an uncompressed `.tap` image.

## Prepare a bin44 bench tape

The archived EDRAM distribution identifies itself as `EDRM0001`, version 010. Its binary voice loads contain 44-byte G-records with per-record checksums and a `G6` aggregate checksum. Nortel's EIU guide independently documents the `.binNN` extension as a way to carry the binary logical record length into a switch file. A `.bin44` retains its 44-byte records throughout encoding and tape packing. Tape framing operates on 512-byte blocks around the file stream. [Release identification](data/original/EDRM0001_INFO.txt) · [G-record format](FORMAT.md) · [EIU guide, Appendix C](https://www.gbppr.net/bsp/297-8991-910.pdf)

`add-bin44` validates the existing G-records and their aggregate checksum. It generates matching SLM header and trailer labels with logical length 44, packed into consecutive tape blocks and zero-padded only at the end. It reuses other metadata from the specified template entry. It applies pair swapping to payload words by default, using the observed SLM text convention. `--raw-words` leaves payload bytes in input order. Label encoding is the same in both cases. `--standalone` copies only the base volume label before writing the new entry. Omit it to append to a copy of the whole image. A native EDRAM template entry can be selected with `--template-image` when one is available.

```sh
python encode_edram.py LABANN.bin44 --phrase 40 greeting-8k.wav
python slm_tape.py add-bin44 0314-patches.tap.xz LABANN.bin44 LABANN.tap \
    --template 'CBM12PGT$PATCH' --standalone
python slm_tape.py list LABANN.tap
python slm_tape.py extract LABANN.tap LABANN LABANN-recovered.bin44
cmp LABANN.bin44 LABANN-recovered.bin44
```

A verified local CLI run packed an 18,216-byte `LABANN` load as 414 logical records in 36 tape blocks. It recovered the original `.bin44` byte for byte. A separate run copied the native `CBM12PGT$PATCH` entry into the same image and verified its directory metadata after assigning ordinal 2.

The example inherits file code `0x000b` and an overhead field of 2 from a patch entry. These fields and the byte order that a native EDRAM tape expects still need a reference dump or switch readback. The patch-derived tape is a small format probe. A switch-written EDRAM file entry is the preferred template for a compatibility test. Take one existing voice file, write it alone with `DISKUT BACKUP FILE`, and collect its tape image, its unmodified off-disk bytes, and its `LISTFL FULL` metadata. Comparing those three captures distinguishes file metadata and byte order from the outer tape framing. `BACKUP FILE` syntax is release-dependent, and the switch's `HELP BACKUP FULL` provides the installed form. [SLM command overview](https://www.gbppr.net/bsp/TAM-1001-018.pdf)

## Write, restore, and verify on the bench

1. Use a compatible DDS drive and scratch cartridge. Write the uncompressed image with a DDS-compatible `tapecopy` build. Read it back and compare the directory and extracted voice bytes. An extra terminal filemark may be introduced by a tape utility when it closes the output.

   ```sh
   mt -f /dev/nst0 rewind
   tapecopy -v LABANN.tap /dev/nst0
   mt -f /dev/nst0 rewind
   tapecopy -v /dev/nst0 LABANN-readback.tap
   python slm_tape.py list LABANN-readback.tap
   ```

2. At the switch, use `DISKUT` and the tape-device name appropriate to the shelf. Nortel's EDRAM voice-file procedure lists the tape and restores the named voice file to disk. Its SLM command form is `RE FILE disk_vol drive_name new_file`. Use the actual PM-load volume and tape device shown by the switch. List the destination file and confirm its byte length and logical record size. Where EIU FTP is available, read the disk file back in binary mode and compare it with `LABANN.bin44`. A usable bench result requires a successful file restore with the expected bytes and record organization. [EDRAM Voice File Release Document, 297-8991-597, chapter 2](http://www.dms-100.net/files/telephony/nortel/docs/pdf/297-8991-597.01.02.pdf)

3. Once the disk file verifies, use a spare EDRAM announcement bank and configure the intended voice file in `EDRAMINV`. Verify how the firmware on the posted DTM and the voice file resolve to the PM load disk volume on that release. `TMINV` identifies the peripheral firmware, and `PMLOADS` provides the base load's disk filename and volume where applicable. The *Voice File Release Document* distinguishes the peripheral firmware from the voice-file set and directs the operator to stage them on the same disk volume. The posted DTM's `LOADPM` loads firmware and the datafilled voice files from disk. The tape's job is to stage the named disk file through `DISKUT`. Verify the result using `QUERYPM` and the test announcement path. [EDRAM Guide, 297-1001-527](https://www.gbppr.net/bsp/297-1001-527.pdf) · [EDRAM Voice File Release Document](http://www.dms-100.net/files/telephony/nortel/docs/pdf/297-8991-597.01.02.pdf)
