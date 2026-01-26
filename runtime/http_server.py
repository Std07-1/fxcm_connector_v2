from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from config.config import Config
from runtime.preview_builder import OhlcvCache
from store.sqlite_store import SQLiteStore

log = logging.getLogger(__name__)


def _build_ui_lite_redirect(host_header: str, ui_lite_port: int) -> str:
    host_value = (host_header or "").strip()
    if not host_value:
        host_value = "127.0.0.1"
    host = host_value
    if host_value.startswith("[") and "]" in host_value:
        end = host_value.find("]")
        host = host_value[: end + 1]
    elif ":" in host_value:
        host = host_value.rsplit(":", 1)[0]
    return f"http://{host}:{int(ui_lite_port)}/"


def _build_chart_stub_response(
    host_header: str, ui_lite_enabled: bool, ui_lite_port: int
) -> Tuple[int, Dict[str, str], bytes]:
    if not ui_lite_enabled:
        body = (
            "<html><body><h3>UI Lite вимкнено.</h3>"
            "<p>Увімкніть ui_lite_enabled у конфігу. /api/* доступні.</p>"
            "</body></html>"
        ).encode("utf-8")
        return 503, {"Content-Type": "text/html; charset=utf-8"}, body
    url = _build_ui_lite_redirect(host_header, ui_lite_port)
    return 302, {"Location": url}, b""


@dataclass
class HttpServer:
    """HTTP сервер для read-only chart."""

    config: Config
    redis_client: Any
    cache: OhlcvCache
    store: Optional[SQLiteStore] = None
    _server: Optional[ThreadingHTTPServer] = None
    _thread: Optional[threading.Thread] = None

    def start(self, host: str = "127.0.0.1") -> None:
        handler = self._make_handler()
        self._server = ThreadingHTTPServer((host, self.config.http_port), handler)
        self._server.timeout = 0.5
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def port(self) -> int:
        if self._server is None:
            return self.config.http_port
        return int(self._server.server_address[1])

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except KeyboardInterrupt:
                logging.getLogger(__name__).info("Отримано KeyboardInterrupt під час зупинки HTTP сервера.")
            finally:
                self._server.server_close()
            if self._thread is not None:
                self._thread.join(timeout=2.0)

    def _make_handler(self) -> type:
        config = self.config
        redis_client = self.redis_client
        cache = self.cache
        store = self.store

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/api/status":
                    raw = redis_client.get(config.key_status_snapshot())
                    if not raw:
                        self._send_json({})
                        return
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        self._send_json({}, status=500)
                        return
                    self._send_json(payload)
                    return

                if parsed.path == "/api/ohlcv":
                    qs = parse_qs(parsed.query)
                    symbol = qs.get("symbol", ["XAUUSD"])[0]
                    tf = qs.get("tf", ["1m"])[0]
                    mode = qs.get("mode", ["preview"])[0]
                    limit_str = qs.get("limit", ["300"])[0]
                    try:
                        limit = int(limit_str)
                    except ValueError:
                        limit = 300
                    if mode == "final":
                        if store is None:
                            self._send_json({"error": "store не налаштований"}, status=500)
                            return
                        if tf == "1m":
                            rows = store.query_1m_tail(symbol, limit)
                        elif tf in {"15m", "1h", "4h", "1d"}:
                            rows = store.query_htf_tail(symbol, tf, limit)
                        else:
                            self._send_json(
                                {"error": "tf не підтримується для final"},
                                status=400,
                            )
                            return
                        bars = [
                            {
                                "open_time": r["open_time_ms"],
                                "close_time": r["close_time_ms"],
                                "open": r["open"],
                                "high": r["high"],
                                "low": r["low"],
                                "close": r["close"],
                                "volume": r["volume"],
                                "complete": True,
                                "synthetic": False,
                                "source": r["source"],
                                "event_ts": r["event_ts_ms"],
                            }
                            for r in rows
                        ]
                        self._send_json({"symbol": symbol, "tf": tf, "bars": bars})
                        return

                    bars = cache.get_tail(symbol, tf, limit)
                    self._send_json({"symbol": symbol, "tf": tf, "bars": bars})
                    return

                if parsed.path == "/chart":
                    status, headers, body = _build_chart_stub_response(
                        self.headers.get("Host", ""),
                        config.ui_lite_enabled,
                        config.ui_lite_port,
                    )
                    if status == 302:
                        log.info("/chart → UI Lite redirect")
                    self.send_response(status)
                    for key, value in headers.items():
                        self.send_header(key, value)
                    if body:
                        self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    if body:
                        self.wfile.write(body)
                    return

                self.send_response(404)
                self.end_headers()

        return Handler
