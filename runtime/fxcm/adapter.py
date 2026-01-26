from __future__ import annotations

from typing_extensions import Protocol


class FxcmAdapter(Protocol):
    def resubscribe_offers(self) -> bool: ...

    def reconnect(self) -> bool: ...

    def is_market_open(self, now_ms: int) -> bool: ...
