# EDRAM firmware evidence

The [behavior specification](EDRAM_BEHAVIOR_SPEC.md) defines the implementation boundary. The tests below execute the original instructions from both recovered images in a Motorola 68000 emulator. The C implementation and the acceptance vectors use observable inputs and outputs.

## Binary anchors

Addresses are absolute 68k byte addresses. Names describe the observed operations. The [address map](../data/xacore/firmware/address-map.json) pins the two flat images by SHA-256 and identifies which ranges the S-records supply.

| Operation | ED16AA07 | EDRMAE11 |
| --- | ---: | ---: |
| Register the loaded bank range | `0x0117DE` | `0x0117DE` |
| Apply incoming data record | `0x011978` | `0x011978` |
| Process announcement load messages | `0x011B76` | `0x011B86` |
| Sum the directory entry and descriptor bytes | `0x013194` | `0x0131DE` |
| Start selected phrase | `0x013206` | `0x013250` |
| Decode descriptor | `0x013292` | `0x0132DC` |
| Initialize the alternate sample record path | `0x01332A` | `0x01336E` |
| Advance page range and repeats | `0x01350C` | `0x013550` |
| Stage a playback block | `0x01355A` | `0x01359E` |
| Copy staging into a capture page | `0x0135FC` | `0x013640` |
| Interpret the playlist | `0x013644` | `0x013688` |
| Decode the application request | `0x013CA0` | `0x013CE4` |
| Service active channels | `0x01436A` | `0x0143AE` |
| Dispatch outer PM message type | `0x014D04` | `0x014CC4` |
| Scan bank integrity in the background | `0x01A42E` | `0x01A400` |
| Fill staging from an alternate sample record | `0x01A55A` | `0x01A52C` |
| Copy one sample page | `0x01A618` | `0x01A5EA` |
| Clear one sample page | `0x01A750` | `0x01A722` |
| Embedded startup copy table | `0x01A7F2` | `0x01A7C4` |
| Built-in phrase directory | `0x01A842` | `0x01A814` |

Both images refer to the staging-base table at `0x010A4E` and the control-address table at `0x010D3A`. Examples for the first active channel are staging at `0x200100` or `0x202100` and control at `0x300602`. The channel service iterates over channel indices 1 through 30.

## Firmware download and startup

Both binaries enter the primary stub at `0x0412` for application startup. When the initialization marker is absent, the handshake routine at `0x010106` waits for `0x7D` and processes `0x7E` payloads until finish opcode `0x77`. The assembly at `0x010308` through `0x010322` compares the sum or accepts header word `0x4342` and calls `0x0418`. At that entry, both builds clear `0x0700–0x0FFF` in the first eight banks, seed the embedded data, clear transfer workspace, set `0x0536` to `0x12345678` and call `0x00E900`. The copy table contains eight positions, four with nonzero lengths.

The verifier exercises a matching checksum, mismatching checksum, and the `0x4342` header branch with the executive prefix already staged. It compares all eight protected windows against the codec's startup model, including bytes on both sides of each window. The two firmware sums are `0x1DC65AF5` and `0x1DAC0413`, matching their archived S6 values. The verifier stops at the executive handoff and uses the recovered loader and sequencer separately to test the loaded voice files.

| Source | Destination | Words | Stored waveform data |
| ---: | ---: | ---: | --- |
| `0x01B600` | `0x400800` | `0x0321` | μ-law 750 Hz cue page and records near 914, 985 and 1370 Hz |
| `0x01BC42` | `0x440700` | `0x018A` | μ-law records near 1429 and 1776 Hz |
| `0x01C000` | `0x480800` | `0x0321` | A-law counterparts to the first group |
| `0x01C642` | `0x4C0700` | `0x018A` | A-law counterparts to the second group |

All four ranges are identical across the two firmware builds. Slot 1 uses the first 750 Hz page under both tested selectors. Slots 4 through 7 resolve to `0x400900`, `0x400AA8`, `0x400C42`, and `0x440700` under `0x4040`. Under `0x5050` each address increases by `0x80000`. Both builds looped the stored sample records byte for byte. The preview's law follows the record's identified storage law.

## How to reproduce

