# Audit v5 — System Map (as‑is)

Дата: 2026-01-22
Режим: read-only discovery

## Dataflow (ticks → preview → final → derived → publish → UI)

```
FXCM tick (offers)
  → TickPublisher (price_tik)
  → PreviewBuilder (ohlcv preview)
  → Redis {NS}:ohlcv
  → UI Lite WS

HistoryProvider
  → SQLite SSOT 1m final
  → Derived builder (HTF)
  → SQLite HTF final
  → Redis {NS}:ohlcv (final)
  → HTTP /api/ohlcv?mode=final
```

Докази потоків:
- FXCM tick → TickPublisher: [runtime/fxcm_forexconnect.py](runtime/fxcm_forexconnect.py#L186-L271), [runtime/tick_feed.py](runtime/tick_feed.py#L15-L52).
- PreviewBuilder → Redis {NS}:ohlcv: [runtime/preview_builder.py](runtime/preview_builder.py#L87-L173), [app/composition.py](app/composition.py#L375-L415).
- UI Lite WS читає {NS}:ohlcv: [ui_lite/server.py](ui_lite/server.py#L380-L470).
- History → SQLite 1m final: [runtime/warmup.py](runtime/warmup.py#L44-L92), [runtime/backfill.py](runtime/backfill.py#L49-L92), [store/schema.sql](store/schema.sql#L1-L23).
- Derived HTF → SQLite + publish: [store/derived_builder.py](store/derived_builder.py#L31-L123), [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L87-L207), [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L304-L307).
- HTTP final: [runtime/http_server.py](runtime/http_server.py#L81-L117).

## SSOT (що є / що не є SSOT)

- SSOT = SQLite final 1m + HTF (bars_1m_final, bars_htf_final). [store/schema.sql](store/schema.sql#L1-L75).
- НЕ SSOT = preview cache (in‑memory). [runtime/preview_builder.py](runtime/preview_builder.py#L39-L71).

## Invariants & Enforcement Points

- Час = epoch ms (lower bound >=1e12). [core/validation/validator.py](core/validation/validator.py#L28-L33).
- close_time inclusive: open_time + TF − 1. [core/time/buckets.py](core/time/buckets.py#L52-L69), [store/schema.sql](store/schema.sql#L19-L22).
- final 1m source=history + event_ts==close_time: [store/schema.sql](store/schema.sql#L19-L23), [core/validation/validator.py](core/validation/validator.py#L170-L191).
- final HTF source=history_agg + event_ts==close_time: [store/schema.sql](store/schema.sql#L56-L75), [core/validation/validator.py](core/validation/validator.py#L204-L234).
- NoMix rail: runtime + store + gate: [runtime/no_mix.py](runtime/no_mix.py#L8-L43), [store/schema.sql](store/schema.sql#L56-L75), [tools/exit_gates/gates/gate_no_mix.py](tools/exit_gates/gates/gate_no_mix.py#L1-L54).
- Status payload size rail: [runtime/status.py](runtime/status.py#L16-L95), [runtime/status.py](runtime/status.py#L931-L948).

## Drift/Lie ризики (as‑is)

- Wall‑clock ticks: FXCM offers використовує now_ms як tick_ts_ms/snap_ts_ms. [runtime/fxcm_forexconnect.py](runtime/fxcm_forexconnect.py#L186-L202).
- Units mismatch у UI: `open_time_ms/1000` та `bar.time` без unit‑guard. [ui_lite/server.py](ui_lite/server.py#L198-L206), [ui_lite/static/chart_adapter.js](ui_lite/static/chart_adapter.js#L15-L20).
- Calendar stub: market state не базується на реальних сесіях. [core/time/calendar.py](core/time/calendar.py#L14-L27), degraded у статусі: [runtime/status.py](runtime/status.py#L140).
- Provider not configured: history provider кидає ProviderNotConfiguredError. [app/composition.py](app/composition.py#L124-L130), [fxcm/history_fxcm_provider.py](fxcm/history_fxcm_provider.py#L1-L15).
