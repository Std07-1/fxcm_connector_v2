from __future__ import annotations

from enum import Enum


class BackendMode(str, Enum):
    FOREXCONNECT = "forexconnect"
    REPLAY = "replay"
    DISABLED = "disabled"
    SIM = "sim"


def parse_mode(value: str) -> BackendMode:
    if value == BackendMode.FOREXCONNECT.value:
        return BackendMode.FOREXCONNECT
    if value == BackendMode.REPLAY.value:
        return BackendMode.REPLAY
    if value == BackendMode.DISABLED.value:
        return BackendMode.DISABLED
    if value == BackendMode.SIM.value:
        return BackendMode.SIM
    raise ValueError(f"Невідомий режим backend: {value}")


def is_forexconnect(mode: BackendMode) -> bool:
    return mode == BackendMode.FOREXCONNECT
