"""Yalnizca tanima adimi: fotograflar -> metadata.json (identity).

    python run_vision.py "inbox\musteri-x"
"""
import argparse
import sys
from pathlib import Path

from agents.vision_agent import VisionError, identify_folder, save_metadata
from core.pipeline import resolve_job_dir


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Urun tanima (Claude Vision)")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--new", action="store_true", help="Yeni is dizini ac")
    args = parser.parse_args()

    job_dir = resolve_job_dir(args.folder, new=args.new)
    try:
        result, info = identify_folder(args.folder)
    except (VisionError, FileNotFoundError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1

    path = save_metadata(job_dir, args.folder, result, info)
    print(f"{result.product_name}")
    print(f"  tip      : {result.type_designation}")
    print(f"  olcu     : {result.nominal_size or '-'} / {result.pressure_rating or '-'}")
    print(f"  malzeme  : {result.body_material or '-'}")
    print(f"  baglanti : {result.end_connection} · kumanda: {result.actuation}")
    print(f"  aile     : {result.family_hint}")
    print(f"  damgalar : {', '.join(result.markings) or '-'}")
    print(f"  guven    : {result.identification.confidence} "
          f"({'tamam' if result.identification.confident else 'DUSUK'})")
    for issue in result.identification.issues:
        print(f"    ! {issue}")
    print(f"\n  {len(info.analyzed_images)}/{info.total_images} fotograf · "
          f"{info.seconds} sn · ${info.cost_usd}")
    print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
