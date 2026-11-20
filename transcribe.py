#!/usr/bin/env python3
"""Plan, transcribe and index all exported EDRAM WAVs, deduplicating identical PCM."""
from __future__ import annotations
import argparse
from array import array
from collections import Counter
import csv
import hashlib
import html
import json
from pathlib import Path
import sys
import wave


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


def make_plan(root):
    clips = []
    reference_path = root.parent / "references" / "sit" / "index.json"
    references = json.loads(reference_path.read_text(encoding="utf-8"))["clips"] if reference_path.exists() else {}
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
                tone = (annotation.get("content") == "tone" or "_sit_" in p.get("label", "") or
                        (kind == "segment" and (p["bank"], p["page"], p["pages"]) in tone_segments) or
                        (kind == "announcement" and all(s["page"] in (13, 14, 15, 16) and s["pages"] == 1 for s in p["segments"])))
                if tone and not silent:
                    tone_hashes.add(digest)
                clips.append({"path": relative, "source": source, "kind": kind, "bank": p["bank"],
                              "label": p.get("label", Path(p["wav"]).stem), "pcm_sha256": digest,
                              "seconds": len(pcm) / 16000, "content": "silence" if silent else "speech",
                              "description": annotation.get("label", ""), "annotation_provenance": annotation.get("provenance")})
    for clip in clips:
        clip["reference_wav"] = references.get(clip["path"], {}).get("path")
        if clip["pcm_sha256"] in tone_hashes:
            clip["content"] = "tone"
    tasks = {}
    for clip in clips:
        if clip["content"] == "speech":
            tasks.setdefault(clip["pcm_sha256"], clip["path"])
    return {"clips": clips, "tasks": [{"pcm_sha256": h, "path": p} for h, p in sorted(tasks.items())],
            "counts": dict(Counter(c["content"] for c in clips))}


def run_shard(root, plan_path, output, shard, shards, model_size):
    from faster_whisper import WhisperModel
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    tasks = [t for i, t in enumerate(plan["tasks"]) if i % shards == shard]
    if output.exists():
        results = json.loads(output.read_text(encoding="utf-8"))["results"]
    else:
        results = {}
    model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1)
    print(json.dumps({"shard": shard, "tasks": len(tasks), "resumed": len(results)}), flush=True)
    for i, task in enumerate(tasks):
        key = task["pcm_sha256"]
        if key in results and results[key]["status"] != "error":
            continue
        path = root / task["path"]
        if hashlib.sha256(read_pcm(path)).hexdigest() != key:
            raise ValueError(f"audio changed after plan: {path}")
        try:
            segments, info = model.transcribe(str(path), beam_size=5, vad_filter=True,
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
                      "human_verified": False}
        except Exception as exc:
            result = {"status": "error", "text": "", "review_recommended": True, "error": str(exc),
                      "human_verified": False, "speaker": None}
        results[key] = result
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"shard": shard, "shards": shards, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if i % 10 == 0 or i + 1 == len(tasks):
            print(json.dumps({"shard": shard, "done": i + 1, "total": len(tasks), "path": task["path"], "text": result["text"]}, ensure_ascii=False), flush=True)
    if not output.exists():
        output.write_text(json.dumps({"shard": shard, "shards": shards, "results": results}), encoding="utf-8")


