#!/usr/bin/env python3
"""Plan, transcribe and index all exported EDRAM WAVs, deduplicating identical PCM."""
from __future__ import annotations
import argparse
from array import array
from collections import Counter
import csv
import hashlib
import html
from itertools import chain
import json
import re
import signal
from pathlib import Path
import sys
import wave

from edram import BANK_SIZE, PAGE_SIZE
from tone_bank import bank_clips, raw_bank_paths

NORTEL_CATALOG = Path(__file__).resolve().parent / "references" / "nortel-phrases.csv"
NORTEL_GUIDE = "https://www.gbppr.net/bsp/297-1001-527.pdf"


def read_pcm(path):
    with wave.open(str(path)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 8000):
            raise ValueError(f"unexpected WAV format: {path}")
        return wav.readframes(wav.getnframes())


def is_silence(pcm):
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return not samples or max(abs(s) for s in samples) <= 8


TONE_FIELDS = ("tone_name", "tone_components", "frequencies_hz")
OLD_TONE_FIELDS = ("rendering", "sit_components", "source_pcm_sha256", "reference_wav")


def tone_clip_fields(entry):
    return {key: entry[key] for key in TONE_FIELDS if key in entry}


def refresh_tone_clips(root, clips):
    entries = {}
    available = {}
    for path in root.glob("*/manifest.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        available[path.parent.name] = {
            (Path(path.parent.name) / p["wav"]).as_posix()
            for p in chain(manifest["phrases"], manifest["segments"]) if p["wav"]
        }
        entries.update({(Path(path.parent.name) / p["wav"]).as_posix(): p for p in manifest["phrases"]
                        if p["wav"] and ("_sit_" in p["label"] or p.get("tone_name"))})
    kept = [clip for clip in clips if clip["source"] not in available or clip["path"] in available[clip["source"]]]
    changed = len(kept) != len(clips)
    clips[:] = kept
    for clip in clips:
        entry = entries.get(clip["path"])
        if entry is None:
            continue
        fields = tone_clip_fields(entry)
        fields.update(seconds=entry["duration_seconds"], pcm_sha256=entry["pcm_sha256"])
        for key in TONE_FIELDS + OLD_TONE_FIELDS:
            if key in clip and key not in fields:
                del clip[key]
                changed = True
        if clip["content"] != "tone":
            clip["asr_before_tone_identification"] = clip["transcript"]
            clip["transcript"] = {"text": "", "status": "tone", "review_recommended": False,
                                  "human_verified": False, "speaker": None}
            clip["content"] = "tone"
            changed = True
        changed |= any(clip.get(key) != value for key, value in fields.items())
        clip.update(fields)
    return changed


def make_plan(root):
    clips = []
    tone_hashes = set()
    annotation_path = root.parent / "annotations.json"
    annotations = json.loads(annotation_path.read_text(encoding="utf-8")) if annotation_path.exists() else {}
    for path in sorted(root.glob("*/manifest.json")):
        m = json.loads(path.read_text(encoding="utf-8"))
        source = Path(m["source"]).stem
        tone_segments = set()
        for p in m["phrases"]:
            annotation = annotations.get((Path(source) / p["wav"]).as_posix(), {}) if p["wav"] else {}
            if "_sit_" in p["label"] or annotation.get("content") == "tone":
                tone_segments.update((p["bank"], s["page"], s["pages"]) for s in p["segments"])
            elif all(s["page"] in (13, 14, 15, 16) and s["pages"] == 1 for s in p["segments"]):
                tone_segments.update((p["bank"], s["page"], s["pages"]) for s in p["segments"])
        for kind, entries in (("announcement", m["phrases"]), ("segment", m["segments"])):
            for p in entries:
                if not p["wav"]:
                    continue
                relative = (Path(source) / p["wav"]).as_posix()
                pcm = read_pcm(root / relative)
                digest = hashlib.sha256(pcm).hexdigest()
                silent = is_silence(pcm)
                annotation = annotations.get(relative, {})
                tone = (p.get("tone_name") or annotation.get("content") == "tone" or "_sit_" in p.get("label", "") or
                        (kind == "segment" and (p["bank"], p["page"], p["pages"]) in tone_segments) or
                        (kind == "announcement" and all(s["page"] in (13, 14, 15, 16) and s["pages"] == 1 for s in p["segments"])))
                if tone and not silent:
                    tone_hashes.add(digest)
                clips.append({"path": relative, "source": source, "kind": kind, "bank": p["bank"],
                              "label": p.get("label", Path(p["wav"]).stem), "pcm_sha256": digest,
                              "seconds": len(pcm) / 16000, "content": "silence" if silent else "speech",
                              "description": annotation.get("label", ""), "annotation_provenance": annotation.get("provenance"),
                              **tone_clip_fields(p)})
    for clip in clips:
        if clip["pcm_sha256"] in tone_hashes:
            clip["content"] = "tone"
    tasks = {}
    for clip in clips:
        if clip["content"] == "speech":
            tasks.setdefault(clip["pcm_sha256"], clip["path"])
    return {"clips": clips, "tasks": [{"pcm_sha256": h, "path": p} for h, p in sorted(tasks.items())],
            "counts": dict(Counter(c["content"] for c in clips))}


