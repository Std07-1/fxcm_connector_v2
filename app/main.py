from __future__ import annotations

import argparse
import logging
import time
from dataclasses import replace
from pathlib import Path

from app.composition import build_runtime, stop_runtime
from config.config import load_config
from core.env_loader import load_env
from runtime.fxcm_forexconnect import check_fxcm_environment


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fxcm-preview", action="store_true", help="Реальний FXCM preview через ForexConnect")
    return parser.parse_args()


def main() -> None:
    _setup_logging()
    log = logging.getLogger("fxcm_p0")

    root_dir = Path(__file__).resolve().parents[1]
    load_env(root_dir)
    args = _parse_args()

    config = load_config()
    if args.fxcm_preview:
        config = replace(
            config,
            fxcm_backend="forexconnect",
            tick_mode="off",
            preview_mode="off",
            ohlcv_sim_enabled=False,
            ohlcv_preview_enabled=True,
            ohlcv_preview_tfs=["1m"],
        )
    log.info("Старт P0 конектора з NS=%s (profile=%s)", config.ns, config.profile)
    log.debug(
        "Redis channels: status=%s commands=%s price_tik=%s ohlcv=%s",
        config.ch_status(),
        config.ch_commands(),
        config.ch_price_tik(),
        config.ch_ohlcv(),
    )
    log.debug(
        "Preview settings: enabled=%s symbols=%s tfs=%s interval_ms=%s",
        config.ohlcv_preview_enabled,
        config.ohlcv_preview_symbols,
        config.ohlcv_preview_tfs,
        config.ohlcv_preview_publish_interval_ms,
    )
    ok, reason = check_fxcm_environment(config)
    log.info(
        "FXCM backend=%s connection=%s host=%s sdk_ok=%s reason=%s",
        config.fxcm_backend,
        config.fxcm_connection,
        config.fxcm_host_url,
        str(ok).lower(),
        reason,
    )
    handles = build_runtime(config=config, fxcm_preview=args.fxcm_preview)

    log.info("Слухаю команди у %s", config.ch_commands())
    try:
        while True:
            if handles.replay_handle is not None and handles.replay_handle.error:
                raise SystemExit(handles.replay_handle.error)
            handles.status.publish_if_due(interval_ms=5000)
            time.sleep(0.1)
    except KeyboardInterrupt:
        log.info("Отримано KeyboardInterrupt — зупинка.")
    finally:
        stop_runtime(handles)


if __name__ == "__main__":
    main()
