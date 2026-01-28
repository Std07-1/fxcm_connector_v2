from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from config.config import Config
from core.validation.validator import ContractError, SchemaValidator
from runtime.no_mix import NoMixDetector
from runtime.status import StatusManager


class RedisPublisher:
    """Єдина точка запису у Redis для status."""

    def __init__(
        self,
        redis_client: Any,
        config: Config,
        no_mix: Optional[NoMixDetector] = None,
        status: Optional[StatusManager] = None,
    ) -> None:
        self._redis = redis_client
        self._config = config
        self._no_mix = no_mix
        self._status = status

    def set_status(self, status: StatusManager) -> None:
        self._status = status

    @staticmethod
    def json_dumps(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def set_snapshot(self, key: str, json_str: str) -> None:
        self._redis.set(key, json_str)

    def publish(self, channel: str, json_str: str) -> None:
        self._redis.publish(channel, json_str)

    def publish_tick(self, channel: str, payload: Dict[str, Any], validator: SchemaValidator) -> None:
        validator.validate_tick_v1(payload)
        json_str = self.json_dumps(payload)
        self.publish(channel, json_str)

    def publish_ohlcv(
        self,
        channel: str,
        payload: Dict[str, Any],
        validator: SchemaValidator,
        max_bars_per_message: int,
    ) -> None:
        validator.validate_ohlcv_v1(payload, max_bars_per_message)
        json_str = self.json_dumps(payload)
        self.publish(channel, json_str)

    def publish_ohlcv_batch(
        self,
        symbol: str,
        tf: str,
        bars: List[Dict[str, Any]],
        source: str = "stream",
        validator: SchemaValidator = None,  # type: ignore[assignment]
    ) -> None:
        if validator is None:
            raise ValueError("validator є обов'язковим")
        if not bars:
            raise ContractError("bars має бути непорожнім списком")
        channel = self._config.ch_ohlcv()
        max_bars = int(self._config.max_bars_per_message)
        for i in range(0, len(bars), max_bars):
            chunk = bars[i : i + max_bars]
            payload = {
                "symbol": symbol,
                "tf": tf,
                "source": source,
                "complete": False,
                "synthetic": False,
                "bars": chunk,
            }
            validator.validate_ohlcv_preview_batch(payload)
            json_str = self.json_dumps(payload)
            self.publish(channel, json_str)

    def publish_ohlcv_final_1m(
        self,
        symbol: str,
        bars: List[Dict[str, Any]],
        validator: SchemaValidator,
    ) -> None:
        if not bars:
            raise ContractError("bars має бути непорожнім списком")
        _validate_final_bars(bars)
        channel = self._config.ch_ohlcv()
        max_bars = int(self._config.max_bars_per_message)
        for i in range(0, len(bars), max_bars):
            chunk = bars[i : i + max_bars]
            payload = {
                "symbol": symbol,
                "tf": "1m",
                "source": "history",
                "complete": True,
                "synthetic": False,
                "bars": chunk,
            }
            validator.validate_ohlcv_final_1m_batch(payload)
            if self._no_mix is not None and self._status is not None:
                ok = self._no_mix.check_final_payload(payload, self._status)
                if not ok:
                    return
            json_str = self.json_dumps(payload)
            self.publish(channel, json_str)

    def publish_ohlcv_final_htf(
        self,
        symbol: str,
        tf: str,
        bars: List[Dict[str, Any]],
        validator: SchemaValidator,
    ) -> None:
        if not bars:
            raise ContractError("bars має бути непорожнім списком")
        _validate_final_bars(bars)
        channel = self._config.ch_ohlcv()
        max_bars = int(self._config.max_bars_per_message)
        for i in range(0, len(bars), max_bars):
            chunk = bars[i : i + max_bars]
            payload = {
                "symbol": symbol,
                "tf": tf,
                "source": "history_agg",
                "complete": True,
                "synthetic": False,
                "bars": chunk,
            }
            validator.validate_ohlcv_final_htf_batch(payload)
            if self._no_mix is not None and self._status is not None:
                ok = self._no_mix.check_final_payload(payload, self._status)
                if not ok:
                    return
            json_str = self.json_dumps(payload)
            self.publish(channel, json_str)


def _validate_final_bars(bars: List[Dict[str, Any]]) -> None:
    seen = set()
    last_open = None
    for bar in bars:
        open_time = int(bar["open_time"])
        close_time = int(bar["close_time"])
        event_ts = int(bar["event_ts"])
        if bar.get("complete") is not True:
            raise ContractError("final bar має complete=true")
        if bar.get("synthetic") is not False:
            raise ContractError("final bar має synthetic=false")
        source = bar.get("source")
        if source not in {"history", "history_agg"}:
            raise ContractError("final bar має source=history або history_agg")
        if last_open is not None and open_time < last_open:
            raise ContractError("bars мають бути відсортовані за open_time")
        if open_time in seen:
            raise ContractError("bars містять дублі open_time")
        if event_ts != close_time:
            raise ContractError("event_ts має дорівнювати close_time")
        seen.add(open_time)
        last_open = open_time
