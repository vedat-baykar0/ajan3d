"""Yalnizca CAD adimi: metadata.json -> model.glb + cad.json.

    python run_cad.py "jobs\yeni-klasor-20261010-021030"
    python run_cad.py <is-dizini> --force        # yeniden kur

Kutuphanedeki aileleri listelemek icin:
    python run_cad.py --families
"""
import argparse
import json
import sys
from pathlib import Path

from agents import cad_agent
from agents.cad_agent import CadError


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Parametrik CAD montaji kurar")
    parser.add_argument("job", type=Path, nargs="?", help="Is dizini")
    parser.add_argument("--force", action="store_true", help="Varsa yeniden kur")
    parser.add_argument("--families", action="store_true",
                        help="Kutuphanedeki aileleri listele ve cik")
    args = parser.parse_args()

    if args.families:
        from cad.library import catalog
        print(f"{'id':20s} {'kategori':18s} aile")
        for row in catalog():
            print(f"{row['id']:20s} {row['category']:18s} {row['label']}")
        return 0

    if args.job is None:
        parser.error("is dizini gerekli (ya da --families)")
    meta = args.job / "metadata.json"
    if not meta.exists():
        print(f"HATA: {meta} yok (once run_vision.py)", file=sys.stderr)
        return 1

    metadata = json.loads(meta.read_text(encoding="utf-8"))
    try:
        result = cad_agent.build(args.job, metadata, on_progress=print,
                                 force=args.force)
    except CadError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1

    print(f"\n  kaynak : {result.source}")
    print(f"  aile   : {result.family}")
    print(f"  parca  : {result.parts} ({result.instances} ornek)")
    print(f"  kutle  : {result.mass_g / 1000:.2f} kg")
    print(f"  olcu   : {' x '.join(f'{v:.0f}' for v in result.size_mm)} mm")
    print(f"  dosya  : {result.model_path} ({result.size_mb} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
