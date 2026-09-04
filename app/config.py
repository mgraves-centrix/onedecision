"""Runtime configuration.

Everything is read from the environment with safe local defaults so the demo
runs with no credentials and no cloud account.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Company + facility identifiers are fictional. See docs/scope.md.
COMPANY_NAME = "Northgate Optics"
FACILITY_ID = "NGO-WH-1"

# Hard ceiling the policy schema will never allow a proposal to exceed, no
# matter what a human approves or a model proposes. The demo policy lands at
# $25; this is the outer wall.
MAX_REPLACEMENT_COST_CEILING_USD = 50.0

# A policy may never authorise more than this many missing components.
MAX_MISSING_COMPONENTS_CEILING = 1


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Process-wide settings. Never contains a secret value at rest."""

    model_provider: str
    bedrock_model_id: str
    anthropic_model_id: str
    aws_region: str
    db_path: Path
    confidence_threshold: float
    model_timeout_seconds: int
    approval_token: str
    otel_enabled: bool

    @property
    def is_offline_provider(self) -> bool:
        return self.model_provider == "scripted"


def load_settings() -> Settings:
    db_path = Path(os.environ.get("ONEDECISION_DB_PATH", "var/onedecision.db"))
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    return Settings(
        model_provider=os.environ.get("ONEDECISION_MODEL_PROVIDER", "scripted").strip().lower(),
        bedrock_model_id=os.environ.get(
            "ONEDECISION_BEDROCK_MODEL_ID",
            "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        ),
        anthropic_model_id=os.environ.get(
            "ONEDECISION_ANTHROPIC_MODEL_ID", "claude-sonnet-4-5-20250929"
        ),
        aws_region=os.environ.get("AWS_REGION", "us-west-2"),
        db_path=db_path,
        confidence_threshold=_env_float("ONEDECISION_CONFIDENCE_THRESHOLD", 0.75),
        model_timeout_seconds=_env_int("ONEDECISION_MODEL_TIMEOUT_SECONDS", 60),
        approval_token=os.environ.get("ONEDECISION_APPROVAL_TOKEN", "replace-me-local-demo-token"),
        otel_enabled=os.environ.get("ONEDECISION_OTEL_ENABLED", "false").lower() == "true",
    )


settings = load_settings()


def reload_settings() -> Settings:
    """Re-read the environment. Used by tests and by the AgentCore entrypoint."""
    global settings
    settings = load_settings()
    return settings
