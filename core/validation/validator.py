from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, cast

from jsonschema import Draft7Validator

from config.config import Config
from core.time.buckets import TF_TO_MS
from core.time.calendar import Calendar
from core.time.epoch_rails import MAX_EPOCH_MS, MIN_EPOCH_MS
from core.validation.errors import ContractError

TF_ALLOWLIST = {"1m", "5m", "15m", "1h", "4h", "1d"}
HTF_FINAL_ALLOWLIST = {"5m", "15m", "1h", "4h", "1d"}
SOURCE_ALLOWLIST = {"stream", "history", "history_agg", "synthetic"}
FINAL_SOURCES = {"history", "history_agg"}


def _format_error_message(err: Any) -> str:
    path = ".".join([str(p) for p in err.path]) if err.path else "<root>"
    return f"Порушено контракт у {path}: {err.message}"


def _require_ms_int(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"Поле {field_name} має бути int ms")
    if value < MIN_EPOCH_MS:
        raise ContractError(f"Поле {field_name} має бути epoch ms, не seconds")
    if value > MAX_EPOCH_MS:
        raise ContractError(f"Поле {field_name} має бути epoch ms, не microseconds")


def _require_tf_allowed(tf: str) -> None:
    if tf not in TF_ALLOWLIST:
        raise ContractError(f"TF не дозволено: {tf}")


def _require_source_allowed(source: str) -> None:
    if source not in SOURCE_ALLOWLIST:
        raise ContractError(f"Source не дозволено: {source}")


def _require_bars_sorted_unique(bars: list) -> None:
    last_open = None
    for bar in bars:
        open_time = bar.get("open_time")
        if isinstance(open_time, bool) or not isinstance(open_time, int):
            raise ContractError("open_time має бути int для сортування")
        if last_open is not None and open_time <= last_open:
            raise ContractError("bars мають бути відсортовані та без дублікатів open_time")
        last_open = open_time


def _require_ohlcv_invariants(bar: Dict[str, Any]) -> None:
    open_p = bar.get("open")
    high = bar.get("high")
    low = bar.get("low")
    close = bar.get("close")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in [open_p, high, low, close]):
        raise ContractError("OHLC має бути числовим")
    open_f = float(cast(float, open_p))
    high_f = float(cast(float, high))
    low_f = float(cast(float, low))
    close_f = float(cast(float, close))
    if high_f < max(open_f, close_f):
        raise ContractError("high має бути >= max(open, close)")
    if low_f > min(open_f, close_f):
        raise ContractError("low має бути <= min(open, close)")
    if high_f < low_f:
        raise ContractError("high має бути >= low")


def _require_canonical_ohlcv_keys(bar: Dict[str, Any]) -> None:
    legacy_keys = ["o", "h", "l", "c", "v"]
    if any(key in bar for key in legacy_keys):
        raise ContractError("OHLCV має використовувати open/high/low/close/volume")


def _require_bucket_boundary(tf: str, open_time: int, close_time: int, calendar: Calendar) -> None:
    size = TF_TO_MS.get(tf)
    if size is None:
        raise ContractError(f"Невідомий TF для bucket: {tf}")
    if tf == "1d":
        expected_open = calendar.trading_day_boundary_for(open_time)
        if int(open_time) != int(expected_open):
            raise ContractError("open_time має бути вирівняний по trading_day_boundary (calendar)")
        expected_close = calendar.next_trading_day_boundary_ms(open_time) - 1
        if int(close_time) != int(expected_close):
            raise ContractError("close_time має дорівнювати next_trading_day_boundary_ms - 1")
        return
    if open_time % size != 0:
        raise ContractError("open_time має бути вирівняний по bucket")
    expected_close = open_time + size - 1
    if close_time != expected_close:
        raise ContractError("close_time має дорівнювати bucket_end_ms - 1")


@dataclass
class SchemaStore:
    """Сховище JSON схем з кешем (allowlist)."""

    root_dir: Path
    _cache: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def load(self, rel_path: str) -> Dict[str, Any]:
        if rel_path in self._cache:
            return self._cache[rel_path]
        schema_path = self.root_dir / rel_path
        if not schema_path.exists():
            raise ContractError(f"Schema не знайдено: {schema_path}")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema_dict = cast(Dict[str, Any], schema)
        self._cache[rel_path] = schema_dict
        return schema_dict


