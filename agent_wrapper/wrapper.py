"""
Day 2 will fill this in. Module docstring lists the JSONL fields the
wrapper intends to log:
- timestamp (ISO 8601)
- request_id (uuid4)
- model
- model_version (image digest)
- temperature
- top_p
- seed
- prompt_messages (full array)
- completion
- usage (input/output tokens)
- latency_ms
- host_metadata (CUDA driver, vLLM image tag)
- caller_tag
- parent_request_id (null for now; chains start Day 4)

Day 2 adds: call_sync, call_async, verify_log_integrity.
Day 4 adds: call_with_tools (max recursion depth 3).
"""
