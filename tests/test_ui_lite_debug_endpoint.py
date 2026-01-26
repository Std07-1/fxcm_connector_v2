from __future__ import annotations

import json

from ui_lite import server


def test_ui_lite_debug_endpoint() -> None:
    resp = server._process_request("/debug", {})
    assert resp is not None
    status, _headers, body = resp
    assert int(status) == 200
    payload = json.loads(body.decode("utf-8"))
    assert "redis_rx_total" in payload
    assert "last_payload_open_time_ms" in payload
    assert "last_payload_close_time_ms" in payload
    assert "last_payload_mode" in payload
    assert "last_ui_bar_time_s" in payload
    assert "last_ring_size" in payload
