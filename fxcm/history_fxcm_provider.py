from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from runtime.history_provider import HistoryProvider


@dataclass
class HistoryFxcmProvider(HistoryProvider):
    """Скелет провайдера FXCM (без реальної інтеграції у P3)."""

    def fetch_1m_final(
        self, symbol: str, start_ms: int, end_ms: int, limit: int
    ) -> List[Dict]:
        raise RuntimeError(
            "FXCM провайдер не налаштований у P3. Використай provider=sim."
        )
