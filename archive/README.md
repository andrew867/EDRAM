# Historical tone experiments

The earlier converter offered generated Nortel/Bellcore SIT previews, repaired sample bytes and a fitted sustain-loop model. The current extractor and player decode the addressed samples. The historical artifacts here preserve the earlier comparisons.

| Folder or file | Contents |
| --- | --- |
| [measurements](measurements) | FFT results, plots, historical playback notes and two loop examples |
| [examples](examples) | Generated SIT references, phase/gain-fitted loop WAVs, and historical mixed page dumps |
| [sit_reference.py](sit_reference.py), [plot_sit.py](plot_sit.py) | Standard reference synthesis and comparison plots |
| [tone_playback.py](tone_playback.py) | Experimental loop renderer |
| [analyze_tones.py](analyze_tones.py), [tone_experiments.py](tone_experiments.py) | Analysis of decoded sample data and alternate codec hypotheses |
| [workflows](workflows) | Retired workflow definitions |

From the repository root, `python -m archive.tone_playback data/original/estd0aa.bin44 decoded/estd0aa-comparison` generates a historical A/B experiment in a separate output directory. The spectrum scripts use NumPy, the plot also uses Matplotlib, and the alternate codec experiment uses FFmpeg.

The [current tone notes](../research/TONE_PLAYBACK.md) explain the measured waveforms, repeat field and remaining hardware questions.
