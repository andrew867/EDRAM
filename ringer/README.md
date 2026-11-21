# Nortel T7316 ringer synthesis

Four patterns measured from the [T7316 recording](https://www.youtube.com/watch?v=e4bi9dy1BQ8), ordered by first appearance. Times are approximate. The pulse widths are inferred from the harmonic spectrum of the recorded phone.

| Rendered WAV | First heard | Frequency and time per stage | Cycle | Duty |
| --- | ---: | --- | ---: | ---: |
| [Low fast](audio/t7316-low-fast.wav) | 0:03.6 | 333⅓ Hz for 50 ms, 250 Hz for 50 ms | 100 ms | 50% |
| [High fast](audio/t7316-high-fast.wav) | 0:05.8 | 666⅔ Hz for 50 ms, 500 Hz for 50 ms | 100 ms | 50% |
| [Narrow pulse](audio/t7316-narrow-pulse.wav) | 0:10.7 | 333⅓ Hz for 87.5 ms, 500 Hz for 87.5 ms | 175 ms | 25% |
| [Three pitch](audio/t7316-three-pitch.wav) | 0:13.1 | 333⅓ Hz for 136 ms, 500 Hz for 76 ms, 666⅔ Hz for 76 ms | 288 ms | 50% |

The low-fast, high-fast and three-pitch patterns are dominated by odd harmonics. In the narrow-pulse pattern, the second harmonic can be stronger than the fundamental, and the fourth is strongly suppressed. The shorter period visible in that recording is consistent with a roughly quarter-duty pulse. The synthesis uses those oscillator shapes with a harmonic roll-off. The handset speaker, amplifier and room response are unmodeled.


## Build and use

Run from the repository root with a C99 compiler, including GCC from an initialized MSYS2 MINGW64 shell.

```sh
cc -std=c99 -Wall -Wextra -Werror -pedantic ringer/ringer.c ringer/demo.c -lm -o ringer-demo
./ringer-demo
```

The demo writes four 2-second, 16 kHz mono WAVs in the current directory. For a DSP or firmware integration, call `ringer_init` with a profile and a sample rate from 8 to 192 kHz before playback. It builds up to three 256-entry signed PCM tables and calculates sample-count boundaries and phase increments. Call `ringer_next` once per output sample. It uses a continuous 32-bit phase accumulator, a lookup, and integer stage timing. Apply the external call-ring cadence and output level in the host. Each instance uses about 1.6 KiB of state.
