"""Where the video tools read their inputs and write what they generate.

Inputs (the narration, the captured AgentCore response) live next to the scripts
and are committed. Everything generated (voiceover audio, raw captures, the
timeline, the finished MP4) goes to a directory beside the repository, not inside
it: the AgentCore packager ships every file in the tree, gitignored or not, and a
few takes are hundreds of megabytes. Override with ONEDECISION_VIDEO_OUT.
"""

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = Path(os.environ.get("ONEDECISION_VIDEO_OUT") or REPO.parent / f"{REPO.name}-video")