def clip_timeout(signum, frame):
    raise TimeoutError("recognition exceeded the per-clip time limit")


def run_shard(root, plan_path, output, shard, shards, model_size, resume_parts=None):
    from faster_whisper import WhisperModel
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    tasks = [t for i, t in enumerate(plan["tasks"]) if i % shards == shard]
    if output.exists():
        results = json.loads(output.read_text(encoding="utf-8"))["results"]
    else:
        results = {}
    if resume_parts:
        for checkpoint in sorted(resume_parts.glob("transcripts-part-*.json")):
            results.update(json.loads(checkpoint.read_text(encoding="utf-8"))["results"])
    keys = {t["pcm_sha256"] for t in tasks}
    results = {key: value for key, value in results.items() if key in keys}
    if all(t["pcm_sha256"] in results and results[t["pcm_sha256"]]["status"] != "error" for t in tasks):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"shard": shard, "shards": shards, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"shard": shard, "tasks": len(tasks), "resumed": len(results), "complete": True}), flush=True)
        return
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1)
    bounded = hasattr(signal, "SIGALRM")
    if bounded:
        signal.signal(signal.SIGALRM, clip_timeout)
    print(json.dumps({"shard": shard, "tasks": len(tasks), "resumed": len(results)}), flush=True)
    for i, task in enumerate(tasks):
        key = task["pcm_sha256"]
        if key in results and results[key]["status"] != "error":
            continue
        path = root / task["path"]
        if hashlib.sha256(read_pcm(path)).hexdigest() != key:
            raise ValueError(f"audio changed after plan: {path}")
        try:
            if bounded:
                signal.alarm(90)
            segments, info = model.transcribe(str(path), beam_size=5, temperature=0.0,
                max_new_tokens=128, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
                condition_on_previous_text=False, word_timestamps=False)
            parts = [{"start": s.start, "end": s.end, "text": s.text.strip(),
                      "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob,
                      "compression_ratio": s.compression_ratio} for s in segments]
            text = " ".join(p["text"] for p in parts).strip()
            review = (not text or info.language_probability < 0.6 or
                      any(p["avg_logprob"] < -0.65 or p["no_speech_prob"] > 0.5 or p["compression_ratio"] > 2.4 for p in parts))
            result = {"text": text, "language": info.language,
                      "language_probability": info.language_probability, "segments": parts,
                      "review_recommended": review, "status": "transcribed" if text else "no_speech_detected",
                      "model": model_size, "engine": "faster-whisper 1.2.1", "speaker": None,
                      "human_verified": False,
                      "decoding": {"beam_size": 5, "temperature": 0, "max_new_tokens": 128,
                                   "clip_timeout_seconds": 90 if bounded else None}}
        except TimeoutError as exc:
            result = {"status": "model_timeout", "text": "", "review_recommended": True,
                      "error": str(exc), "human_verified": False, "speaker": None}
        except Exception as exc:
            result = {"status": "error", "text": "", "review_recommended": True, "error": str(exc),
                      "human_verified": False, "speaker": None}
        finally:
            if bounded:
                signal.alarm(0)
        results[key] = result
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"shard": shard, "shards": shards, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if i % 10 == 0 or i + 1 == len(tasks):
            print(json.dumps({"shard": shard, "done": i + 1, "total": len(tasks), "path": task["path"], "text": result["text"]}, ensure_ascii=False), flush=True)
    if not output.exists():
        output.write_text(json.dumps({"shard": shard, "shards": shards, "results": results}), encoding="utf-8")


