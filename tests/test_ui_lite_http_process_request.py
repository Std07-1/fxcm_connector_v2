from __future__ import annotations

from typing import Any

from ui_lite.server import _process_request


def _header_names(headers: Any) -> list:
    if hasattr(headers, "items"):
        return [name.lower() for name, _ in headers.items()]
    return [name.lower() for name, _ in headers]


def test_ui_lite_process_request_root() -> None:
    resp = _process_request("/", {})
    assert resp is not None
    status, headers, body = resp
    assert status == 200
    assert "content-type" in _header_names(headers)
    assert b"<html" in body or b"<!doctype" in body


def test_ui_lite_process_request_app_js() -> None:
    resp = _process_request("/app.js", {})
    assert resp is not None
    status, headers, _body = resp
    assert status in (200, 404)
    assert "content-type" in _header_names(headers)


def test_ui_lite_process_request_unknown() -> None:
    resp = _process_request("/nope", {})
    assert resp is not None
    status, headers, _body = resp
    assert status == 404
    assert "content-type" in _header_names(headers)
