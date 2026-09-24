"""Validated project-owned model deployment selection.

The deployment document chooses a fixed local backend.  It is configuration,
not live-state evidence: runtime readiness remains the launcher's job.  This
module deliberately accepts neither request-provided URLs nor model aliases.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEPLOYMENT_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "model_deployment.json"
)

FLASH_BACKEND = "sglang-flash"
FLASH_MODEL = "nvidia/Qwen3.8-Flash-Next-NVFP4"
FLASH_BASE_URL = "http://127.0.0.1:30080/v1"
FLASH_ROLE_ALIASES = frozenset({"vllm-gemma", "vllm-qwen"})
# Counts covered by an immutable serving helper/profile: C1 (v8), C2 (v9),
# and C4 (v10/M24 or v11/v12 M20). The resident's selected() check binds the
# declared count and profile digest to one exact helper.
FLASH_MAX_RUNNING_REQUESTS_ALLOWED = frozenset({1, 2, 4})


@dataclass(frozen=True)
class ModelDeployment:
    backend: str
    model: str
    base_url: str
    context_length: int
    max_running_requests: int
    model_revision: str
    image_id: str
    profile_sha256: str
    host_reserve_gib: int
    selected_at: str
    config_sha256: str

    @property
    def model_version(self) -> str:
        """Content-bound model/runtime provenance for calls.jsonl."""

        return (
            f"{self.model}@{self.model_revision};"
            f"image={self.image_id};profile={self.profile_sha256}"
        )

    @property
    def host_metadata(self) -> dict[str, Any]:
        return {
            "backend": "sglang",
            "sglang_base_url": self.base_url,
            "deployment_topology": "single_flash",
            "deployment_config_sha256": self.config_sha256,
            "model_revision": self.model_revision,
            "image_id": self.image_id,
            "profile_sha256": self.profile_sha256,
            "context_length": self.context_length,
            "max_running_requests": self.max_running_requests,
            "host_reserve_gib": self.host_reserve_gib,
            "selected_at": self.selected_at,
        }


def _require_exact(value: Mapping[str, Any], key: str, expected: Any) -> None:
    if value.get(key) != expected:
        raise ValueError(
            f"model deployment {key!r} must be {expected!r}; "
            f"got {value.get(key)!r}"
        )


def _max_running_requests(value: Mapping[str, Any]) -> int:
    item = value.get("max_running_requests")
    if type(item) is not int or item not in FLASH_MAX_RUNNING_REQUESTS_ALLOWED:
        raise ValueError(
            "model deployment 'max_running_requests' must be one of "
            f"{sorted(FLASH_MAX_RUNNING_REQUESTS_ALLOWED)!r}; got {item!r}"
        )
    return item


def _required_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"model deployment {key!r} must be a nonempty string")
    return item


def _hex(value: Mapping[str, Any], key: str, length: int) -> str:
    item = _required_text(value, key)
    if len(item) != length or any(c not in "0123456789abcdef" for c in item):
        raise ValueError(
            f"model deployment {key!r} must be {length} lowercase hex chars"
        )
    return item


def load_model_deployment(
    path: Path | str = DEPLOYMENT_PATH,
    *,
    required: bool = True,
) -> ModelDeployment | None:
    """Load and strictly validate the immutable deployment selection.

    ``required=False`` is the compatibility seam for source trees that do not
    yet carry a deployment document.  A present but malformed document always
    fails closed.
    """

    deployment_path = Path(path)
    try:
        info = deployment_path.lstat()
    except FileNotFoundError:
        if required:
            raise RuntimeError(
                f"model deployment is missing: {deployment_path}"
            ) from None
        return None
    if deployment_path.is_symlink() or not deployment_path.is_file():
        raise ValueError("model deployment must be a regular non-symlink file")
    if info.st_size > 64 * 1024:
        raise ValueError("model deployment exceeds 64 KiB")
    raw_bytes = deployment_path.read_bytes()
    try:
        value = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("model deployment is not valid JSON") from exc
    if not isinstance(value, dict):
        raise TypeError("model deployment must be a JSON object")

    allowed = {
        "schema_version",
        "topology",
        "backend",
        "model",
        "base_url",
        "context_length",
        "max_running_requests",
        "production_authorized",
        "selected_at",
        "model_revision",
        "image_id",
        "profile_sha256",
        "host_reserve_gib",
        "automated_benchmarks_enabled",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown model deployment fields: {unknown}")

    _require_exact(value, "schema_version", 1)
    _require_exact(value, "topology", "single_flash")
    _require_exact(value, "backend", FLASH_BACKEND)
    _require_exact(value, "model", FLASH_MODEL)
    _require_exact(value, "base_url", FLASH_BASE_URL)
    _require_exact(value, "context_length", 262144)
    _require_exact(value, "production_authorized", True)
    _require_exact(value, "host_reserve_gib", 10)
    _require_exact(value, "automated_benchmarks_enabled", False)
    max_running_requests = _max_running_requests(value)
    selected_at = _required_text(value, "selected_at")
    model_revision = _hex(value, "model_revision", 40)
    profile_sha256 = _hex(value, "profile_sha256", 64)
    image_id = _required_text(value, "image_id")
    prefix = "sha256:"
    digest = image_id.removeprefix(prefix)
    if (not image_id.startswith(prefix) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("model deployment image_id must be a sha256 digest")

    return ModelDeployment(
        backend=FLASH_BACKEND,
        model=FLASH_MODEL,
        base_url=FLASH_BASE_URL,
        context_length=262144,
        max_running_requests=max_running_requests,
        model_revision=model_revision,
        image_id=image_id,
        profile_sha256=profile_sha256,
        host_reserve_gib=10,
        selected_at=selected_at,
        config_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


__all__ = [
    "DEPLOYMENT_PATH",
    "FLASH_BACKEND",
    "FLASH_BASE_URL",
    "FLASH_MAX_RUNNING_REQUESTS_ALLOWED",
    "FLASH_MODEL",
    "FLASH_ROLE_ALIASES",
    "ModelDeployment",
    "load_model_deployment",
]
