# EDRAM tone bytes and playback

The factory loads contain companded waveform samples. The 750 Hz cue supplies a direct byte-level example. Its sustain holds repeated samples that already follow a 750 Hz carrier when expanded as A-law. The standalone banks store individual waveforms with a length header, including DTMF pairs and a pre-mixed receiver-off-hook howler. These bytes need no oscillator frequency to recover a waveform.

## Phrase tones from menu to WAV

All offsets below refer to the reconstructed image after applying the transport records in file order.

| ESTD0AA bank 0 | Bytes | Meaning |
| --- | --- | --- |
| Phrase 1 at `0x0004` | `04 01 02 D5` | Submenu offset `0x0104`, two entries, checksum `D5` |
| Submenu at `0x0104` | `0E 00 01 02` | Page 14 at `0x0E00`, one page, repeat twice |
| Submenu at `0x0108` | `0F 00 01 03` | Page 15 at `0x0F00`, one page, repeat three times |

The last 128 bytes of page 15 are four exact copies of this 32-byte pattern.

~~~text
02 84 86 87 87 84 02 04 06 06 04 81 84 86 87 86
82 04 06 07 07 04 82 84 86 86 84 01 04 06 07 06
~~~

Unmasked A-law expands the block to 32 signed samples with three rising zero crossings in a circular traversal. That is three cycles in 4 ms, or **750 Hz**. A 32-byte period is evidence of a waveform table. The submenu supplies addresses, range lengths and repeat counts. The WAVE export repeats the 256-byte attack twice and the 256-byte sustain three times, for 1,280 frames (160 ms). It uses each page from its addressed location, including in banks where the recognizable cue bytes begin one byte earlier.

At 8 kHz with unmasked A-law, the last 96 samples of the 750 Hz attack measure about 3,648 PCM RMS after removing the DC mean. The last 32 samples of the sustain measure 89 PCM RMS, about 32 dB quieter. Several SIT sustains are also roughly 33 dB below their attacks, while others have a quiet onset and a sustain near the attack level. Full-block replay preserves these differences. [Archived measurements](../archive/measurements/tone-fft-summary.json)

Across all 2,890 validated phrase menus in the archive, 4,018 submenu references have a repeat count above one. Referenced silence accounts for 2,560, the 750 Hz cue pages account for 600, and SIT sustains account for 854. The remaining four are the same ACTS alert entry `10 00 04 04`, referenced by phrases 5 and 63 in both banks of EACTS0AE. It selects four pages from `0x10` and repeats the range four times, yielding 512 ms at 8 kHz. This ties the repeat field to both tones and silence in these files. [ACTS alert WAV](../audio/eacts0ae/bank_00/phrase_05.wav) · [Corpus counts](../VALIDATION.json)

### SIT component layout

The menu describes three pitches in sequence. For each pitch, the bytes describe one attack page followed by a two-page sustain. A long component adds another pass through the sustain and then plays its first page once more. In `ESTD0AA` bank 0, the third component uses these exact submenu words.

| Component | Submenu bytes in play order | Frames at 8 kHz |
| --- | --- | --- |
| Short, phrase 8 | `1D 00 01 01`, then `1E 00 02 04` | `(1 + 2 × 4) × 256 = 2,304` (288 ms) |
| Long, phrase 9 | `1D 00 01 01`, then `1E 00 02 05`, then `1E 00 01 01` | `(1 + 2 × 5 + 1) × 256 = 3,072` (384 ms) |

