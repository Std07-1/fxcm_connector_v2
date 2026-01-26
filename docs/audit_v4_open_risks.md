# Audit v4 — Open Risks

Дата: 2026-01-22
Режим: read-only discovery (код не змінювався)

## 1) Роз’їзди P-нумерації (P4.1)

**Факт:** у SSOT‑доках є P4, але P4.1 не знайдено.
- [docs/Public API Spec (SSOT).md](docs/Public%20API%20Spec%20(SSOT).md#L411)
- [docs/Public Surface.md](docs/Public%20Surface.md#L411)

**Ризик:** дрейф нумерації між документацією, gates і фактичним runtime.

**Рекомендація:** зафіксувати P‑індексацію в одному SSOT‑докі та посилатися звідти в усіх README/ADR.

## 2) Calendar stub / degraded та наслідки

**Факт:** календар є stub і відмічений як degraded у статусі.
- [core/time/calendar.py](core/time/calendar.py#L14-L27)
- [runtime/status.py](runtime/status.py#L140)

**Наслідки:** логіка «market open/closed» базова; risk‑рейки (repair/pauses) можуть працювати на stub‑даних.

## 3) FXCM provider gap (не реалізовано з v1)

**Факт:** history provider не налаштований у runtime.
- [app/composition.py](app/composition.py#L124-L130)
- [fxcm/history_fxcm_provider.py](fxcm/history_fxcm_provider.py#L1-L15)

**Наслідки:** warmup/backfill не можуть працювати з реальним FXCM history без впровадження провайдера.

## 4) UI «зсув вправо» як симптом time boundary

**Факт:** UI нормалізація бере `bar.time` без перевірки одиниць; якщо приходить ms/us як sec, шкала стрибає в майбутнє.
- [ui_lite/static/chart_adapter.js](ui_lite/static/chart_adapter.js#L15-L20)

**Факт:** FXCM offers tick використовує wall‑clock `now_ms` як `tick_ts_ms` без реального timestamp.
- [runtime/fxcm_forexconnect.py](runtime/fxcm_forexconnect.py#L186-L202)

**Наслідки:** “зсув вправо” може бути системною проблемою (тип 1) і не лише UI‑візуалізацією. Для типу 2 (реальні weekend gaps) потрібна окрема політика рендера.

---

## GO/NO‑GO до наступного slice

**NO‑GO**: потрібні рішення для history provider (реальні backfill/річні дані) та політики wall‑clock ticks під час market=CLOSED.
