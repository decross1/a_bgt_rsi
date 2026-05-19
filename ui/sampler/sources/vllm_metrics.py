"""vLLM telemetry by scraping its Prometheus /metrics endpoint.

See ui_plan.md sections 4.1, 5.1, 7. Metric names drift between vLLM
releases, so each value is looked up against a list of candidate names.
Counter-derived values (decode tok/s, MTP token deltas) are computed
across sample intervals and return None while priming or just after a
counter reset (vLLM restart -> counters drop to zero).
"""
import time

import requests

# Candidate metric names, most-preferred first. Names drift between vLLM
# releases (ui_plan.md section 7) -- core gauges verified against v0.20.0.
_RUNNING = ["vllm:num_requests_running"]
_WAITING = ["vllm:num_requests_waiting"]
# KV-cache usage gauge: renamed kv_cache_usage_perc in newer vLLM.
_CACHE = ["vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"]
# Prefix-cache hit rate: a direct gauge in old vLLM; query/hit counters in new.
_PREFIX_HIT_GAUGE = ["vllm:gpu_prefix_cache_hit_rate"]
_PREFIX_QUERIES = ["vllm:prefix_cache_queries_total"]
_PREFIX_HITS = ["vllm:prefix_cache_hits_total"]
_GEN_TOKENS = ["vllm:generation_tokens_total"]
# Speculative-decoding / MTP counters. As of D-022 the apparatus runs MTP on
# vLLM v0.21.0 (--speculative-config method=mtp), so these are expected to be
# present. The v1 engine exports per-counter totals (no acceptance-rate
# gauge) -- when the gauge is absent, read() derives the rate from the
# accepted/draft deltas. The candidate lists cover the v1 counter names
# (Prometheus appends _total) and their unsuffixed forms; the exact v0.21.0
# names still want a live-server check (see ui/notes/ui-build.md). The mtp_*
# fields stay null if a build exports none of them.
_SPEC_ACCEPT_RATE = ["vllm:spec_decode_draft_acceptance_rate"]
_SPEC_DRAFT = ["vllm:spec_decode_num_draft_tokens_total",
               "vllm:spec_decode_num_draft_tokens"]
_SPEC_ACCEPTED = ["vllm:spec_decode_num_accepted_tokens_total",
                  "vllm:spec_decode_num_accepted_tokens"]


def parse_prometheus(text):
    """Parse Prometheus text format -> {metric_name: float}.

    Labels are stripped; the first occurrence of a name wins.
    """
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            metric, value = line.rsplit(" ", 1)
        except ValueError:
            continue
        name = metric.split("{", 1)[0].strip()
        if name in out:
            continue
        try:
            out[name] = float(value)
        except ValueError:
            continue
    return out


def _first(metrics, names):
    for name in names:
        if name in metrics:
            return metrics[name]
    return None


class VllmMetricsReader:
    """Stateful reader: holds previous counter values for rate computation."""

    def __init__(self, url="http://localhost:8000/metrics", timeout=2.0):
        self.url = url
        self.timeout = timeout
        self._rate_prev = {}   # key -> (monotonic_ts, value)
        self._delta_prev = {}  # key -> value

    def _rate(self, key, value, now):
        """Per-second rate of a counter. None while priming or after a reset."""
        if value is None:
            return None
        prev = self._rate_prev.get(key)
        self._rate_prev[key] = (now, value)
        if prev is None:
            return None
        prev_ts, prev_val = prev
        if value < prev_val:          # counter reset (vLLM restart)
            return None
        dt = now - prev_ts
        if dt <= 0:
            return None
        return (value - prev_val) / dt

    def _delta(self, key, value):
        """Counter increment since last read. None while priming or after a reset."""
        if value is None:
            self._delta_prev.pop(key, None)
            return None
        prev = self._delta_prev.get(key)
        self._delta_prev[key] = value
        if prev is None or value < prev:
            return None
        return value - prev

    def read(self):
        """Return (vllm_dict, None) or (None, error_str)."""
        try:
            resp = requests.get(self.url, timeout=self.timeout)
        except requests.RequestException as exc:
            return None, f"vllm /metrics unreachable: {exc}"
        if resp.status_code != 200:
            return None, f"vllm /metrics HTTP {resp.status_code}"

        metrics = parse_prometheus(resp.text)
        now = time.monotonic()

        running = _first(metrics, _RUNNING)
        waiting = _first(metrics, _WAITING)
        cache = _first(metrics, _CACHE)
        missing = [label for label, val in
                   (("running", running), ("waiting", waiting), ("cache", cache))
                   if val is None]
        if missing:
            return None, f"vllm /metrics missing core gauges: {missing}"

        tps = self._rate("gen_tokens", _first(metrics, _GEN_TOKENS), now)

        # Prefix-cache hit rate: use the direct gauge if present, else
        # compute it from the hit/query counter deltas over the interval.
        prefix_hit = _first(metrics, _PREFIX_HIT_GAUGE)
        if prefix_hit is None:
            queries = self._delta("prefix_queries", _first(metrics, _PREFIX_QUERIES))
            hits = self._delta("prefix_hits", _first(metrics, _PREFIX_HITS))
            if queries is not None and queries > 0 and hits is not None:
                prefix_hit = hits / queries

        draft_delta = self._delta("spec_draft", _first(metrics, _SPEC_DRAFT))
        accepted_delta = self._delta("spec_accepted", _first(metrics, _SPEC_ACCEPTED))
        accept_rate = _first(metrics, _SPEC_ACCEPT_RATE)
        if (accept_rate is None and draft_delta is not None and draft_delta > 0
                and accepted_delta is not None):
            accept_rate = accepted_delta / draft_delta

        return {
            "running_requests": running,
            "waiting_requests": waiting,
            # vLLM reports cache usage as a 0-1 fraction; normalize to 0-100.
            "gpu_cache_usage_pct": cache * 100.0 if cache <= 1.0 else cache,
            "gpu_prefix_cache_hit_rate": prefix_hit,
            "tokens_per_sec_decode": tps,
            "mtp_acceptance_rate": accept_rate,
            "mtp_draft_tokens": draft_delta,
            "mtp_accepted_tokens": accepted_delta,
        }, None
