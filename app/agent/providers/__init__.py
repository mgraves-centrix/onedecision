"""Model provider adapter.

The rest of the application never imports a model class directly. It asks for
`resolve_model()` and gets whatever the environment is configured for:

  scripted  - deterministic, offline, no credentials. Tests, CI, offline demo.
  bedrock   - Amazon Bedrock (Strands `BedrockModel`).
  anthropic - Anthropic API (Strands `AnthropicModel`).

Every provider drives the *same* Strands `Agent`, the same tools, and the same
typed structured outputs. Swapping providers changes who does the reasoning, not
what the system is allowed to do — the guardrails, the policy schema, and the
activation gate sit downstream of all of them.
"""

from __future__ import annotations

from typing import Any

from strands.models.model import Model

from app.config import Settings, settings as default_settings


class ModelProviderUnavailable(RuntimeError):
    """Raised when the configured provider cannot be constructed."""


SUPPORTED_PROVIDERS = ("scripted", "bedrock", "anthropic")


def resolve_model(settings: Settings | None = None, **overrides: Any) -> Model:
    """Build the configured Strands model provider."""
    cfg = settings or default_settings
    provider = cfg.model_provider

    if provider == "scripted":
        from app.agent.providers.scripted import ScriptedModel

        return ScriptedModel(**overrides)

    if provider == "bedrock":
        try:
            from strands.models import BedrockModel
        except ImportError as exc:  # pragma: no cover - dependency is pinned
            raise ModelProviderUnavailable(f"BedrockModel unavailable: {exc}") from exc
        # No default temperature, for the same reason as the Anthropic provider
        # below: current Claude models reject it as deprecated.
        return BedrockModel(
            model_id=overrides.pop("model_id", cfg.bedrock_model_id),
            region_name=overrides.pop("region_name", cfg.aws_region),
            **overrides,
        )

    if provider == "anthropic":
        try:
            from strands.models.anthropic import AnthropicModel
        except ImportError as exc:
            raise ModelProviderUnavailable(
                "AnthropicModel requires the 'anthropic' extra: "
                "pip install 'strands-agents[anthropic]'"
            ) from exc
        # Strands requires max_tokens as a top-level config key; anything in
        # `params` is passed through to the request as extra fields. No default
        # temperature: current Claude models reject it as deprecated.
        return AnthropicModel(
            model_id=overrides.pop("model_id", cfg.anthropic_model_id),
            max_tokens=overrides.pop("max_tokens", 2048),
            params=overrides.pop("params", None),
            **overrides,
        )

    raise ModelProviderUnavailable(
        f"unknown provider '{provider}'; supported: {', '.join(SUPPORTED_PROVIDERS)}"
    )


def provider_label(settings: Settings | None = None) -> str:
    cfg = settings or default_settings
    match cfg.model_provider:
        case "scripted":
            return "scripted (deterministic, offline)"
        case "bedrock":
            return f"bedrock · {cfg.bedrock_model_id}"
        case "anthropic":
            return f"anthropic · {cfg.anthropic_model_id}"
        case other:
            return other