def load_nortel_catalog(path):
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as file:
        rows = {}
        for row in csv.DictReader(file):
            if not row["pcm_sha256"]:
                continue
            key = (row["load"].casefold(), int(row["bank"]), int(row["phrase"]), row["pcm_sha256"])
            if key in rows:
                raise ValueError(f"duplicate Nortel catalog key: {key[:3]}")
            rows[key] = row
    return rows


def catalog_entry(clip, catalog):
    if clip["kind"] != "announcement":
        return None
    phrase = re.match(r"phrase_(\d+)(?:_|$)", clip["label"])
    if not phrase:
        return None
    pcm_hash = clip.get("source_pcm_sha256", clip.get("pcm_sha256"))
    return catalog.get((clip["source"].casefold(), clip["bank"], int(phrase[1]), pcm_hash))


def apply_nortel_transcripts(clips, catalog):
    changed = False
    for clip in clips:
        old = clip["transcript"]
        entry = catalog_entry(clip, catalog) or {}
        preferred = entry.get("transcript_text")
        if not preferred and "catalog_page" not in old and not entry.get("intonation") and not entry.get("category"):
            continue
        t = old.copy()
        t["text"] = t.pop("asr_text", t["text"])
        t["status"] = t.pop("asr_status", t["status"])
        for field in ("text_source", "catalog_page", "intonation", "catalog_category"):
            t.pop(field, None)
        if preferred and clip["content"] == "speech":
            if preferred != t["text"]:
                t["asr_text"] = t["text"]
                t["text"] = preferred
            if t["status"] == "no_speech_detected":
                t["asr_status"] = t["status"]
                t["status"] = "transcribed"
            t["text_source"] = entry["transcript_basis"]
        if entry.get("intonation"):
            t["intonation"] = entry["intonation"]
        if entry.get("category"):
            t["catalog_category"] = entry["category"]
        if preferred or entry.get("intonation") or entry.get("category"):
            t["catalog_page"] = entry["printed_page"]
        if t != old:
            clip["transcript"] = t
            changed = True
    return changed


