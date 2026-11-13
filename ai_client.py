"""One AI client for the scanner. Works with any chat API that uses the OpenAI request format.

Settings (GitHub secrets, or environment variables):
  AI_PROVIDER      nvidia | mistral | custom        (default: mistral if only MISTRAL_API_KEY is set, else nvidia)
  AI_API_KEY       the provider's key               (or NVIDIA_API_KEY / MISTRAL_API_KEY)
  AI_BASE_URL      needed for custom, e.g. https://api.openai.com/v1
  AI_MODEL         the model name exactly as the provider lists it
NVIDIA_MODEL still works for NVIDIA. Nothing is called unless a key and a model are set.
"""
import os

PRESETS = {
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", "mistralai/mistral-medium-3.5-128b"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-large-latest"),
}


def _env(k: str) -> str:
    return (os.environ.get(k) or "").strip()


def provider() -> str:
    set_ = _env("AI_PROVIDER").lower()
    if set_:
        return set_
    return "mistral" if _env("MISTRAL_API_KEY") and not _env("NVIDIA_API_KEY") else "nvidia"


def endpoint():
    """Returns (url, key, model), or (None, None, None) when AI is not set up."""
    p = provider()
    preset = PRESETS.get(p)
    base = _env("AI_BASE_URL") or (preset[0] if preset else "")
    key = _env("AI_API_KEY") or (_env(preset[1]) if preset else "")
    model = _env("AI_MODEL") or (_env("NVIDIA_MODEL") if p == "nvidia" else "") or (preset[2] if preset else "")
    if not base or not key or not model:
        return None, None, None
    return f"{base.rstrip('/')}/chat/completions", key, model