From the repository root, install the optional Unicorn dependency and run the [trace verifier](../data/xacore/firmware/verify_behavior.py). It compares both images with the checked-in [vectors](../data/xacore/firmware/playback-vectors.json), including exact raw byte hashes. The main EDRAM decoder has no Unicorn dependency.

```sh
python -m pip install unicorn==2.1.4
python data/xacore/firmware/verify_behavior.py
```

The harness maps the flat image at `0x400`, allocates a stack and uses caller-seeded RAM. It sets the current-channel pointer, bank base, directory entry, and staging destination before invoking the selected phrase routine. It calls the real one-block emit routine and intercepts the sequencer-advance and playback-error routines as observable endpoints. The loader receives frames through a stub at `0x00FE56`, and the harness records each reply at `0x00FE8C`. The request-decoder tests replace the resident queue-buffer release at `0x03F270` with a successful return.

- The ordinary fixture seeds physical pages 13, 16, 17, and 18 with distinct nonzero bytes and verifies all emitted bytes. The archived `ESTD0AA` test uses the bank-local slot 8 entry and checks both raw staging and decoded PCM. The checksum failure is injected before playback begins.
- The loader fixture seeds the first bank with `0xA5`, submits four data records, and checks both protected boundaries and the full protected region. It reads the sum and registration state from native RAM. A bad `.bin` sum leaves the already-written payload in memory. The bank remains in its loading state.
- The application request fixture sends bank select `80` and phrase `09` to channel 1 through the firmware's decoded queue buffer. It checks the exact generated playlists, stored mode, and next channel state.
- The tone fixture applies the native copy routine at `0x00EA2A` to the four startup entries before playing built-in slots 8 through 39. It sets low-memory byte `[0x000001]` to 1 and compares native staging with a direct repeat of the waveforms for selectors `0x4040` and `0x5050`, including the trailing zero codes. A further test uses selector `0x4040`, sets the byte to 0, and records the changed hash for slot 8.

The cue fixture uses the same startup copies and starts slots 1 and 2. It records every page address consumed by the native staging routine. Slot 1 emits five copies of `0x400800`. Slot 2 adds the silence ranges at `0x400700`. Both selectors and firmware builds produce the same 1,280 and 7,936 staged sample codes, respectively.

The instruction at `0x01A582` in ED16AA07 compares a register byte with absolute memory location `0x000001`. Setting that RAM byte is part of the test profile. The first-descriptor initializer at `0x01332A` or `0x01336E` relocates the first waveform record by `0x80000` in the `0x5050` profile. The in-buffer advance at `0x01A758` or `0x01A72A` uses the next record address directly. Both images reproduced the resulting mixed-address sequence. An independent implementation can consume them as sample records and finite durations and compare its output with the hashes.

## Standalone tone-bank playback

The verifier rebuilds MWTTONE and EDRMTONE and feeds their parsed S2 payloads through the OEM load loop at the decoded message boundary. It uses one-based bank number 2 to test address relocation. Both builds acknowledge the native S6 values and register the original bank types. The PM application's `TONE` branch accepts the archived MWTTONE footer without a comparison to the incoming word sum. Host-side validation of changed MWTTONE images needs a verified checksum rule.

The harness executes the actual playlist sequencer, which selects a built-in duration-`0xFFFFFF` descriptor and applies the loaded bank offset. It observes howler slot 42 at `0x443BCA` and milliwatt slot 49 at `0x44379E` for bank number 2. At selector `0x4040` with low-memory byte `1`, each 256-byte staging block follows the original waveform continuously across record boundaries. Both original banks and a regenerated EDRMTONE with record 14 copied to record 9 were tested across every available continuous slot from 40 through 63. A second EDRMTONE test uses selector `0x5050` and loads the bank at physical index 2, where the relocated descriptor addresses resolve. Both DTMF sets retain their sample bytes in RAM. The service routing that selects the DTMF records remains unresolved.

## Hardware evidence still needed

The S-records supply the application and its executive prefix. The listings also call resident service entries near `0x03F000` and jump to code at `0x020D20`, outside the supplied ranges. A card trace or resident image would establish the initial hardware entry, the provisioned playback selector and low-memory byte, command transport and interrupt timing, control-register meanings, sample law and level at the network interface, capture and recording behavior, and service timing on the line. The test boundary is the sequence of 256-byte staging writes and the loader and request-decoder state transitions.