The third word in the long component uses ordinary page, page-count and repeat fields. It points back to the first sustain page. There is no separate release field in these entries or separately addressed release sample. The last 32 frames of each of the five attack/sustain variants still contain carrier energy in both length forms. All 32 SIT menus follow this short/long structure. [ESTD0AA manifest](../audio/estd0aa/manifest.json) · [Worked byte offsets](../BYTE_MAP.md#follow-real-tone-data)

### Shared tone data and measured timing

Image addresses `0x1100` through `0x1FFF` contain the same 3,840 bytes in all nine copies across `ESTD0AA`, `ASTD0AB`, `FSTD0BA`, `EMCCS0CA`, `MWTTONE`, and `EDRMTONE`. The SHA-256 of that address range after zero fill is `d7595046b61df181a089349bfd793a445383fe2dc7bd1a5bbb255d777b78c995`. This proves reuse across the archived **EDRAM** loads. Nortel lists corresponding NT1X76 DRAM packs and identifies the four announcement voice files as SITLOAD sources. A corresponding DRAM ROM image would let us compare the waveforms with the shared load bytes. [Nortel DRAM and EDRAM Guide, Tables 3-4 and 4-2](https://www.gbppr.net/bsp/297-1001-527.pdf)

The final page of the low middle sustain (`0x1900`) repeats a 64-byte block with 11 cycles (1,375 Hz at 8 kHz). The high middle sustain ends with 23 cycles in a 128-byte block (`0x1C00`, 1,437.5 Hz). Nortel gives nominal middle carriers of 1,370.6 and 1,428.5 Hz, and specifies 274/380 ms for EDRAM. The archived menus expand to 288/384 ms. Each of the five attack pages begins with 32 zero codes (4 ms). Measuring from after that lead-in accounts for the long value of 380 ms and leaves the short at 284 ms. A fixed sample-rate change also fails to reconcile both lengths. The on-wire timing and gain need a capture from the SITLOAD path. [Nortel DRAM and EDRAM Guide, Table 4-2](https://www.gbppr.net/bsp/297-1001-527.pdf#page=59)

### French standard bank recovery

In `FSTD0BA`, bank 1 has a byte-identical copy of bank 0's SIT submenus and sample pages. The three misaligned directory entries and the fourth entry that lands on the previous SIT's last word have verified replacements. Use the [explicit repair](../FORMAT.md#malformed-references) to export the four corrected SITs from bank 1.

## Standalone records

`MWTTONE` and `EDRMTONE` share 17 records. `EDRMTONE` adds 47 records, including two DTMF sets and two constant-fill records. The two-byte big-endian count at the start of each record is the number of 16-bit words of payload. Each payload word holds two eight-bit sample codes. The exporter checks the archived regions and their record boundaries, then expands samples with the region's identified companding law. In these images, records with headers below `0xB5EA` use unmasked μ-law, and the rest use unmasked A-law. The law assignment comes from the archived waveform analysis. The header has no codec selector.

| Record | Header address | Header bytes | Sample bytes | What decodes |
| --- | --- | --- | --- | --- |
| Shared record 9 | `0x379E` | `01 F2` | 996 | 1004 Hz milliwatt carrier |
| Shared record 10 | `0x3BCA` | `03 E8` | 2,000 | Four-frequency receiver-off-hook howler |
| EDRMTONE record 47 | `0xCA42` | `00 C5` | 394 | DTMF 1, second set, approximately 690 and 1218 Hz |

The 394 samples in a DTMF record can represent whole cycles of both carriers. For DTMF 1, 34 and 60 cycles in 394 samples give about 690.4 and 1,218.3 Hz. The short WAVs contain the stored blocks. Service cadence and level are properties of playback on the card. `EDRMTONE` phrase 41 spans many standalone records. The converter flags that overlap and gives each record its own WAV. Record 1 retains code `0x94` at sample index 3, while the later copy in record 18 contains `0x54` there. [EDRMTONE manifest](../audio/edrmtone/manifest.json) · [MWTTONE manifest](../audio/mwttone/manifest.json)

## Independent waveform check

This check reconstructs the factory image from the file records, follows one phrase menu and three tone headers, and uses FFmpeg's G.711 decoder. Run it with Python 3 and FFmpeg on the path from the repository root. It compares the resulting PCM with the versioned WAVs sample for sample.

~~~python
from pathlib import Path
import struct
import subprocess
import wave

def image(name):
    raw = (Path("data/original") / name).read_bytes()
    result = bytearray(0x40000)
    if name.endswith(".bin44"):
        for i in range(0, len(raw), 44):
            record = raw[i:i + 44]
            if record[:2] in (b"G0", b"G2"):
                addr = int.from_bytes(record[3:6], "big")
                count = record[2]
                result[addr:addr + count] = record[6:6 + count]
    else:
        for line in raw.splitlines():
            if line.startswith(b"S2"):
                record = bytes.fromhex(line[2:].decode("ascii"))
                addr = int.from_bytes(record[1:4], "big")
                result[addr:addr + len(record) - 5] = record[4:-1]
    return result

def compare(codes, law, wav_path):
    mask = {"alaw": 0x55, "mulaw": 0x7F}[law]
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", law, "-ar", "8000", "-i", "pipe:0",
         "-f", "s16le", "pipe:1"],
        input=bytes(code ^ mask for code in codes), capture_output=True, check=True,
    ).stdout
    with wave.open(str(Path("audio") / wav_path)) as wav:
        assert pcm == wav.readframes(wav.getnframes()), wav_path
        print(wav_path, wav.getnframes(), "matching frames")
    return pcm

estd = image("estd0aa.bin44")
ptr, count, _ = struct.unpack_from("<HBB", estd, 4)
cue = b"".join(
    estd[256 * page:256 * (page + pages)] * repeats
    for page, pages, repeats in struct.iter_unpack("<HBB", estd[ptr:ptr + 4 * count])
)
compare(cue, "alaw", "estd0aa/bank_00/phrase_01.wav")

for name, address, law, clip in (
    ("mwttone", 0x3BCA, "mulaw", 10),
    ("edrmtone", 0x6CB2, "mulaw", 23),
    ("edrmtone", 0xCA42, "alaw", 47),
):
    data = image(name + ".txt80")
    count = 2 * int.from_bytes(data[address:address + 2], "big")
    codes = data[address + 2:address + 2 + count]
    compare(codes, law, f"{name}/tone-bank/tone_{clip:02d}.wav")
~~~

The frame counts are 1,280 for the cue, 2,000 for the howler, and 394 for each DTMF clip. A separate run also matched ESTD0AA SIT 1, the EDRMTONE copy of the howler, and all 32 DTMF WAVs. The four strongest bins in the howler are 351, 515, 613, and 651 of 2,000 samples, corresponding to 1404, 2060, 2452, and 2604 Hz.

### What supports the DTMF law assignment

For each key, measure the share of spectral power outside its two carrier bins, excluding DC and Nyquist. Across all 16 keys in each set, the decoder's selected law left less power outside the carriers than the alternate law.

| 394-sample DTMF blocks | μ-law expansion | A-law expansion |
| --- | ---: | ---: |
| First set | 0.0107% to 0.0140% | 0.0144% to 0.0178% |
| Second set | 0.0297% to 0.0461% | 0.0142% to 0.0249% |

Either law can leave the dominant frequencies visible. The comparison supports the law assignments for these stored blocks. The card's selection between the two sets is still open.

## What the encoder can reproduce

An independent readback of the same five custom phrases in `.bin44` and `.txt80` found identical menus and sample codes. The reserved 750 Hz test cue, three-burst prompt, and first two SITs retained their original menus and codes in both outputs. Each newly generated submenu entry used a repeat count of one.

| Test input | Observed output |
| --- | --- |
| `--tone 40 750@160` | 1,280 generated A-law samples. The dominant carrier was 750 Hz. |
| `--tone 41 howler` | The 2,000 stored μ-law samples converted to A-law, followed by 48 padding codes. All four carriers were present. Against direct μ-law expansion, the conversion had a maximum difference of 132 signed PCM units and about 42.4 dB signal-to-error ratio over the original block. |
| `--tone 42 dtmf:1:2` | The 394 stored A-law codes were identical, followed by 118 padding codes. |
| `--phrase 43 audio/estd0aa/bank_00/phrase_01.wav` | The 1,280 expanded factory cue codes were recovered exactly in a custom phrase. Both waveform copies and their order matched the factory menu's expansion. |
| `--tone 44 dtmf:1` | 394 codes converted from μ-law to A-law, followed by 118 padding codes. The two carrier bins were preserved. |

The encoder writes tone audio to ordinary announcement slots. Custom repeat-count authoring and standalone tone-bank writing remain open. [Encoder guide](../ENCODING.md#encode-tone-phrases) · [Bench status](../BENCH_STATUS.md)

## What remains on the card

An Ameritech patent describes prerecorded tones alongside words and silence in Northern Telecom's NT1X80AA memory. The Nortel guide names `MWTTONE.AA01` as the data file for the milliwatt and receiver-off-hook feature, with separate PM firmware: `EDRMAE01` or later for NT1X80AA, or `ED16AA01` or later for NT1X80BA. The announcement/tone archive supplies the data files. For SIT specifically, Nortel documents that SITLOAD downloads voice-file data into announcement RAM and that OFCENG.PM_PCM_PROTOCOL_SELECTION selects the coding law. These sources establish what gets loaded and what the waveform bytes carry. They leave open whether firmware or dedicated logic applies the repeats, adjusts gain, or changes the phase, sample selection or cadence. [US6442246B1, description of Fig. 2](https://patents.google.com/patent/US6442246B1/en) · [Nortel DRAM and EDRAM Guide, Tone feature and chapter 14](https://www.gbppr.net/bsp/297-1001-527.pdf)

The [bench checklist](../BENCH_STATUS.md#tone-playback-test) gives a repeat-count test and the settings to record.

Historical sine references and the phase/gain-fitting experiment remain in the [archive](../archive/README.md).
