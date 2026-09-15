"""The registered near-ceiling packet uses Mia's actual pinned tokenizer."""
from __future__ import annotations

from bench.flash_next_ab import followon_native_packet as native


def test_native_packet_retokenizes_to_the_frozen_chat_template_count():
    packet = native.prepared_factory()()
    assert packet["cell_id"] == native.PACK_ID
    assert packet["actual_input_tokens"] == 65_581
    assert packet["actual_input_tokens"] + packet["max_tokens"] == 67_629
    assert packet["source_messages_sha256"] == native.MESSAGE_SHA256
