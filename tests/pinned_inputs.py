"""Pure byte-identity checks for private test inputs; no I/O or fixture data.

The trusted test caller supplies expected identities before it reads/replays
inputs. This does not authenticate that caller or promote scientific evidence.
"""
import hashlib


def verify_inputs(sources, expected):
    if type(sources) is not dict or type(expected) is not dict or set(sources) != set(expected):
        raise ValueError("input set differs from pinned manifest")
    for name, raw in sources.items():
        if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != expected[name]:
            raise ValueError("input digest differs from pinned manifest: " + name)
    return sources
