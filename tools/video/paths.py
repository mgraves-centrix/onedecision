"""Where the video tools read their inputs and write what they generate.

Inputs (the narration, the captured AgentCore response) live next to the scripts
and are committed. Everything generated (voiceover audio, raw captures, the
timeline, the finished MP4) goes to var/video, which git ignores.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "var" / "video"
