from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from runtime.history_provider import HistoryProvider


@dataclass
class HistoryFxcmProvider(HistoryProvider):
    """LEGACY/UNUSED: застаріла заглушка провайдера FXCM.

    Реальна інтеграція історії знаходиться у runtime/fxcm/history_provider.py.
    """

    def fetch_1m_final(self, symbol: str, start_ms: int, end_ms: int, limit: int) -> List[Dict]:
        raise RuntimeError(
            "LEGACY/UNUSED: застаріла заглушка FXCM history. Використай runtime/fxcm/history_provider.py"
        )
