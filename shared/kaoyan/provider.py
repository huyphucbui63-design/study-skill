"""Configurable OpenAI-compatible vision provider with no stored secrets."""

from __future__ import annotations

import base64
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProviderError(RuntimeError):
    """A provider is unavailable or returned an unusable response."""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 90.0
    retries: int = 2
    image_batch_limit: int = 4
    high_resolution: bool = True

    @classmethod
    def from_environment(cls) -> "ProviderConfig":
        """Capture trusted provider settings once when the local service starts."""
        return cls(
            base_url=str(os.environ.get("KAOYAN_VISION_BASE_URL") or cls.base_url).rstrip("/"),
            model=str(os.environ.get("KAOYAN_VISION_MODEL") or cls.model),
            api_key_env=str(os.environ.get("KAOYAN_VISION_API_KEY_ENV") or cls.api_key_env),
            timeout_seconds=float(os.environ.get("KAOYAN_VISION_TIMEOUT", cls.timeout_seconds)),
            retries=int(os.environ.get("KAOYAN_VISION_RETRIES", cls.retries)),
            image_batch_limit=int(os.environ.get("KAOYAN_VISION_BATCH_LIMIT", cls.image_batch_limit)),
            high_resolution=_as_bool(os.environ.get("KAOYAN_VISION_HIGH_RES", cls.high_resolution)),
        ).validated()

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None = None) -> "ProviderConfig":
        """Build a configuration from a trusted, non-request mapping."""
        value = value or {}
        forbidden = {"api_key", "key", "token"}.intersection(value)
        if forbidden:
            raise ValueError("API keys must be supplied through an environment variable, never configuration.")
        return cls(
            base_url=str(value.get("base_url") or cls.base_url).rstrip("/"),
            model=str(value.get("model") or cls.model),
            api_key_env=str(value.get("api_key_env") or cls.api_key_env),
            timeout_seconds=float(value.get("timeout_seconds", cls.timeout_seconds)),
            retries=int(value.get("retries", cls.retries)),
            image_batch_limit=int(value.get("image_batch_limit", cls.image_batch_limit)),
            high_resolution=_as_bool(value.get("high_resolution", cls.high_resolution)),
        ).validated()

    def validated(self) -> "ProviderConfig":
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must use http:// or https://")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain credentials, a query, or a fragment")
        if not self.model.strip():
            raise ValueError("model is required")
        if not self.api_key_env or any(char in self.api_key_env for char in "= \t\r\n"):
            raise ValueError("api_key_env must be an environment variable name")
        if not 1 <= self.timeout_seconds <= 600:
            raise ValueError("timeout_seconds must be between 1 and 600")
        if not 0 <= self.retries <= 8:
            raise ValueError("retries must be between 0 and 8")
        if not 1 <= self.image_batch_limit <= 20:
            raise ValueError("image_batch_limit must be between 1 and 20")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "api_key_available": bool(os.environ.get(self.api_key_env)),
            "timeout_seconds": self.timeout_seconds,
            "retries": self.retries,
            "image_batch_limit": self.image_batch_limit,
            "high_resolution": self.high_resolution,
        }


def _data_url(path: Path) -> str:
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower())
    if not mime:
        raise ProviderError(f"Unsupported image format: {path.name}")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object without brittle field-level string extraction."""
    candidate = text.strip()
    if candidate.startswith("\x60\x60\x60"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
        if candidate.lower().startswith("json"):
            candidate = candidate[4:].lstrip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"The vision model did not return valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProviderError("The vision model response must be one JSON object.")
    return value


class VisionProvider:
    def __init__(self, config: ProviderConfig):
        self.config = config.validated()

    def analyze(self, images: list[Path], prompt: str, schema_name: str) -> dict[str, Any]:
        if not images:
            raise ProviderError("At least one image is required.")
        if len(images) > self.config.image_batch_limit:
            raise ProviderError(f"This provider allows at most {self.config.image_batch_limit} images per request.")
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise ProviderError(
                f"Vision API is not configured. Set environment variable {self.config.api_key_env}, "
                "or use manual transcription in the review screen."
            )
        detail = "high" if self.config.high_resolution else "auto"
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": _data_url(path), "detail": detail}} for path in images)
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": (
                    "You transcribe Chinese exam questions conservatively. Return only one JSON object. "
                    "Never guess obscured text, formulas, options, subquestions, or diagrams; mark uncertainty instead."
                )},
                {"role": "user", "content": content},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                message = body["choices"][0]["message"]["content"]
                result = parse_json_object(message)
                result.setdefault("recognition", {})
                result["recognition"].update({"provider": "openai-compatible", "model": self.config.model, "schema": schema_name})
                return result
            except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, KeyError, IndexError, json.JSONDecodeError, ProviderError) as exc:
                error = exc
                if attempt < self.config.retries:
                    time.sleep(min(0.5 * (2**attempt), 4.0))
        if isinstance(error, urllib.error.HTTPError):
            raise ProviderError(f"Vision API returned HTTP {error.code}; check base URL, model, and permissions.") from error
        raise ProviderError(f"Vision API request failed after {self.config.retries + 1} attempt(s): {error}") from error
