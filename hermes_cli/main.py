"""Console-script entry point."""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    from cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
