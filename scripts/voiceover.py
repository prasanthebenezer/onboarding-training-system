#!/usr/bin/env python3
"""Voiceover helper: per-scene narration text out, timed audio track in.

TTS tools read everything they are given, including time cues, and can't
place speech at a timestamp. So:

1. export   writes the narration only (no cues), one file per scene plus one
            combined file, for pasting into the voice tool.
2. (you)    generate ONE audio clip per scene in the voice tool and name them
            scene01.mp3, scene02.mp3, ... (any audio format, in scene order).
3. assemble places each clip at its scene's start time from script.<lang>.md,
            checks each clip fits before the next scene starts, and writes a
            full-length audio track, or the finished MP4 if you pass --video.

Usage:
  python3 scripts/voiceover.py export   content/modules/pt-01-raw-materials --lang en
  python3 scripts/voiceover.py assemble content/modules/pt-01-raw-materials --lang en \
          --clips ~/voice/pt01-en --video visuals_en.mp4 --out en.mp4

Needs ffmpeg and ffprobe on PATH for `assemble`.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

SCENE_RE = re.compile(r"^## Scene (\d+):\s*(.*?)\s*\((\d+):(\d{2})\)\s*$")
LENGTH_RE = re.compile(r"Target length:\s*(?:about\s*)?(\d+):(\d{2})")
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
MARGIN = 0.3  # seconds of air wanted before the next scene starts


def parse_script(path: Path):
    scenes, length = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if m := LENGTH_RE.search(line):
            length = int(m[1]) * 60 + int(m[2])
        if m := SCENE_RE.match(line):
            scenes.append({"no": int(m[1]), "name": m[2], "start": int(m[3]) * 60 + int(m[4]), "text": ""})
        elif line.startswith("NARRATION:") and scenes:
            scenes[-1]["text"] = line[len("NARRATION:"):].strip()
    if not scenes:
        sys.exit(f"No '## Scene N: Name (m:ss)' headings found in {path}")
    if length is None:
        sys.exit(f"No 'Target length: m:ss' found in {path}")
    for i, s in enumerate(scenes):
        s["end"] = scenes[i + 1]["start"] if i + 1 < len(scenes) else length
        if s["end"] <= s["start"]:
            sys.exit(f"Scene {s['no']} has no time: starts {s['start']}s, next starts {s['end']}s")
        if not s["text"]:
            sys.exit(f"Scene {s['no']} has no NARRATION line")
    return scenes, length


def export(module: Path, lang: str):
    scenes, length = parse_script(module / f"script.{lang}.md")
    out = module / "voiceover" / lang
    out.mkdir(parents=True, exist_ok=True)
    for s in scenes:
        (out / f"scene{s['no']:02d}.txt").write_text(s["text"] + "\n", encoding="utf-8")
    (out / "all-scenes.txt").write_text("\n\n".join(s["text"] for s in scenes) + "\n", encoding="utf-8")
    print(f"Wrote {len(scenes)} scene files + all-scenes.txt to {out}")
    print("Make one clip per scene, named to match: " + ", ".join(f"scene{s['no']:02d}" for s in scenes))
    for s in scenes:
        words = len(s["text"].split())
        print(f"  scene{s['no']:02d}  {fmt(s['start'])}-{fmt(s['end'])}  slot {s['end'] - s['start']:>3}s  {words:>3} words  {s['name']}")


def fmt(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:04.1f}" if sec % 1 else f"{int(sec // 60)}:{int(sec % 60):02d}"


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(f"ffprobe could not read {path}: {r.stderr.strip()}")
    return float(r.stdout.strip())


def assemble(module: Path, lang: str, clips_dir: Path, out: Path, video: Path | None, force: bool):
    scenes, length = parse_script(module / f"script.{lang}.md")
    clips = sorted(p for p in clips_dir.iterdir() if p.suffix.lower() in AUDIO_EXT)
    if len(clips) != len(scenes):
        sys.exit(f"Found {len(clips)} audio clips in {clips_dir}, script has {len(scenes)} scenes. "
                 "Make exactly one clip per scene, named scene01, scene02, ... so they sort in order.")
    problems = []
    print(f"{'clip':<16}{'starts':>8}{'length':>8}{'slot':>7}  fit")
    for s, c in zip(scenes, clips):
        d = duration(c)
        slot = s["end"] - s["start"]
        ok = d <= slot - MARGIN
        print(f"{c.name:<16}{fmt(s['start']):>8}{d:>7.1f}s{slot:>6}s  {'ok' if ok else 'TOO LONG'}")
        if not ok:
            problems.append(f"{c.name} is {d:.1f}s but scene {s['no']} ({s['name']}) has {slot}s: "
                            "shorten the text or speed up the voice for this clip")
    if problems and not force:
        sys.exit("\n".join(["", *problems, "Nothing written. Use --force to build anyway (speech will overlap)."]))

    cmd = ["ffmpeg", "-y", "-v", "error"]
    if video:
        cmd += ["-i", str(video)]
    for c in clips:
        cmd += ["-i", str(c)]
    first = 1 if video else 0
    parts = [f"[{first + i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(s['start'] * 1000)}:all=1[a{i}]"
             for i, s in enumerate(scenes)]
    mix = "".join(f"[a{i}]" for i in range(len(scenes)))
    parts.append(f"{mix}amix=inputs={len(scenes)}:normalize=0:duration=longest,apad,atrim=0:{length}[voice]")
    cmd += ["-filter_complex", ";".join(parts)]
    if video:
        cmd += ["-map", "0:v", "-map", "[voice]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-t", str(length), "-movflags", "+faststart", str(out)]
    else:
        cmd += ["-map", "[voice]", "-c:a", "aac" if out.suffix.lower() in (".m4a", ".aac") else "pcm_s16le"
                if out.suffix.lower() == ".wav" else "libmp3lame", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{r.stderr}")
    total = duration(out)
    print(f"\nWrote {out} ({total:.1f}s).")
    if total > 180:
        print("WARNING: longer than the 3-minute limit.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write narration-only text per scene")
    e.add_argument("module", type=Path)
    e.add_argument("--lang", default="en")
    a = sub.add_parser("assemble", help="place per-scene clips at their scene times")
    a.add_argument("module", type=Path)
    a.add_argument("--lang", default="en")
    a.add_argument("--clips", type=Path, required=True, help="folder with scene01.*, scene02.*, ...")
    a.add_argument("--out", type=Path, required=True, help=".mp4 with --video, else .m4a / .mp3 / .wav")
    a.add_argument("--video", type=Path, help="silent MP4 exported from Motion: writes the finished video")
    a.add_argument("--force", action="store_true", help="build even if a clip overruns its scene")
    args = ap.parse_args()
    if args.cmd == "export":
        export(args.module, args.lang)
    else:
        assemble(args.module, args.lang, args.clips, args.out, args.video, args.force)


if __name__ == "__main__":
    main()
