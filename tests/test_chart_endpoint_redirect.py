from __future__ import annotations

from runtime.http_server import _build_chart_stub_response, _build_ui_lite_redirect


def test_chart_redirect_host_without_port() -> None:
    url = _build_ui_lite_redirect("example.com", 8089)
    assert url == "http://example.com:8089/"


def test_chart_redirect_host_with_port() -> None:
    url = _build_ui_lite_redirect("example.com:8080", 8089)
    assert url == "http://example.com:8089/"


def test_chart_ui_lite_disabled_returns_503() -> None:
    status, headers, body = _build_chart_stub_response("example.com", False, 8089)
    assert status == 503
    assert headers.get("Content-Type") == "text/html; charset=utf-8"
    assert "UI Lite вимкнено" in body.decode("utf-8")
