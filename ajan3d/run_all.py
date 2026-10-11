"""Tek seferlik üretim: fotoğraf klasörü -> teslim paketi (ajans katmanı olmadan).

    python run_all.py "inbox\\musteri-x"
    python run_all.py "inbox\\musteri-x" --repackage      # yalnız sayfayı yeniden kur
    python run_all.py "inbox\\musteri-x" --rebuild-cad    # montajı yeniden kur
    python run_all.py "inbox\\musteri-x" --force          # düşük güvende de devam et

Zincirin kendisi `core/pipeline.py` içindedir; bu dosya yalnızca terminale
yazdırır. Ajans orkestratörü (`run_agency.py`) aynı zinciri sessizce kullanır.
"""
import argparse
import sys
import time
from pathlib import Path

from core.pipeline import PipelineError, resolve_job_dir, run_pipeline


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Fotoğraf klasöründen teknik 3D ürün sunumu üretir")
    parser.add_argument("folder", type=Path, help="Fotoğrafların bulunduğu klasör")
    parser.add_argument("--lang", default="tr", choices=["tr", "en"])
    parser.add_argument("--force", action="store_true",
                        help="Tanıma güveni düşük olsa da devam et")
    parser.add_argument("--new", action="store_true", help="Yeni iş dizini aç")
    parser.add_argument("--repackage", action="store_true",
                        help="Sunum sayfasını yeniden kur")
    parser.add_argument("--rebuild-cad", action="store_true",
                        help="CAD montajını yeniden kur (model.glb + cad.json)")
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()

    started = time.perf_counter()
    step = [0]

    def progress(message: str) -> None:
        if message.startswith("  "):
            print(f"      {message.strip()}")
        else:
            step[0] += 1
            print(f"\n[{step[0]}] {message}")

    try:
        result = run_pipeline(
            args.folder,
            job_dir=resolve_job_dir(args.folder, new=args.new),
            force=args.force,
            lang=args.lang,
            make_zip=not args.no_zip,
            repackage=args.repackage,
            rebuild_cad=args.rebuild_cad,
            on_progress=progress,
        )
    except PipelineError as e:
        print(f"\nHATA [{e.stage}]: {e}", file=sys.stderr)
        if e.retriable:
            print("Geçici görünüyor; birazdan tekrar deneyin.", file=sys.stderr)
        return 1

    print(f"\nTamamlandı ({time.perf_counter() - started:.1f} sn)")
    print(f"  Ürün   : {result.object_name}")
    print(f"  İş     : {result.job_dir}")
    print(f"  Paket  : {result.delivery_dir}")
    if result.zip_path:
        print(f"  ZIP    : {result.zip_path}")
    print(f"\n  Açmak için: {result.delivery_dir / 'index.html'}")
    print("  (Public link için: .\\baslat.ps1)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