def write_player(root, clips, *, catalog_path=NORTEL_CATALOG):
    catalog = load_nortel_catalog(catalog_path)
    stored_tones = []
    raw_paths = set()
    for path in sorted(root.glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        stored_tones.extend(bank_clips(manifest))
        raw_paths.update(raw_bank_paths(manifest, BANK_SIZE, PAGE_SIZE))
    rows = []
    for clip in chain(stored_tones, clips):
        if clip["path"] in raw_paths:
            continue
        t = clip["transcript"]
        text = t["text"] or clip.get("tone_name") or clip.get("description") or {
            "silence": "[Silence]", "tone": "[Tone sequence or component]",
        }.get(clip["content"], "[No speech detected, review]")
        review = "Review" if t.get("review_recommended") else ""
        bank_label = "tone bank" if clip["kind"] == "tone-bank" else f"bank {clip['bank']}"
        title = f"{clip['source']} / {bank_label} / {clip['label']}"
        words = html.escape(text)
        entry = catalog_entry(clip, catalog)
        if entry:
            name, note = html.escape(entry["nortel_name"]), html.escape(entry["catalog_note"])
            page = html.escape(entry["printed_page"])
            source = f'{NORTEL_GUIDE}#page={int(entry["pdf_page"])}'
            heading = f' <code>{name}</code>' if name else ""
            category = html.escape(entry.get("category", ""))
            if category:
                heading += f' ({category})'
            intonation = html.escape(entry.get("intonation", ""))
            if intonation and not intonation.isdecimal():
                words += f' <span class="intonation">({intonation} intonation)</span>'
            elif intonation:
                words += f' <span class="intonation">(intonation {intonation})</span>'
            description = f'<small>{note}</small>' if note else ""
            details = f'<div class="catalog">Nortel catalog{heading} <a href="{source}">p. {page}</a>{description}</div>'
            words = f'{details}<span class="words">{words}</span>'
            if t.get("text_source"):
                words += '<small>Catalog-checked transcript</small>'
        url = html.escape(clip["path"], quote=True)
        if clip["kind"] == "tone-bank":
            play = f'<button data-src="{url}">Play stored tone</button>'
        else:
            play = f'<button data-src="{url}">Play stored audio</button>'
        if clip.get("frequencies_hz"):
            details = ", ".join(f"{freq:g} Hz" for freq in clip["frequencies_hz"])
            if clip["kind"] == "tone-bank":
                details += f' / sample address 0x{clip["sample_address"]:x} / {clip["codec"]}'
            words = f'{words}<small>{details}</small>'
        flag = ' data-tone="true"' if clip["content"] == "tone" else ""
        rows.append(f'<tr data-kind="{clip["kind"]}" data-review="{str(bool(review)).lower()}"{flag}><td>{html.escape(title)}'
                    f'<small>{clip["kind"]}, {clip["seconds"]:.3f}s, {html.escape(t.get("language") or clip["content"])}</small></td>'
                    f'<td class="transcript">{words}<small class="review">{review}</small></td>'
                    f'<td>{play} <a href="{url}" download>WAV</a></td></tr>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>EDRAM announcement player and transcripts</title><style>
body{max-width:1400px;margin:1rem auto;padding:0 1rem;font:16px system-ui;background:#101820;color:#edf4f9}a{color:#7ad8ff}
header{position:sticky;top:0;background:#101820;padding:.6rem 0;border-bottom:1px solid #607888}h1{margin:.4rem 0}
input,select,button{font:inherit;padding:.4rem}input{width:min(650px,80%)}audio{width:100%;height:38px}
table{width:100%;border-collapse:collapse}td{padding:.65rem;border-bottom:1px solid #334452}td:first-child{width:31%}small{display:block;color:#a5bac9}.review{color:#ffc46b}
#now{margin:.5rem 0;color:#9ee5ff}#words{white-space:pre-wrap}.transcript{max-width:650px}button{cursor:pointer}
.catalog{margin-bottom:.35rem;color:#a5bac9;font-size:.86rem}.catalog code{color:#edf4f9}.catalog a{margin-left:.2rem}
.intonation{color:#a5bac9}
@media(max-width:700px){td{display:block}td:first-child{width:auto}header p{font-size:13px}}
</style><header><h1>EDRAM announcement archive</h1><p>Catalog-checked transcripts include Nortel phrase names and intonation. Use Tone banks for individual MWTTONE and EDRMTONE records.</p>
<input id="q" aria-label="Search the archive" placeholder="Search transcripts, tone names, loads or phrase IDs">
<select id="kind" aria-label="Clip type"><option value="">All clips</option><option value="announcement" selected>Announcements</option><option value="segment">Speech and tone fragments</option><option value="tone-bank">Tone banks</option><option value="tone">Tones</option></select>
<label><input type="checkbox" id="review" style="width:auto">Needs review</label><span id="count"></span>
<audio controls id="player"></audio><div id="now">Select a recording</div><div id="words"></div></header>
<table><tbody>ROWS</tbody></table><script>
const player=document.querySelector('#player'), rows=[...document.querySelectorAll('tr')];
function filter(){let n=0;const q=document.querySelector('#q').value.toLowerCase(),k=document.querySelector('#kind').value,r=document.querySelector('#review').checked;
rows.forEach(row=>{const type=k==='tone'?row.dataset.tone==='true':!k||row.dataset.kind===k;row.hidden=!(row.textContent.toLowerCase().includes(q)&&type&&(!r||row.dataset.review==='true'));if(!row.hidden)n++;});document.querySelector('#count').textContent=' '+n+' clips';}
document.querySelectorAll('input,select').forEach(e=>e.addEventListener('input',filter));filter();
document.addEventListener('click',e=>{if(e.target.dataset.src){const row=e.target.closest('tr');player.src=e.target.dataset.src;player.play();document.querySelector('#now').textContent=(e.target.dataset.playback||'Stored audio')+': '+row.cells[0].textContent;document.querySelector('#words').textContent=(row.querySelector('.words')||row.cells[1]).textContent;}});
</script></html>'''.replace("ROWS", "\n".join(rows))
    (root / "listen.html").write_text(page, encoding="utf-8")


def write_transcripts(root, summary, clips):
    summary["content_counts"] = dict(Counter(c["content"] for c in clips))
    summary["unique_speech_pcm"] = len({c["pcm_sha256"] for c in clips if c["content"] == "speech"})
    summary["review_recommended"] = sum(bool(c["transcript"].get("review_recommended")) for c in clips)
    summary["status_counts"] = dict(Counter(c["transcript"]["status"] for c in clips))
    summary["catalog_checked_transcripts"] = sum(bool(c["transcript"].get("text_source")) for c in clips)
    payload = json.dumps({"summary": summary, "clips": clips}, ensure_ascii=False, indent=2)
    (root / "transcripts.json").write_text(payload + "\n", encoding="utf-8")
    (root / "transcript-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (root / "transcripts.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        base_fields = ("language", "text", "status", "review_recommended", "human_verified")
        catalog_fields = ("text_source", "intonation", "catalog_category", "catalog_page", "asr_text")
        writer.writerow(("path", "kind", "content", *base_fields, *catalog_fields))
        for c in clips:
            t = c["transcript"]
            values = [t.get(key, False if key in ("review_recommended", "human_verified") else "")
                      for key in (*base_fields, *catalog_fields)]
            writer.writerow((c["path"], c["kind"], c["content"], *values))


def merge(root, plan_path, parts):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    results = {}
    for path in sorted(parts.glob("transcripts-part-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))["results"]
        overlap = results.keys() & data.keys()
        if overlap:
            raise ValueError(f"duplicate shard results: {len(overlap)}")
        results.update(data)
    expected = {t["pcm_sha256"] for t in plan["tasks"]}
    tonal_hashes = {c["pcm_sha256"] for c in plan["clips"] if c["content"] != "speech"}
    missing = expected - results.keys()
    extra = results.keys() - expected
    if missing or extra - tonal_hashes:
        raise ValueError(f"transcription coverage mismatch: {len(missing)} missing, {len(extra - tonal_hashes)} unrelated extra")
    errors = 0
    for clip in plan["clips"]:
        if clip["content"] == "speech":
            clip["transcript"] = results[clip["pcm_sha256"]]
        else:
            clip["transcript"] = {"text": "", "status": clip["content"], "review_recommended": False,
                                  "human_verified": False, "speaker": None}
        errors += clip["transcript"]["status"] == "error"
        if not (root / clip["path"]).is_file():
            raise ValueError(f"missing player target: {clip['path']}")
    apply_nortel_transcripts(plan["clips"], load_nortel_catalog(NORTEL_CATALOG))
    summary = {"wav_files": len(plan["clips"]), "unique_speech_pcm": len(expected),
               "content_counts": plan["counts"],
               "review_recommended": sum(c["transcript"].get("review_recommended", False) for c in plan["clips"]),
               "human_listening_review": False, "speaker_identities_assigned": False,
               "unused_results_reclassified_as_non_speech": len(extra)}
    write_transcripts(root, summary, plan["clips"])
    write_player(root, plan["clips"])
    print(json.dumps(summary, indent=2))
    if errors:
        raise ValueError(f"{errors} WAV entries have transcription errors; inspect and rerun affected shards")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "merge", "index"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--plan", type=Path, default=Path("transcription-plan.json"))
    parser.add_argument("--output", type=Path, default=Path("transcripts-part-0.json"))
    parser.add_argument("--parts", type=Path, default=Path("."))
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--model", default="small")
    parser.add_argument("--resume-parts", type=Path)
    args = parser.parse_args()
    if not 0 <= args.shard < args.shards:
        parser.error("shard index must be within shard count")
    if args.command == "plan":
        plan = make_plan(args.root)
        args.plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"clips": len(plan["clips"]), "unique_speech": len(plan["tasks"]), "content": plan["counts"]}))
    elif args.command == "run":
        run_shard(args.root, args.plan, args.output, args.shard, args.shards, args.model, args.resume_parts)
    elif args.command == "merge":
        merge(args.root, args.plan, args.parts)
    else:
        path = args.root / "transcripts.json"
        transcripts = json.loads(path.read_text(encoding="utf-8"))
        changed = refresh_tone_clips(args.root, transcripts["clips"])
        changed |= apply_nortel_transcripts(transcripts["clips"], load_nortel_catalog(NORTEL_CATALOG))
        if changed:
            write_transcripts(args.root, transcripts["summary"], transcripts["clips"])
        write_player(args.root, transcripts["clips"])


if __name__ == "__main__":
    main()
