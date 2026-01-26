# Audit v6 — Duplication smells (read-only)

## 1) Дві окремі HTTP поверхні для chart/UI
- `runtime/http_server.py` віддає `/chart` (HTML) та `/api/*` — [runtime/http_server.py](runtime/http_server.py#L66-L136).
- `ui_lite/server.py` віддає статичні ресурси UI Lite (`/`, `/index.html`, `/app.js`, `/styles.css`, `/chart_adapter.js`) та `/debug` — [ui_lite/server.py](ui_lite/server.py#L133-L178).
- Ризик: паралельні UI-шари можуть дублювати логіку відображення/потоків даних і вимагати синхронізації.

## 2) Подвійна логіка дедуплікації барів у UI Lite
- Є клас `DedupIndex` (in-memory set) — [ui_lite/server.py](ui_lite/server.py#L42-L51).
- Паралельно існує глобальний механізм `_DEDUP_KEYS` з ручним керуванням set — [ui_lite/server.py](ui_lite/server.py#L119-L245).
- Також у пайплайні використовується `DedupIndex` — [ui_lite/server.py](ui_lite/server.py#L406-L437).
- Ризик: дублювання логіки дедуплікації ускладнює підтримку і може призвести до розходжень поведінки.