@dataclass
class SchemaValidator:
    """Валідатор payload за JSON schema з fail-fast."""

    root_dir: Path
    calendar: Optional[Calendar] = None

    def _store(self) -> SchemaStore:
        return SchemaStore(self.root_dir)

    def _calendar(self) -> Calendar:
        if self.calendar is not None:
            return self.calendar
        config = Config()
        return Calendar(calendar_tag=config.calendar_tag, overrides_path=config.calendar_path)

    def validate(self, rel_schema_path: str, payload: Dict[str, Any]) -> None:
        schema = self._store().load(rel_schema_path)
        validator = Draft7Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
        if errors:
            raise ContractError(_format_error_message(errors[0]))

    def validate_commands_v1(self, payload: Dict[str, Any]) -> None:
        self.validate("core/contracts/public/commands_v1.json", payload)

    def validate_status_v2(self, payload: Dict[str, Any]) -> None:
        self.validate("core/contracts/public/status_v2.json", payload)

    def validate_tick_v1(self, payload: Dict[str, Any]) -> None:
        self.validate("core/contracts/public/tick_v1.json", payload)
        _require_ms_int(payload.get("tick_ts"), "tick_ts")
        _require_ms_int(payload.get("snap_ts"), "snap_ts")

    def validate_ohlcv_preview_batch(self, payload: Dict[str, Any]) -> None:
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise ContractError("symbol має бути непорожнім рядком")
        tf = payload.get("tf")
        if not isinstance(tf, str) or tf not in TF_ALLOWLIST:
            raise ContractError("tf має бути з allowlist")
        bars = payload.get("bars")
        if not isinstance(bars, list) or not bars:
            raise ContractError("bars має бути непорожнім списком")
        _require_bars_sorted_unique(bars)
        for bar in bars:
            _require_ms_int(bar.get("open_time"), "open_time")
            _require_ms_int(bar.get("close_time"), "close_time")
            if int(bar.get("open_time")) >= int(bar.get("close_time")):
                raise ContractError("open_time має бути < close_time")
            if bar.get("synthetic") is True:
                raise ContractError("Preview не може бути synthetic=true")
            _require_ohlcv_invariants(bar)

    def validate_ohlcv_final_1m_batch(self, payload: Dict[str, Any]) -> None:
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise ContractError("symbol має бути непорожнім рядком")
        tf = payload.get("tf")
        if tf != "1m":
            raise ContractError("final 1m має tf=1m")
        source = payload.get("source")
        if source != "history":
            raise ContractError("final 1m має source=history")
        if payload.get("complete") is not True:
            raise ContractError("final 1m має complete=true")
        if payload.get("synthetic") is not False:
            raise ContractError("final 1m має synthetic=false")
        bars = payload.get("bars")
        if not isinstance(bars, list) or not bars:
            raise ContractError("bars має бути непорожнім списком")
        _require_bars_sorted_unique(bars)
        for bar in bars:
            _require_ms_int(bar.get("open_time"), "open_time")
            _require_ms_int(bar.get("close_time"), "close_time")
            if int(bar.get("open_time")) >= int(bar.get("close_time")):
                raise ContractError("open_time має бути < close_time")
            _require_bucket_boundary("1m", int(bar.get("open_time")), int(bar.get("close_time")), self._calendar())
            if bar.get("complete") is not True:
                raise ContractError("final 1m має complete=true")
            if bar.get("synthetic") is not False:
                raise ContractError("final 1m має synthetic=false")
            if bar.get("source") != "history":
                raise ContractError("final 1m bar має source=history")
            _require_ohlcv_invariants(bar)
            event_ts = bar.get("event_ts")
            if event_ts is not None:
                _require_ms_int(event_ts, "event_ts")
                if int(event_ts) != int(bar.get("close_time")):
                    raise ContractError("event_ts має дорівнювати close_time")

    def validate_ohlcv_final_htf_batch(self, payload: Dict[str, Any]) -> None:
        self.validate("core/contracts/public/ohlcv_v1.json", payload)
        symbol = payload.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise ContractError("symbol має бути непорожнім рядком")
        tf = payload.get("tf")
        if not isinstance(tf, str) or tf not in HTF_FINAL_ALLOWLIST:
            raise ContractError("tf має бути з allowlist для HTF final")
        source = payload.get("source")
        if source != "history_agg":
            raise ContractError("HTF final має source=history_agg")
        complete = payload.get("complete")
        synthetic = payload.get("synthetic")
        if complete is not True:
            raise ContractError("HTF final має complete=true")
        if synthetic is not False:
            raise ContractError("HTF final має synthetic=false")
        bars = payload.get("bars")
        if not isinstance(bars, list) or not bars:
            raise ContractError("bars має бути непорожнім списком")
        _require_bars_sorted_unique(bars)
        for bar in bars:
            _require_canonical_ohlcv_keys(bar)
            _require_ms_int(bar.get("open_time"), "open_time")
            _require_ms_int(bar.get("close_time"), "close_time")
            if int(bar.get("open_time")) >= int(bar.get("close_time")):
                raise ContractError("open_time має бути < close_time")
            _require_bucket_boundary(tf, int(bar.get("open_time")), int(bar.get("close_time")), self._calendar())
            _require_ohlcv_invariants(bar)
            if bar.get("complete") is not True:
                raise ContractError("bar має complete=true")
            if bar.get("synthetic") is not False:
                raise ContractError("bar має synthetic=false")
            if bar.get("source") != "history_agg":
                raise ContractError("bar має source=history_agg")
            event_ts = bar.get("event_ts")
            if event_ts is None:
                raise ContractError("event_ts є обов'язковим для HTF final")
            _require_ms_int(event_ts, "event_ts")
            if int(event_ts) != int(bar.get("close_time")):
                raise ContractError("event_ts має дорівнювати close_time")
            bar_tf = bar.get("tf")
            if bar_tf is not None and str(bar_tf) != tf:
                raise ContractError("bars.tf має збігатися з root.tf")

    def validate_ohlcv_v1(self, payload: Dict[str, Any], max_bars_per_message: int) -> None:
        self.validate("core/contracts/public/ohlcv_v1.json", payload)

        tf = str(payload.get("tf"))
        _require_tf_allowed(tf)

        source = str(payload.get("source"))
        _require_source_allowed(source)

        complete = bool(payload.get("complete"))
        synthetic = bool(payload.get("synthetic"))
        if source == "stream":
            if complete:
                raise ContractError("Preview не може мати complete=true")
            if synthetic:
                raise ContractError("Preview не може бути synthetic=true")
        if complete:
            if source not in FINAL_SOURCES:
                raise ContractError("Final має source з FINAL_SOURCES")
            if synthetic:
                raise ContractError("Final не може бути synthetic=true")
            if tf == "1m" and source != "history":
                raise ContractError("Final 1m має мати source=history")
            if tf != "1m" and source != "history_agg":
                raise ContractError("Final HTF має мати source=history_agg")

        bars = payload.get("bars")
        if not isinstance(bars, list):
            raise ContractError("bars має бути списком")
        if len(bars) > max_bars_per_message:
            raise ContractError("Перевищено max_bars_per_message")

        _require_bars_sorted_unique(bars)

        for bar in bars:
            _require_canonical_ohlcv_keys(bar)
            _require_ms_int(bar.get("open_time"), "open_time")
            _require_ms_int(bar.get("close_time"), "close_time")
            _require_bucket_boundary(tf, int(bar.get("open_time")), int(bar.get("close_time")), self._calendar())
            bar_source = str(bar.get("source"))
            _require_source_allowed(bar_source)
            bar_complete = bool(bar.get("complete"))
            bar_synthetic = bool(bar.get("synthetic"))
            if bar_source != source:
                raise ContractError("source у bar має збігатися з root")
            if bar_complete != complete:
                raise ContractError("complete у bar має збігатися з root")
            if bar_synthetic != synthetic:
                raise ContractError("synthetic у bar має збігатися з root")
            if complete:
                event_ts = bar.get("event_ts")
                _require_ms_int(event_ts, "event_ts")
                if int(event_ts) != int(bar.get("close_time")):
                    raise ContractError("event_ts має дорівнювати close_time")
