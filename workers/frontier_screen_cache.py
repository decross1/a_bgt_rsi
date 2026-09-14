"""Opt-in, bounded cache for exact duplicate frontier veto screens.

Only a completed, fully parseable overall veto can be reused. Passes,
inconclusive reviews, provider errors, malformed records, and cache failures
all take the existing fresh-screen path. The binding covers the complete
candidate evidence, rendered prompts/review logic, role routing, and requested
provider/model configuration.

The subscription transports expose mutable model aliases, not independently
verifiable server revision IDs. Reuse therefore also requires an operator-
declared cache epoch for every routed provider. The epoch is an explicit risk
boundary, not proof of model immutability; rotate or unset it whenever a
provider alias may have changed.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from workers import frontier_review


CACHE_SCHEMA_VERSION = 1
LOGIC_VERSION = "frontier-screen-cache-2026-09-14.v1"
DEFAULT_TTL_S = 24 * 60 * 60
MAX_TTL_S = 7 * 24 * 60 * 60
MAX_RECORD_BYTES = 64 * 1024
MAX_CACHE_ENTRIES = 1024
_IMPLEMENTATION_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _implementation_identity(frontier_cli_module: Any, vendor: str) -> dict:
    """Bind the resolved executable and package revision without spawning it."""
    try:
        raw = frontier_cli_module._resolve_binary(vendor)
        found = raw if os.path.isabs(raw) else shutil.which(raw)
        if not found:
            raise OSError("executable not found")
        path = Path(found).resolve(strict=True)
        stat = path.stat()
        key = (str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if key in _IMPLEMENTATION_CACHE:
            return dict(_IMPLEMENTATION_CACHE[key])
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        package_version = None
        for parent in path.parents:
            package = parent / "package.json"
            if package.is_file() and package.stat().st_size <= 64 * 1024:
                try:
                    value = json.loads(package.read_text(encoding="utf-8")).get(
                        "version"
                    )
                    if isinstance(value, str) and value.strip():
                        package_version = value.strip()
                        break
                except (OSError, ValueError, TypeError):
                    pass
        identity = {
            "resolved_path": str(path),
            "sha256": digest.hexdigest(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "package_version": package_version,
        }
        _IMPLEMENTATION_CACHE[key] = identity
        return dict(identity)
    except (AttributeError, OSError, TypeError, ValueError):
        return {
            "resolved_path": None, "sha256": None, "size": None,
            "mtime_ns": None, "package_version": None,
        }


def requested_provider_config(frontier_cli_module: Any | None = None) -> dict:
    """Return the non-secret effective configuration requested for review.

    The current transport does not report immutable server-side model
    revisions. Caching therefore remains bypassed unless an operator supplies
    a reviewed cache epoch for every routed provider via
    ``FRONTIER_<VENDOR>_CACHE_EPOCH``. This declaration does not independently
    verify that a vendor's mutable alias stayed fixed.
    """
    if frontier_cli_module is None:
        from agent_wrapper import frontier_cli as frontier_cli_module

    role_vendors = {
        role: frontier_review.role_vendor(role) for role in frontier_review.ROLES
    }
    vendors = set(role_vendors.values())
    # A veto/pass disagreement may cross-run on the other configured vendor.
    vendors.update(frontier_review.ROLE_VENDOR_DEFAULTS.values())
    providers: dict[str, dict[str, Any]] = {}
    epochs_declared = True
    for vendor in sorted(vendors):
        epoch = os.environ.get(f"FRONTIER_{vendor.upper()}_CACHE_EPOCH")
        if vendor == "codex":
            provider = {
                "model": frontier_cli_module.CODEX_MODEL,
                "reasoning_effort": frontier_cli_module.CODEX_REASONING_EFFORT,
                "binary_override": os.environ.get("FRONTIER_CODEX_BIN"),
            }
        elif vendor == "claude":
            # frontier_cli supplies no --model flag; bind that exact request.
            provider = {
                "model": "cli-default",
                "reasoning_effort": None,
                "binary_override": os.environ.get("FRONTIER_CLAUDE_BIN"),
            }
        else:
            provider = {
                "model": "unsupported-provider",
                "reasoning_effort": None,
                "binary_override": os.environ.get(
                    f"FRONTIER_{vendor.upper()}_BIN"
                ),
            }
        epoch = epoch.strip() if isinstance(epoch, str) else None
        if not epoch:
            epochs_declared = False
            epoch = None
        provider["declared_cache_epoch_sha256"] = (
            hashlib.sha256(epoch.encode("utf-8")).hexdigest() if epoch else None
        )
        provider["implementation"] = (
            _implementation_identity(frontier_cli_module, vendor)
            if epoch is not None else None
        )
        if epoch is not None and not provider["implementation"].get("sha256"):
            epochs_declared = False
        providers[vendor] = provider
    try:
        transport_source_sha256 = hashlib.sha256(
            inspect.getsource(frontier_cli_module).encode("utf-8")
        ).hexdigest()
    except (OSError, TypeError):
        transport_source_sha256 = None
        epochs_declared = False
    return {
        "role_vendors": role_vendors,
        "providers": providers,
        "review_timeout_s": os.environ.get(
            "FRONTIER_REVIEW_TIMEOUT_S", str(frontier_review.DEFAULT_TIMEOUT_S)
        ),
        "transport_source_sha256": transport_source_sha256,
        "cache_epochs_declared": epochs_declared,
    }


def _config_has_declared_epochs(requested_config: Any) -> bool:
    if not isinstance(requested_config, dict):
        return False
    if requested_config.get("cache_epochs_declared") is not True:
        return False
    transport_digest = requested_config.get("transport_source_sha256")
    if not isinstance(transport_digest, str) or len(transport_digest) != 64:
        return False
    providers = requested_config.get("providers")
    if not isinstance(providers, dict) or not providers:
        return False
    role_vendors = requested_config.get("role_vendors")
    if (
        not isinstance(role_vendors, dict)
        or set(role_vendors) != set(frontier_review.ROLES)
        or any(vendor not in providers for vendor in role_vendors.values())
    ):
        return False
    for provider in providers.values():
        if not isinstance(provider, dict):
            return False
        epoch_digest = provider.get("declared_cache_epoch_sha256")
        implementation = provider.get("implementation")
        if not isinstance(epoch_digest, str) or len(epoch_digest) != 64:
            return False
        if (
            not isinstance(implementation, dict)
            or not isinstance(implementation.get("sha256"), str)
            or len(implementation["sha256"]) != 64
        ):
            return False
    return True


def _binding(
    candidate: dict, requested_config: dict, ttl_s: int
) -> tuple[str, dict]:
    prompts = {
        role: frontier_review.build_prompt(role, candidate)
        for role in frontier_review.ROLES
    }
    try:
        review_source = inspect.getsource(frontier_review)
    except (OSError, TypeError) as exc:
        raise ValueError("frontier review source unavailable") from exc
    binding = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "candidate_sha256": _sha(candidate),
        "prompt_sha256": {role: _sha(prompt) for role, prompt in prompts.items()},
        "review_logic_sha256": hashlib.sha256(
            (LOGIC_VERSION + "\n" + review_source).encode("utf-8")
        ).hexdigest(),
        "requested_config": requested_config,
        "cache_ttl_s": ttl_s,
    }
    return _sha(binding), binding


def _complete_veto(screen: Any, requested_config: dict) -> bool:
    if not isinstance(screen, dict) or screen.get("verdict") != "veto":
        return False
    if screen.get("escalated") is not False:
        return False
    methods = screen.get("methods")
    novelty = screen.get("novelty")
    if not all(isinstance(review, dict) for review in (methods, novelty)):
        return False
    role_vendors = requested_config.get("role_vendors")
    if not isinstance(role_vendors, dict):
        return False
    labelled = (
        (methods, "methods_reviewer"),
        (novelty, "novelty_reviewer"),
    )
    for review, expected_role in labelled:
        if review.get("role") != expected_role:
            return False
        if review.get("vendor") != role_vendors.get(expected_role):
            return False
        if review.get("parse_ok") is not True:
            return False
        if review.get("verdict") not in ("veto", "pass"):
            return False
        if (
            not isinstance(review.get("reasoning"), str)
            or not review["reasoning"].strip()
        ):
            return False
        cross = review.get("cross_run")
        if cross is not None and (
            not isinstance(cross, dict)
            or cross.get("parse_ok") is not True
            or cross.get("verdict") != "veto"
            or not isinstance(cross.get("reasoning"), str)
            or not cross["reasoning"].strip()
            or cross.get("error") not in (None, "")
            or cross.get("exit_code") not in (None, 0)
        ):
            return False
        if review.get("error") not in (None, ""):
            return False
        if review.get("exit_code") not in (None, 0):
            return False
    # A split base verdict needs the confirming cross-vendor veto.
    base_verdicts = {methods["verdict"], novelty["verdict"]}
    if base_verdicts == {"veto"}:
        return True
    if base_verdicts == {"veto", "pass"}:
        vetoer = methods if methods["verdict"] == "veto" else novelty
        other = novelty if vetoer is methods else methods
        cross = vetoer.get("cross_run")
        return (
            isinstance(cross, dict)
            and cross.get("role") == vetoer.get("role")
            and cross.get("vendor") == other.get("vendor")
            and cross.get("vendor") != vetoer.get("vendor")
        )
    return False


def _load(
    cache_dir: Path, key: str, binding: dict, now_s: float
) -> tuple[dict | None, str]:
    path = cache_dir / f"{key}.json"
    try:
        if path.is_symlink() or not path.is_file():
            return None, "miss"
        if path.stat().st_size > MAX_RECORD_BYTES:
            return None, "record_too_large"
        record = json.loads(path.read_text(encoding="utf-8"))
        created = float(record["created_at_s"])
        expires = float(record["expires_at_s"])
        expected_ttl = float(binding["cache_ttl_s"])
        if (
            record.get("schema_version") != CACHE_SCHEMA_VERSION
            or record.get("key") != key
            or record.get("binding") != binding
            or not math.isfinite(created)
            or not math.isfinite(expires)
            or created > now_s
            or expires <= created
            or expires - created > MAX_TTL_S
            or not math.isclose(
                expires - created, expected_ttl, rel_tol=0.0, abs_tol=1e-6
            )
        ):
            return None, "binding_mismatch"
        if now_s >= expires:
            try:
                path.unlink()
            except OSError:
                pass
            return None, "expired"
        screen = record.get("screen")
        if not _complete_veto(screen, binding["requested_config"]):
            return None, "invalid_screen"
        # JSON round-trip produces an independent result for annotation.
        return json.loads(json.dumps(screen)), "hit"
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None, "malformed_record"


def _prune(cache_dir: Path) -> None:
    try:
        records = [p for p in cache_dir.glob("*.json") if not p.is_symlink()]
        if len(records) <= MAX_CACHE_ENTRIES:
            return
        records.sort(key=lambda p: p.stat().st_mtime_ns)
        for path in records[:len(records) - MAX_CACHE_ENTRIES]:
            try:
                path.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _store(
    cache_dir: Path,
    key: str,
    binding: dict,
    screen: dict,
    now_s: float,
    ttl_s: int,
) -> tuple[bool, str]:
    if not _complete_veto(screen, binding["requested_config"]):
        return False, "result_not_complete_veto"
    record = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "key": key,
        "binding": binding,
        "created_at_s": now_s,
        "expires_at_s": now_s + ttl_s,
        "screen": screen,
    }
    payload = _canonical(record)
    if len(payload) > MAX_RECORD_BYTES:
        return False, "record_too_large"
    tmp_path: Path | None = None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        fd, raw_tmp = tempfile.mkstemp(prefix=f".{key}.", suffix=".tmp",
                                       dir=cache_dir)
        tmp_path = Path(raw_tmp)
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, cache_dir / f"{key}.json")
        tmp_path = None
        _prune(cache_dir)
        return True, "stored"
    except OSError:
        return False, "write_error"
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def screen_candidate_cached(
    candidate: dict,
    invoke_fn: Callable[..., dict],
    *,
    cache_dir: str | os.PathLike,
    requested_config: dict,
    ttl_s: int = DEFAULT_TTL_S,
    now_s: float | None = None,
) -> dict[str, Any]:
    """Reuse an exact, unexpired complete veto; otherwise screen freshly.

    Cache configuration/read/write failures never affect the scientific
    verdict. They are reported under ``result["cache"]`` and the normal fresh
    screen runs.
    """
    try:
        now_s = time.time() if now_s is None else float(now_s)
    except (TypeError, ValueError):
        now_s = float("nan")
    try:
        ttl_s = int(ttl_s)
    except (TypeError, ValueError):
        ttl_s = 0
    if not math.isfinite(now_s) or ttl_s <= 0 or ttl_s > MAX_TTL_S:
        screen = frontier_review.screen_candidate(candidate, invoke_fn)
        screen["cache"] = {
            "enabled": True, "hit": False, "stored": False,
            "reason": "invalid_time" if not math.isfinite(now_s)
            else "invalid_ttl",
        }
        return screen

    if not _config_has_declared_epochs(requested_config):
        screen = frontier_review.screen_candidate(candidate, invoke_fn)
        screen["cache"] = {
            "enabled": True, "hit": False, "stored": False,
            "reason": "undeclared_provider_cache_epoch",
        }
        return screen

    try:
        key, binding = _binding(candidate, requested_config, ttl_s)
    except (TypeError, ValueError):
        screen = frontier_review.screen_candidate(candidate, invoke_fn)
        screen["cache"] = {
            "enabled": True, "hit": False, "stored": False,
            "reason": "binding_error",
        }
        return screen

    try:
        root = Path(cache_dir)
    except TypeError:
        screen = frontier_review.screen_candidate(candidate, invoke_fn)
        screen["cache"] = {
            "enabled": True, "hit": False, "stored": False,
            "reason": "invalid_cache_dir",
        }
        return screen
    screen, reason = _load(root, key, binding, now_s)
    if screen is not None:
        screen["cache"] = {
            "enabled": True, "hit": True, "stored": False,
            "reason": "hit", "key": key, "ttl_s": ttl_s,
        }
        return screen

    screen = frontier_review.screen_candidate(candidate, invoke_fn)
    stored, store_reason = _store(
        root, key, binding, screen, now_s, ttl_s
    )
    screen["cache"] = {
        "enabled": True, "hit": False, "stored": stored,
        "reason": store_reason if reason == "miss" else reason,
        "key": key, "ttl_s": ttl_s,
    }
    if not stored and store_reason not in ("result_not_complete_veto",):
        screen["cache"]["write_reason"] = store_reason
    return screen
