"""0. Alıcı Ajan — `inbox\\` klasörünü izler.

Çalışma şekli: `inbox\\` altına
  - bir klasör atılır (ör. `inbox\\cafe-x-hamburger\\`), veya
  - doğrudan fotoğraflar bırakılır (ajan bunları tek klasörde toplar),
ajan bunu algılar ve iş adayı döner.

E-posta (IMAP) yolu kaldırıldı: Gmail uygulama şifresi/güvenlik ayarları
gereksiz sürtünme yaratıyordu. Klasör izleme hiçbir kimlik bilgisi, port veya
dış servis istemez.

İki koruma:
  - **Kararlılık kontrolü:** kopyalanması bitmemiş dosyalar işlenmez; bir dosya
    en az `settle` saniye boyunca değişmemiş olmalı. Yarım kopyalanmış JPEG'le
    üretime girmek baştan bozuk model demektir.
  - **İşaret dosyası:** kuyruğa alınan klasöre `.ajan3d-job.json` yazılır.
    Servis yeniden başlasa da aynı klasör ikinci kez işlenmez.
"""
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.config import settings
from core.images import IMAGE_EXTS

MARKER = ".ajan3d-job.json"
LOOSE_PREFIX = "elle"
# İşaretlenmiş ama iş kaydı açılmamış bir klasör bu kadar süre sonra "takılmış"
# sayılır ve yeniden kuyruğa alınır. İşaret ile iş kaydı arasındaki normal
# gecikme saniyenin altında; bu pay yalnızca yarış durumunu kapatıyor.
STALE_CLAIM_SECONDS = 120.0
# Alt çizgi/nokta ile başlayan klasörler ajansın kendi kullanımına ayrıldı.
IGNORED_PREFIXES = ("_", ".")


@dataclass
class Intake:
    """Bir fotoğraf klasöründen çıkan iş adayı."""
    folder: Path
    image_count: int
    customer_name: str = ""
    customer_email: str = ""     # klasör akışında boş; ileride kanal eklenirse dolar
    subject: str = ""
    message_id: str = ""


def _images(folder: Path) -> List[Path]:
    try:
        return sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        )
    except OSError:
        return []


# {dosya yolu: (son görülen boyut, o boyutun ilk görüldüğü an)}
_sizes: dict = {}


