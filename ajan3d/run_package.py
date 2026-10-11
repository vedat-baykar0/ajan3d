"""Yalnizca paketleme adimi: is dizini -> delivery klasoru (+ ZIP).

    python run_package.py "jobs\yeni-klasor-20261010-021030"
"""
import argparse
import sys
from pathlib import Path

from agents.packager_agent import PackagingError, build_package


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Sunum sayfasini ve paketi kurar")
    parser.add_argument("job", type=Path)
    parser.add_argument("--lang", default="tr", choices=["tr", "en"])
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()

    try:
        out = build_package(args.job, lang=args.lang, make_zip=not args.no_zip)
    except PackagingError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    print(f"Paket: {out}")
    print(f"Ac   : {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