def write_player(root, clips):
    rows = []
    for clip in clips:
        t = clip["transcript"]
        text = t["text"] or (clip.get("description") or ("[Silence]" if clip["content"] == "silence" else "[Tone sequence or component]" if clip["content"] == "tone" else "[No speech detected, review]"))
        review = "Review" if t.get("review_recommended") else ""
        title = f"{clip['source']} / bank {clip['bank']} / {clip['label']}"
        url = html.escape(clip["path"], quote=True)
        reference = clip.get("reference_wav")
        compare = f'<button data-src="{html.escape(reference, quote=True)}" data-reference="true">Standard SIT reference</button>' if reference else ""
        rows.append(f'<tr data-kind="{clip["kind"]}" data-review="{str(bool(review)).lower()}"><td>{html.escape(title)}'
                    f'<small>{clip["kind"]}, {clip["seconds"]:.3f}s, {html.escape(t.get("language") or clip["content"])}</small></td>'
                    f'<td class="transcript">{html.escape(text)}<small class="review">{review}</small></td>'
                    f'<td><button data-src="{url}">Play stored audio</button> <a href="{url}" download>WAV</a> {compare}</td></tr>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>EDRAM announcement player and transcripts</title><style>
body{max-width:1400px;margin:1rem auto;padding:0 1rem;font:16px system-ui;background:#101820;color:#edf4f9}a{color:#7ad8ff}
header{position:sticky;top:0;background:#101820;padding:.6rem 0;border-bottom:1px solid #607888}h1{margin:.4rem 0}
input,select,button{font:inherit;padding:.4rem}input{width:min(650px,80%)}audio{width:100%;height:38px}
table{width:100%;border-collapse:collapse}td{padding:.65rem;border-bottom:1px solid #334452}td:first-child{width:31%}small{display:block;color:#a5bac9}.review{color:#ffc46b}
#now{margin:.5rem 0;color:#9ee5ff}#words{white-space:pre-wrap}.transcript{max-width:650px}button{cursor:pointer}
@media(max-width:700px){td{display:block}td:first-child{width:auto}header p{font-size:13px}}
</style><header><h1>EDRAM announcement archive</h1><p>Machine transcripts, not yet reviewed by a person. Tone and silence labels come from the audio/menu classification. Speaker identities are unassigned. Stored SIT decoding is under investigation; Standard SIT reference plays a separately generated comparison signal.</p>
<input id="q" aria-label="Search transcripts" placeholder="Search words, source or phrase ID">
<select id="kind" aria-label="Clip type"><option value="">All clips</option><option value="announcement" selected>Announcements</option><option value="segment">Speech and tone fragments</option></select>
<label><input type="checkbox" id="review" style="width:auto">Needs review</label><span id="count"></span>
<audio controls id="player"></audio><div id="now">Select a recording</div><div id="words"></div></header>
<table><tbody>ROWS</tbody></table><script>
const player=document.querySelector('#player'), rows=[...document.querySelectorAll('tr')];
function filter(){let n=0;const q=document.querySelector('#q').value.toLowerCase(),k=document.querySelector('#kind').value,r=document.querySelector('#review').checked;
rows.forEach(row=>{row.hidden=!(row.textContent.toLowerCase().includes(q)&&(!k||row.dataset.kind===k)&&(!r||row.dataset.review==='true'));if(!row.hidden)n++;});document.querySelector('#count').textContent=' '+n+' clips';}
document.querySelectorAll('input,select').forEach(e=>e.addEventListener('input',filter));filter();
document.addEventListener('click',e=>{if(e.target.dataset.src){const row=e.target.closest('tr');player.src=e.target.dataset.src;player.play();document.querySelector('#now').textContent=(e.target.dataset.reference?'GENERATED STANDARD REFERENCE: ':'STORED AUDIO: ')+row.cells[0].textContent;document.querySelector('#words').textContent=row.cells[1].textContent;}});
</script></html>'''.replace("ROWS", "\n".join(rows))
    (root / "listen.html").write_text(page, encoding="utf-8")


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
    summary = {"wav_files": len(plan["clips"]), "unique_speech_pcm": len(expected),
               "content_counts": plan["counts"], "status_counts": dict(Counter(c["transcript"]["status"] for c in plan["clips"])),
               "review_recommended": sum(c["transcript"].get("review_recommended", False) for c in plan["clips"]),
               "human_listening_review": False, "speaker_identities_assigned": False,
               "unused_results_reclassified_as_non_speech": len(extra)}
    (root / "transcripts.json").write_text(json.dumps({"summary": summary, "clips": plan["clips"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "transcript-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (root / "transcripts.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(("path", "kind", "content", "language", "text", "status", "review_recommended", "human_verified"))
        for c in plan["clips"]:
            t = c["transcript"]
            writer.writerow((c["path"], c["kind"], c["content"], t.get("language", ""), t["text"], t["status"], t.get("review_recommended", False), False))
    write_player(root, plan["clips"])
    print(json.dumps(summary, indent=2))
    if errors:
        raise ValueError(f"{errors} WAV entries have transcription errors; inspect and rerun affected shards")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "merge"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--plan", type=Path, default=Path("transcription-plan.json"))
    parser.add_argument("--output", type=Path, default=Path("transcripts-part-0.json"))
    parser.add_argument("--parts", type=Path, default=Path("."))
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--model", default="small")
    args = parser.parse_args()
    if not 0 <= args.shard < args.shards:
        parser.error("shard index must be within shard count")
    if args.command == "plan":
        plan = make_plan(args.root)
        args.plan.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"clips": len(plan["clips"]), "unique_speech": len(plan["tasks"]), "content": plan["counts"]}))
    elif args.command == "run":
        run_shard(args.root, args.plan, args.output, args.shard, args.shards, args.model)
    else:
        merge(args.root, args.plan, args.parts)


if __name__ == "__main__":
    main()