def _stable(path: Path, settle: float) -> bool:
    """Dosyanın kopyalanması bitti mi.

    mtime'a bakmak işe yaramıyor: Windows Explorer kopyalaması da `shutil.copy2`
    da kaynak dosyanın mtime'ını korur, yani yarım kopyalanmış bir fotoğraf
    "eski" görünüp anında kararlı sayılır. Bu yüzden boyut takip edilir: dosya
    en az `settle` saniye boyunca aynı boyutta kalmalı. Bu, dosyanın en az iki
    taramada görülmesi anlamına gelir.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size == 0:
        return False

    now = time.monotonic()
    previous = _sizes.get(path)
    if previous is None or previous[0] != size:
        _sizes[path] = (size, now)      # ilk görülüş ya da hâlâ büyüyor
        return False
    if now - previous[1] < settle:
        return False
    return _readable(path)


def _readable(path: Path) -> bool:
    """Dosya başka bir süreç tarafından kilitli değil mi (ek güvence)."""
    try:
        with path.open("rb") as f:
            return bool(f.read(1))
    except OSError:
        return False


def _forget_missing(seen: set) -> None:
    """Artık var olmayan dosyaları takip tablosundan düşür (sınırsız büyümesin)."""
    for path in [p for p in _sizes if p not in seen]:
        _sizes.pop(path, None)


def _ignored(folder: Path) -> bool:
    return folder.name.startswith(IGNORED_PREFIXES)


def marker_path(folder: Path) -> Path:
    return Path(folder) / MARKER


def is_claimed(folder: Path) -> bool:
    """Klasör gerçekten kuyruğa alınmış mı.

    İşaret dosyasının varlığı tek başına yetmiyor. Servis klasörü
    işaretledikten **sonra** ama iş kaydını açmadan **önce** kapanırsa
    (yeniden başlatma, çökme, Ctrl+C) klasör sonsuza kadar atlanıyor: işaret
    "kuyrukta" diyor ama kuyrukta kimse yok, iş dizini de hiç oluşmamış.
    Gözetimsiz çalışan bir sistemde bu, sessizce kaybolan müşteri işi demek
    (yaşandı: servis yeniden başlatılırken işaretlenmiş klasör bir daha
    alınmadı).

    Bu yüzden işaretin gösterdiği iş dizininde gerçek bir iş kaydı aranıyor.
    Henüz kaydı açılmamış **taze** işaretler korunuyor, yoksa normal çalışmada
    aynı klasör işçi onu devralmadan ikinci kez kuyruğa girerdi.
    """
    marker = marker_path(folder)
    if not marker.exists():
        return False
    job_dir = claimed_job_dir(folder)
    if job_dir and (Path(job_dir) / "agency.json").exists():
        return True
    try:
        return (time.time() - marker.stat().st_mtime) < STALE_CLAIM_SECONDS
    except OSError:
        return False


def claim(folder: Path, job_dir: Path) -> None:
    """Klasörü kuyruğa alındı olarak işaretler (yeniden başlatmaya dayanıklı)."""
    marker_path(folder).write_text(json.dumps({
        "job_dir": str(job_dir),
        "queued_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def claimed_job_dir(folder: Path) -> Optional[Path]:
    p = marker_path(folder)
    if not p.exists():
        return None
    try:
        return Path(json.loads(p.read_text(encoding="utf-8"))["job_dir"])
    except (OSError, ValueError, KeyError):
        return None


def intake_from_folder(folder: Path) -> Intake:
    folder = Path(folder)
    return Intake(
        folder=folder,
        image_count=len(_images(folder)),
        customer_name=folder.name,
        subject=f"Klasör: {folder.name}",
        message_id=f"folder:{folder.resolve()}",
    )


def _collect_loose(inbox: Path, settle: float) -> Optional[Path]:
    """`inbox\\` köküne doğrudan bırakılan fotoğrafları yeni bir klasöre taşır.

    Hepsi kararlı olana kadar bekler; yarım bırakılmış bir seçimi bölmemek için
    dosyaların bir kısmı hâlâ kopyalanıyorsa hiçbiri taşınmaz.
    """
    loose = _images(inbox)
    if not loose:
        return None
    if not all([_stable(p, settle) for p in loose]):
        return None

    target = inbox / f"{LOOSE_PREFIX}-{datetime.now():%Y%m%d-%H%M%S}"
    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    for src in loose:
        dest = target / src.name
        try:
            src.replace(dest)
        except OSError:
            continue
        # Kararlılık kaydını yeni yola taşı: dosya zaten kararlı olduğu
        # doğrulandı, taşınma yüzünden bir tarama daha beklemesin.
        if src in _sizes:
            _sizes[dest] = _sizes.pop(src)
        moved += 1
    if moved == 0:
        target.rmdir()
        return None
    return target


def scan_inbox(settle: Optional[float] = None) -> List[Intake]:
    """`inbox\\` içindeki işlenmeye hazır klasörleri döner (idempotent).

    Hem watchdog olayından hem de periyodik taramadan çağrılır; aynı klasörü
    iki kez döndürmez çünkü döndürdüğü klasörü çağıran taraf `claim()` ile
    işaretler.
    """
    settle = settings.agency_settle_seconds if settle is None else settle
    inbox = settings.inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)

    _collect_loose(inbox, settle)

    ready: List[Intake] = []
    seen: set = set()
    for folder in sorted(p for p in inbox.iterdir() if p.is_dir()):
        if _ignored(folder) or is_claimed(folder):
            continue
        images = _images(folder)
        seen.update(images)
        if not images:
            continue
        # all() yerine liste: her dosyanın boyutu kaydedilsin, ilk kararsızda durmasın
        if not all([_stable(p, settle) for p in images]):
            continue        # kopyalama sürüyor; sonraki taramada alınır
        ready.append(intake_from_folder(folder))
    _forget_missing(seen | set(_images(inbox)))
    return ready
