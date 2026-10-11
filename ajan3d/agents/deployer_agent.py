"""4. Yayın Ajanı — teslim paketini kendi sunucunuzda yayınlar.

Seçilen model: paket sizin kontrolünüzdeki `public\\` dizinine kopyalanır,
`run_agency.py` içindeki yayın sunucusu bunu statik olarak servis eder.
Müşteriden FTP, WordPress veya Shopify kimlik bilgisi istenmez; müşteri
yalnızca verilen linki açar ya da iframe kodunu sitesine yapıştırır.

Neden böyle: müşteri kimlik bilgisi toplamak hem en büyük sürtünme hem de en
büyük sorumluluk. Kendi alanınızda yayınlamak tek seferlik kurulumla her müşteri
için çalışır ve WordPress/Shopify/statik site ayrımını ortadan kaldırır.

**Link artık dondurulmuyor.** Ücretsiz tünel adresleri her başlatmada değişiyor;
eskiden tam URL `published.json` ve `agency.json` içine yazıldığı için servis
yeniden başladığında panelde duran bütün linkler ölüyordu. Şimdi kalıcı olan
tek şey `slug`; tam adres her gösterimde `core/tunnel.public_base_url()`
üzerinden canlı tünelden türetiliyor (`url_for()`).
"""
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import settings
from core.jobs import slugify
from core.tunnel import public_base_url

INDEX_FILE = "index.html"
MANIFEST_FILE = "published.json"
# Web yayınında taşınmayan dosyalar.
#
# `model-data.js` modelin base64 gömülü kopyasıdır ve YALNIZCA paket klasörüne
# çift tıklanarak (`file://`) açıldığında kullanılır — sunum sayfası
# `location.protocol === "file:"` kontrolüyle buna karar verir. HTTP üzerinden
# hiç istenmediği hâlde yayınlanırsa boşuna yer kaplar: ölçümde paket 27,3 MB
# yerine 12,0 MB'a düştü. Telefonda ilk açılış süresi doğrudan buna bağlı.
WEB_EXCLUDED = ("model-data.js",)


class DeployError(RuntimeError):
    pass


@dataclass
class Deployment:
    slug: str
    public_url: str
    embed_code: str
    path: Path
    size_mb: float


def url_for(slug: str) -> str:
    """Bir paketin güncel public adresi. Tünel adresi değişse de doğru kalır."""
    return f"{public_base_url().rstrip('/')}/p/{slug}/"


def is_live(slug: str) -> bool:
    """Paket gerçekten yayında mı.

    Panelde yalnızca açılan linkler gösterilsin diye var: yayından kaldırılmış
    ya da public dizini temizlenmiş bir paketin linki 404 verir, operatör de
    onu farkında olmadan müşteriye gönderebilir.
    """
    return bool(slug) and (settings.public_dir / slug / INDEX_FILE).exists()


def _iframe(url: str, title: str) -> str:
    """Müşterinin sitesine yapıştıracağı gömme kodu."""
    safe_title = title.replace('"', "'")
    return (
        f'<iframe src="{url}" title="{safe_title} - 3D"\n'
        f'        style="width:100%;aspect-ratio:16/10;border:0;border-radius:14px"\n'
        f'        loading="lazy" allow="xr-spatial-tracking; fullscreen; camera"\n'
        f'        allowfullscreen></iframe>'
    )


def embed_for(slug: str, title: str) -> str:
    return _iframe(url_for(slug), title or slug)


def _dir_size_mb(path: Path) -> float:
    return round(sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1_048_576, 2)


def _unique_slug(base: str) -> str:
    """Aynı ürün tekrar yayınlanırsa eskisini ezmemek için tarih eklenir."""
    return f"{slugify(base, 'urun')}-{datetime.now():%Y%m%d-%H%M%S}"


def deploy(delivery_dir: Path, object_name: str, customer_email: str = "") -> Deployment:
    """Teslim paketini public dizine kopyalar ve erişim bilgilerini döner."""
    delivery_dir = Path(delivery_dir)
    if not (delivery_dir / INDEX_FILE).exists():
        raise DeployError(f"{delivery_dir} içinde {INDEX_FILE} yok; paket eksik görünüyor")

    slug = _unique_slug(object_name or delivery_dir.name)
    target = settings.public_dir / slug
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # ZIP paketin içinde değil, kardeşi; yalnızca klasör yayınlanır.
    # Çevrimdışı gömülü kopya web'de kullanılmadığı için taşınmaz (bkz. WEB_EXCLUDED).
    shutil.copytree(delivery_dir, target, ignore=shutil.ignore_patterns(*WEB_EXCLUDED))

    url = url_for(slug)
    deployment = Deployment(
        slug=slug,
        public_url=url,
        embed_code=_iframe(url, object_name or slug),
        path=target,
        size_mb=_dir_size_mb(target),
    )

    # Manifest'te tam URL TUTULMAZ (tünel adresi değişir); slug kalıcı anahtar.
    (target / MANIFEST_FILE).write_text(json.dumps({
        "slug": slug,
        "object_name": object_name,
        "customer_email": customer_email,
        "source": str(delivery_dir),
        "published_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "size_mb": deployment.size_mb,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return deployment


def unpublish(slug: str) -> bool:
    """Yayından kaldırır (müşteri isterse). Silinen bir şey varsa True."""
    target = settings.public_dir / slug
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def published() -> list:
    """Yayındaki tüm paketlerin manifest kayıtları, en yenisi önce.

    `public_url` her okumada güncel tünelden yeniden üretilir.
    """
    root = settings.public_dir
    if not root.exists():
        return []
    items = []
    for manifest in root.glob(f"*/{MANIFEST_FILE}"):
        try:
            record = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slug = record.get("slug") or manifest.parent.name
        record["slug"] = slug
        record["public_url"] = url_for(slug)
        items.append(record)
    return sorted(items, key=lambda d: d.get("published_at", ""), reverse=True)


def write_result_file(folder: Path, object_name: str, public_url: str,
                      embed_code: str) -> Path:
    """Sonucu fotoğrafların bırakıldığı klasöre yazar.

    E-posta akışı yok; kullanıcı sonucu fotoğrafları attığı yerde görsün diye
    link ve gömme kodu düz metin olarak oraya bırakılır.
    """
    out = Path(folder) / "3D_SONUC.txt"
    lines = [
        f"{object_name} — 3D sunumunuz hazır",
        "=" * 56,
        "",
        "MÜŞTERİYE GÖNDERİLECEK LİNK (WhatsApp'a yapıştırabilirsiniz):",
        f"  {public_url}",
        "",
        "Telefondan tek dokunuşla açılır. Sayfada:",
        "  · parçaları ayırıp birleştirme (patlatılmış görünüm)",
        "  · otomatik kamera turu",
        "  · numaralı detay noktaları ve teknik özellikler",
        "  · 'Odanda gör' (AR) — destekleyen telefonlarda",
        "",
        "Web sitesine eklemek için bu kodu sayfaya yapıştırın",
        "(WordPress: 'Custom HTML' bloğu, Shopify: HTML görünümü):",
        "",
        embed_code,
        "",
        "NOT: Bu link, sisteminiz açık olduğu sürece çalışır. Ücretsiz tünel",
        "adresi her yeniden başlatmada değişir; kalıcı adres için .env içindeki",
        "TUNNEL_HOSTNAME ayarına kendi alan adınızı yazabilirsiniz.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
