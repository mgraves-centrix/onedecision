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

# A policy may never authorize more than this many missing components.
MAX_MISSING_COMPONENTS_CEILING = 1

# The out-of-the-box approval token. It is a placeholder, not a secret: the demo
# has to be usable by someone who just cloned the repository. While it is still
# in use the interface says so out loud, so nobody mistakes it for real
# authorization. Setting ONEDECISION_APPROVAL_TOKEN replaces it and silences the
# notice.
DEFAULT_APPROVAL_TOKEN = "replace-me-local-demo-token"


def load_dotenv(path: Path | None = None) -> list[str]:
    """Load `.env` into the process environment, if it exists.

    The README tells anyone running this to copy `.env.example` to `.env`, so
    something has to read it. Deliberately small and dependency-free:

    * a real environment variable always wins over the file, so a deployment
      cannot be silently overridden by a stray file on disk;
    * values are never logged, and the names loaded are returned rather than the
      values, so a caller that wants to report progress cannot leak a secret.

    `.env` is gitignored. Never commit one.
    """
    target = path or (REPO_ROOT / ".env")
    if not target.exists():
        return []

    loaded: list[str] = []
    for raw in target.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key or key in os.environ:
            continue  # the real environment wins
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value
        loaded.append(key)
    return loaded


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
    database_url: str
    db_path: Path
    db_pool_min_size: int
    db_pool_max_size: int
    db_connect_timeout_seconds: int
    confidence_threshold: float
    model_timeout_seconds: int
    approval_token: str
    otel_enabled: bool

    @property
    def is_offline_provider(self) -> bool:
        return self.model_provider == "scripted"

    @property
    def db_backend(self) -> str:
        return "postgres" if self.database_url else "sqlite"

    @property
    def uses_default_approval_token(self) -> bool:
        """True while the shipped placeholder token is still in use."""
        return self.approval_token == DEFAULT_APPROVAL_TOKEN


def resolve_database_url() -> str:
    """The PostgreSQL DSN, or empty to use the local SQLite demo backend.

    `ONEDECISION_DATABASE_URL` wins. `DATABASE_URL` is honored as the platform
    convention so a managed host that injects it needs no extra wiring. A secret
    is read from the environment and never written anywhere.
    """
    for name in ("ONEDECISION_DATABASE_URL", "DATABASE_URL"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def load_settings() -> Settings:
    db_path = Path(os.environ.get("ONEDECISION_DB_PATH", "var/onedecision.db"))
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    return Settings(
        model_provider=os.environ.get("ONEDECISION_MODEL_PROVIDER", "scripted").strip().lower(),
        bedrock_model_id=os.environ.get(
            "ONEDECISION_BEDROCK_MODEL_ID",
            # Bedrock IDs carry an "anthropic." prefix. Unverified against a live
            # endpoint (see docs/provenance.md); confirm against
            # `aws bedrock list-foundation-models` for the target account.
            "anthropic.claude-opus-5",
        ),
        anthropic_model_id=os.environ.get(
            # Current model IDs carry no date suffix.
            "ONEDECISION_ANTHROPIC_MODEL_ID", "claude-opus-5"
        ),
        aws_region=os.environ.get("AWS_REGION", "us-west-2"),
        database_url=resolve_database_url(),
        db_path=db_path,
        db_pool_min_size=_env_int("ONEDECISION_DB_POOL_MIN", 1),
        db_pool_max_size=_env_int("ONEDECISION_DB_POOL_MAX", 10),
        db_connect_timeout_seconds=_env_int("ONEDECISION_DB_CONNECT_TIMEOUT", 10),
        confidence_threshold=_env_float("ONEDECISION_CONFIDENCE_THRESHOLD", 0.75),
        model_timeout_seconds=_env_int("ONEDECISION_MODEL_TIMEOUT_SECONDS", 60),
        approval_token=os.environ.get("ONEDECISION_APPROVAL_TOKEN", DEFAULT_APPROVAL_TOKEN),
        otel_enabled=os.environ.get("ONEDECISION_OTEL_ENABLED", "false").lower() == "true",
    )


load_dotenv()
settings = load_settings()


def get_settings() -> Settings:
    """The live settings object.

    Call this rather than importing `settings` directly anywhere that must see a
    reload — importing binds the value at import time, which is exactly the bug
    this avoids.
    """
    return settings


def reload_settings() -> Settings:
    """Re-read the environment. Used by tests and by the AgentCore entrypoint."""
    global settings
    settings = load_settings()
    return settings
