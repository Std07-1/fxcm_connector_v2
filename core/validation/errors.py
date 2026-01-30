from __future__ import annotations


class ContractError(ValueError):
    """Помилка контракту: payload не відповідає allowlist schema."""
