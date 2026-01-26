# V2 P3–P5 Flow (as-is)

Дата: 2026-01-22
Режим: read-only discovery

## Послідовність (warmup/backfill → SSOT → derived → tail_guard → republish)

1) Warmup/Backfill отримує history 1m та пише у SSOT SQLite.
   - Warmup: [runtime/warmup.py](runtime/warmup.py#L44-L92)
   - Backfill: [runtime/backfill.py](runtime/backfill.py#L49-L92)
   - SSOT schema: [store/schema.sql](store/schema.sql#L1-L23)

2) SSOT 1m final → derived rebuild (HTF final).
   - HTF builder: [store/derived_builder.py](store/derived_builder.py#L31-L123)
   - Rebuild coordinator: [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L87-L207)

3) Tail guard audit/repair → optional rebuild/republish.
   - Tail guard core: [runtime/tail_guard.py](runtime/tail_guard.py#L43-L190)
   - Repair window (market closed): [core/time/calendar.py](core/time/calendar.py#L31-L34)
   - Republish watermark: [runtime/republish.py](runtime/republish.py#L15-L77)

## Де оновлюється status:snapshot

- publish_snapshot: [runtime/status.py](runtime/status.py#L931-L948) — під час lifecycle у app/composition: [app/composition.py](app/composition.py#L112-L344).
- Preview publish counters: record_ohlcv_publish → [runtime/status.py](runtime/status.py#L509-L547), викликається при preview publish: [app/composition.py](app/composition.py#L392-L404).
- Final publish counters: record_final_publish → [runtime/status.py](runtime/status.py#L629-L709), виклики: warmup/backfill/rebuild/handlers. Приклади: [runtime/warmup.py](runtime/warmup.py#L85-L92), [runtime/backfill.py](runtime/backfill.py#L82-L86), [runtime/rebuild_derived.py](runtime/rebuild_derived.py#L262-L265),
[runtime/handlers_p4.py](runtime/handlers_p4.py#L64-L74).
- Tail guard summary: record_tail_guard_summary → [runtime/status.py](runtime/status.py#L808-L838), виклики: [runtime/tail_guard.py](runtime/tail_guard.py#L84-L192).
- Republish watermark state: record_republish → [runtime/status.py](runtime/status.py#L840-L866), виклик: [runtime/republish.py](runtime/republish.py#L75-L77).

## Примітки (as-is)

- Провайдер history для FXCM не налаштований (ProviderNotConfiguredError). [app/composition.py](app/composition.py#L124-L130), [fxcm/history_fxcm_provider.py](fxcm/history_fxcm_provider.py#L1-L15).
