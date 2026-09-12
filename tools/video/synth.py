"""Synthesize the draft voiceover with Amazon Polly, one clip per demo beat.

Usage: python tools/video/synth.py [voice] [engine]
Reads narration.json. Writes var/video/audio/<beat>.wav (48 kHz stereo, with a
short trailing pause) and var/video/durations.json, which record_live.py uses to
pace the recording. Uses the AWS_PROFILE profile (default: onedecision).

A beat whose line has not changed keeps the clip it already has, so fixing one
line does not re-time every other beat and invalidate a take. Pass --all to
resynthesize everything, which you want after changing the voice or engine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from paths import HERE, OUT

AUDIO = OUT / "audio"
PAD_SECONDS = 0.6
PROFILE = os.environ.get("AWS_PROFILE", "onedecision")
REGION = os.environ.get("AWS_REGION", "us-west-2")

args = [a for a in sys.argv[1:] if a != "--all"]
force = "--all" in sys.argv
voice = args[0] if args else "Ruth"
engine = args[1] if len(args) > 1 else "generative"


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def main() -> None:
    AUDIO.mkdir(parents=True, exist_ok=True)
    beats = json.loads((HERE / "narration.json").read_text())
    durations: dict[str, float] = {}
    for beat in beats:
        mp3 = AUDIO / f"{beat['id']}.mp3"
        wav = AUDIO / f"{beat['id']}.wav"
        said = AUDIO / f"{beat['id']}.txt"
        spoken = said.read_text() if said.exists() else None
        if not force and wav.exists() and spoken == beat["text"]:
            seconds = float(run(
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(wav),
            ).strip())
            durations[beat["id"]] = round(seconds, 3)
            print(f"{beat['id']:<10} {seconds:6.2f} s  (unchanged)")
            continue
        run(
            "aws", "polly", "synthesize-speech",
            "--profile", PROFILE, "--region", REGION,
            "--engine", engine, "--voice-id", voice,
            "--output-format", "mp3", "--sample-rate", "24000",
            "--text", beat["text"], str(mp3),
        )
        run(
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
            "-af", f"apad=pad_dur={PAD_SECONDS}", "-ar", "48000", "-ac", "2", str(wav),
        )
        seconds = float(run(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(wav),
        ).strip())
        said.write_text(beat["text"])
        durations[beat["id"]] = round(seconds, 3)
        print(f"{beat['id']:<10} {seconds:6.2f} s")
    (OUT / "durations.json").write_text(json.dumps(durations, indent=2) + "\n")
    print(f"total      {sum(durations.values()):6.1f} s  ({voice}, {engine})")


if __name__ == "__main__":
    main()
