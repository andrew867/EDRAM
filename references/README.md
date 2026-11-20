# Generated SIT comparison signals

The sit/ WAV files are generated reference signals, not recovered EDRAM sample audio. They interpret validated menus' low/high and short/long selections using Bellcore's North American SIT parameters. The stored-audio WAVs remain unchanged in ../audio/.

Bellcore SR-2275, Issue 3, December 1997, table 6-45, specifies first-component frequencies of 913.8 or 985.2 Hz, second-component frequencies of 1370.6 or 1428.5 Hz, and a third-component frequency of 1776.7 Hz. Short and long durations are 274 and 380 ms. Nortel's guide lists the same EDRAM timing and frequencies.

References use 8 kHz 16-bit mono PCM, a chosen peak amplitude of 5000, two-millisecond edge ramps and no inter-component gap. The peak roughly matches the stored attack waveforms; it is a comparison setting rather than a recovered hardware calibration.

ITU-T E.180/Q.35 (03/1998), section 7, specifies broader international ranges of 950/1400/1800 Hz, each with 50 Hz tolerance, and 330 ms with 70 ms tolerance. It permits up to a 30 ms gap between components. These broader limits do not explain the encoded EDRAM sustain blocks.

- [Bellcore Notes on the Networks](https://vtda.org/docs/telephony/BellCore/SR-2275_Bellcore_NotesOnTheNetworks_Issue3_Dec97.pdf)
- [Nortel DRAM and EDRAM Guide](https://www.gbppr.net/bsp/297-1001-527.pdf)
- [ITU-T E.180/Q.35](https://www.itu.int/rec/T-REC-E.180-199803-I/en)

The index maps source announcement paths to generated profiles and preserves selected frequencies and durations. This comparison option does not claim that the original SIT byte decoding has been solved.
