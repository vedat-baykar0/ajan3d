"""GLB web optimizasyonu — Draco sıkıştırması (isteğe bağlı adım).

Parametrik montaj her parçası ayrı katı olan, dokusuz bir GLB üretir; boyutun
tamamı köşe ve indeks verisidir. Draco bu veriyi yaklaşık **onda birine**
indiriyor (ölçüldü: 994 KB → 121 KB). Karşılığında tarayıcının bir çözücü
indirmesi gerekiyor (~250 KB, wasm).

Bu yüzden sıkıştırma **eşiğe bağlı**: küçük bir modelde 250 KB'lık çözücüyü
indirmek net kayıptır. `DRACO_MIN_BYTES` altındaki modeller olduğu gibi
yayınlanır. Çözücü üstelik ürünler arasında önbelleğe alınıyor, yani ikinci
sunumdan itibaren kazanç tam.

**Bağımlılık isteğe bağlıdır.** Sıkıştırma Node tarafındaki
`tools/node/optimize_glb.mjs` ile yapılıyor (`@gltf-transform` + `draco3dgltf`).
Node yoksa, paketler kurulu değilse ya da bütünlük doğrulaması başarısız olursa
adım **sessizce atlanır** ve zincir sıkıştırılmamış modelle devam eder. Hiçbir
koşulda teslimi engellemez.

Bütünlük: sıkıştırılmış dosya geri okunup karşılaştırılmadan kabul edilmez —
düğüm sözleşmesi (pid/grp/ax/d/st), mesh sayısı, sınır kutuları ve üçgen
sayısı denetlenir. Ayrıntı `tools/node/optimize_glb.mjs` içinde.
"""
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.config import PROJECT_ROOT, settings

SCRIPT = PROJECT_ROOT / "tools" / "node" / "optimize_glb.mjs"
NODE_MODULES = PROJECT_ROOT / "tools" / "node" / "node_modules"
DECODER_DIR = PROJECT_ROOT / "vendor" / "draco"
# Tarayıcının indireceği Draco çözücüsü (wasm sarmalayıcı + wasm) ~250 KB.
DECODER_BYTES = 251_000
TIMEOUT = 180


@dataclass
class OptimizeResult:
    ok: bool
    path: Path                 # kullanılacak model (sıkışmadıysa özgün dosya)
    before: int
    after: int
    draco: bool
    reason: str = ""

    @property
    def saved_pct(self) -> int:
        if not self.before or self.after >= self.before:
            return 0
        return round((1 - self.after / self.before) * 100)


def node_binary() -> Optional[str]:
    return shutil.which("node")


def available() -> bool:
    """Sıkıştırma zinciri kurulu mu (Node + paketler + çözücü)."""
    return bool(node_binary()) and SCRIPT.exists() and NODE_MODULES.exists() \
        and (DECODER_DIR / "draco_decoder.wasm").exists()


def worth_it(size: int) -> bool:
    """Sıkıştırma bu boyutta kazanç sağlıyor mu.

    Çözücü indirme maliyeti sabit; model küçükse sıkıştırma toplam indirmeyi
    ARTIRIR. Ölçülen sıkışma oranı ~%88 olduğundan, kazanç ancak
    `0.12 * size + çözücü < size` olduğunda doğar.
    """
    return size >= settings.draco_min_bytes


def optimize(source: Path, target: Path,
             on_progress=lambda m: None) -> OptimizeResult:
    """`source` GLB'sini web için sıkıştırır. Başarısızlıkta özgün dosyaya düşer."""
    source = Path(source)
    before = source.stat().st_size

    if not settings.draco_enabled:
        return OptimizeResult(False, source, before, before, False, "kapalı")
    if not worth_it(before):
        return OptimizeResult(
            False, source, before, before, False,
            f"model zaten küçük ({before / 1024:.0f} KB); çözücü indirmek "
            f"({DECODER_BYTES / 1024:.0f} KB) net kayıp olurdu")
    if not available():
        return OptimizeResult(
            False, source, before, before, False,
            "Node/gltf-transform kurulu değil (tools/node)")

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [node_binary(), str(SCRIPT), str(source), str(target)],
            capture_output=True, text=True, timeout=TIMEOUT,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32" else 0)
    except (OSError, subprocess.SubprocessError) as e:
        return OptimizeResult(False, source, before, before, False,
                              f"{type(e).__name__}: {str(e)[:120]}")

    try:
        report = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        detail = (completed.stderr or completed.stdout or "").strip()[:140]
        return OptimizeResult(False, source, before, before, False,
                              f"çıktı okunamadı: {detail}")

    if not report.get("ok"):
        return OptimizeResult(False, source, before, before, False,
                              str(report.get("error", "bilinmeyen hata"))[:160])

    after = int(report.get("after", target.stat().st_size))
    # Çözücü maliyetiyle birlikte hâlâ kazanç var mı? Yoksa özgün dosya.
    if after + DECODER_BYTES >= before:
        target.unlink(missing_ok=True)
        return OptimizeResult(False, source, before, before, False,
                              "sıkıştırma çözücü maliyetini karşılamadı")

    on_progress(f"Draco: {before / 1024:.0f} KB -> {after / 1024:.0f} KB "
                f"(%{report.get('saved_pct', 0)} küçüldü, "
                f"{report.get('meshes', 0)} mesh, sözleşme korundu)")
    return OptimizeResult(True, target, before, after, True)


def copy_decoder(dest_dir: Path) -> bool:
    """Draco çözücüsünü teslim paketine kopyalar (internetsiz de açılsın)."""
    if not (DECODER_DIR / "draco_decoder.wasm").exists():
        return False
    dest = Path(dest_dir) / "vendor" / "draco"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("draco_wasm_wrapper.js", "draco_decoder.wasm"):
        src = DECODER_DIR / name
        if src.exists():
            shutil.copy2(src, dest / name)
    return (dest / "draco_decoder.wasm").exists()
