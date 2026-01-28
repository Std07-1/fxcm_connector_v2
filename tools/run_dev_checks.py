from __future__ import annotations

from tools.dev_checks import main


def _main() -> int:
    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
