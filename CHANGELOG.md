# EDRAM 0.2.0 alpha 1

First tagged release of the EDRAM tools for Nortel DMS-100 and SL-100 announcement loads.

- Decode binary bin44 and text S-record loads into WAVs. Browse announcements, SITs, DTMF and other tones in the offline audio player.
- Inspect phrase tables, byte addresses and repeat counts. Each export records the source hashes and flags incomplete or invalid references.
- Build a single-bank announcement load and prepare an SLM tape image for lab testing.

## Try it

Download **Source code (zip)**, extract it, and open `audio/listen.html` locally. To decode another load, use Python 3.10 or newer.

~~~sh
python edram.py data/original/estd0aa.bin44 -o decoded --segments
~~~

The reference audit verified 5,377 WAVs from 61 loads. SITs and tones use stored samples and menu timing. NT1X80 hardware timing, gain and acceptance of generated loads still need bench verification.

[Format guide](AUDIO_FORMAT_GUIDE.md) · [Validation](VALIDATION.json) · [Hardware checklist](BENCH_STATUS.md)
