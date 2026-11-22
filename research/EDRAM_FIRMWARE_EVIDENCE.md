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

Both images refer to the staging-base table at `0x010A4E` and the control-address table at `0x010D3A`. Examples for the first active channel are staging at `0x200100` or `0x202100` and control at `0x300602`. The channel service iterates over channel indices 1 through 30. The alternate entry clears the protected pages of the first eight banks and runs a table with four nonempty copy entries.

| Source | Destination | 16-bit words |
| ---: | ---: | ---: |
| `0x01B600` | `0x400800` | `0x0321` |
| `0x01BC42` | `0x440700` | `0x018A` |
| `0x01C000` | `0x480800` | `0x0321` |
| `0x01C642` | `0x4C0700` | `0x018A` |

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
- The tone fixture applies the native copy routine at `0x00EA2A` to the four startup entries before playing built-in slots 8 through 39. It sets the selector to `0x4040` and low-memory byte `[0x000001]` to 1. It compares native staging with a direct repeat of the waveforms addressed by each descriptor, including the trailing zero codes. A second test sets the byte to 0 and records the changed hash for slot 8.

The instruction at `0x01A582` in ED16AA07 compares a register byte with absolute memory location `0x000001`. Setting that RAM byte is part of the test profile. The waveforms and tested duration fields agree across the two images. An independent implementation can consume them as sample records and finite durations and compare its output with the hashes.

## Hardware evidence still needed

The S-records supply the application and its executive prefix. The listings also call resident service entries near `0x03F000` and jump to code at `0x020D20`, outside the supplied ranges. A card trace or resident image would establish the real boot-time selector and low-memory byte, command transport and interrupt timing, control-register meanings, sample law and level at the network interface, and capture/recording and continuous-tone behavior. The test boundary is the sequence of 256-byte staging writes and the loader and request-decoder state transitions.
