"""Extract the XA-Core announcement loads and export surviving sample data."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import edram
import tone_bank


LOADS = [f'ANN{i}' for i in range(1, 9)] + ['DTM_BK3']
RECORD_SIZE = 259


def unwrap(path):
    data = path.read_bytes()
    if not data or len(data) % RECORD_SIZE:
        raise ValueError(f'{path.name} has a partial disk record')
    unwrapped = bytearray()
    for index in range(0, len(data), RECORD_SIZE):
        record = data[index:index + RECORD_SIZE]
        if record[:4] != bytes.fromhex('004c2c00') or record[48:] != b' ' * 211:
            raise ValueError(f'{path.name} has an unexpected disk wrapper at {index:#x}')
        unwrapped.extend(record[4:47] + b'\x16')
    edram.parse_bin44(unwrapped)
    return bytes(unwrapped)


def export_unreferenced_pages(path, name, audio):
    image = edram.Image.read(path)
    phrases = image.phrases()
    folder = audio / name
    used = set()
    out = {'load': name, 'orphan_audio': []}
    for phrase in phrases:
        for part in phrase.segments:
            used.update(range(part.page, part.page + part.pages))
    pages = []
    for page in range(16, (len(image.data) + 255) // 256):
        start = page * 256
        coverage = image.coverage[start:start+256]
        if page not in used and any(coverage):
            if len(coverage) != 256 or not all(coverage):
                raise ValueError(f'Partial orphan page in {name} at {start:#x}')
            pages.append(page)
    if pages:
        # Preserve the sequence of stored pages, skipping absent and referenced pages.
        raw = b''.join(image.read_bytes(page*256, 256, required=True) for page in pages)
        relative = 'orphan-pages.wav'
        pcm = edram.decode(raw)
        edram.write_wav(folder / relative, pcm, f'{name} unreferenced stored pages',
                        'Compacted in address order; see extra-audio.json for original page offsets.')
        out['orphan_audio'].append(dict(
            wav=relative, pages=pages, duration_seconds=len(raw)/edram.RATE,
            pcm_sha256=hashlib.sha256(pcm).hexdigest()
        ))

    return out


def reference_hashes(reference):
    refs = defaultdict(list)
    paths = sorted(reference.glob('*.bin44')) + sorted(reference.glob('*.txt80'))
    for path in paths:
        image = edram.Image.read(path)
        standalone = list(tone_bank.records(image))
        ranges = tone_bank.record_ranges(item for item, _ in standalone)
        for item, payload in standalone:
            if item['wav']:
                digest = hashlib.sha256(edram.decode(payload, item['codec'])).hexdigest()
                refs[digest].append([path.stem, item.get('label'), item['tone_name']])
        try:
            phrases = image.phrases(strict=False)
        except edram.FormatError:
            if not standalone:
                raise
            continue
        for phrase in phrases:
            try:
                edram.check_voice_ranges(phrase.bank, phrase.segments, ranges)
                pcm, _ = edram.render(image, phrase)
            except edram.FormatError:
                continue
            refs[hashlib.sha256(pcm).hexdigest()].append([path.stem, phrase.bank, phrase.number])
    return refs, len(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('factory', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--reuse-wav', action='store_true', help='Keep existing original exports and recompute extras')
    args = parser.parse_args()
    normalized = args.output / 'normalized'
    normalized.mkdir(parents=True, exist_ok=True)
    audio = args.output / 'audio'
    audio.mkdir(exist_ok=True)
    manifests = []
    extras = []
    for name in LOADS:
        path = normalized / f'{name}.bin44'
        path.write_bytes(unwrap(args.original / name))
        manifest = audio / name / 'manifest.json'
        if args.reuse_wav and manifest.is_file():
            manifests.append(json.loads(manifest.read_text(encoding='utf-8')))
        else:
            manifests.append(edram.export(path, audio, 'alaw-unmasked', segments=True))
        extras.append(export_unreferenced_pages(path, name, audio))
    if not (audio / 'listen.html').exists():
        edram.write_browser(audio, manifests)
    refs, files = reference_hashes(args.factory)
    matches = [
        dict(load=Path(m['source']).stem, phrase=p['number'], samples=p['samples'],
             matches=refs[p['pcm_sha256']])
        for m in manifests for p in m['phrases'] if p['wav']
    ]
    totals = dict(
        source_loads=len(manifests), validated_menu_entries=sum(len(m['phrases']) for m in manifests),
        source_phrase_wavs=len(matches), exact_factory_matches=sum(bool(x['matches']) for x in matches),
        factory_reference_loads=files, reference_waveforms=sum(len(m) for m in refs.values()),
        unique_reference_waveforms=len(refs),
        orphan_renders=sum(len(x['orphan_audio']) for x in extras)
    )
    for filename, data in (('extra-audio.json', extras), ('factory-exact.json', matches), ('summary.json', totals)):
        (audio / filename).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(totals), flush=True)


if __name__ == '__main__':
    main()
