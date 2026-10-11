"""Ajans katmanı: bir müşteri işinin uçtan uca durumu.

Tek bir `run_all.py` çalıştırması kendi kendine yeterlidir; ama gözetimsiz
(otomatik) çalışan zincirde "bu iş nerede kaldı, kaç kez denendi, müşteriye
haber verildi mi" bilgisini tutmak gerekir. Bu dosya o durumu `<iş>\agency.json`
içinde taşır.

Neden ayrı dosya: `metadata.json` Vision'ın, `generation.json` 3D ajanının
çıktısı. Ajans durumu (müşteri e-postası, aşama, yayın linki, bildirim) bunlardan
bağımsızdır ve yeniden üretim yapılsa bile korunmalıdır.
"""
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

STATE_FILE = "agency.json"

# Sıralı aşamalar. Bir iş yalnızca ileri gider; hata halinde aşama korunur,
# last_error ve attempts güncellenir, böylece kaldığı yerden devam edilebilir.
RECEIVED = "RECEIVED"
PRODUCED = "PRODUCED"      # metadata + model.glb + teslim paketi hazır
DEPLOYED = "DEPLOYED"      # paket yayınlandı, public link var
NOTIFIED = "NOTIFIED"      # müşteriye haber verildi (iş bitti)
BLOCKED = "BLOCKED"        # el değmesi gerekiyor (ör. kalite reddi, kota bitti)
STAGES = (RECEIVED, PRODUCED, DEPLOYED, NOTIFIED, BLOCKED)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class AgencyJob:
    job_dir: str
    source_folder: str
    customer_email: str
    customer_name: str = ""
    subject: str = ""
    message_id: str = ""
    stage: str = RECEIVED
    attempts: int = 0
    last_error: str = ""
    # Kalıcı anahtar slug'dır; tam adres her gösterimde canlı tünelden
    # türetilir (`agents/deployer_agent.url_for`). public_url yalnızca son
    # bilinen adresin kaydı — ücretsiz tünelde yeniden başlatmadan sonra
    # geçersiz olabilir, bu yüzden ona güvenilmez.
    public_slug: str = ""
    public_url: str = ""
    embed_code: str = ""
    object_name: str = ""
    acknowledged: bool = False      # "fotoğraflarınızı aldık" gitti mi
    operator_alerted: bool = False  # tekrarlayan hatada operatöre haber gitti mi
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # --- kalıcılık ---

    @property
    def path(self) -> Path:
        return Path(self.job_dir) / STATE_FILE

    def save(self) -> None:
        self.updated_at = _now()
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, job_dir: Path) -> Optional["AgencyJob"]:
        p = Path(job_dir) / STATE_FILE
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    # --- durum geçişleri ---

    def advance(self, stage: str, **fields) -> None:
        self.stage = stage
        self.last_error = ""
        for k, v in fields.items():
            setattr(self, k, v)
        self.save()

    def fail(self, error: str, blocked: bool = False) -> None:
        self.attempts += 1
        self.last_error = error[:1000]
        if blocked:
            self.stage = BLOCKED
        self.save()

    @property
    def done(self) -> bool:
        return self.stage == NOTIFIED

    @property
    def slug(self) -> str:
        """Yayınlanmış paketin slug'ı.

        `public_slug` alanı sonradan eklendi; ondan önce açılmış işlerde
        yalnızca (artık geçersiz olabilen) tam adres var. Linkin yeniden
        üretilebilmesi için slug o adresten geri çıkarılır — yoksa eski
        işlerin paneldeki bağlantısı boş kalıyordu.
        """
        if self.public_slug:
            return self.public_slug
        url = (self.public_url or "").rstrip("/")
        marker = "/p/"
        if marker in url:
            return url.rsplit(marker, 1)[-1]
        return ""


def all_jobs(jobs_dir: Path) -> List[AgencyJob]:
    """Ajans tarafından açılmış tüm işler, en yenisi önce."""
    if not Path(jobs_dir).exists():
        return []
    jobs = [j for p in Path(jobs_dir).glob(f"*/{STATE_FILE}") if (j := AgencyJob.load(p.parent))]
    return sorted(jobs, key=lambda j: j.created_at, reverse=True)


def unfinished_jobs(jobs_dir: Path, max_attempts: int) -> List[AgencyJob]:
    """Tekrar denenmeye uygun işler: bitmemiş, engellenmemiş, deneme hakkı kalan."""
    return [
        j for j in all_jobs(jobs_dir)
        if not j.done and j.stage != BLOCKED and j.attempts < max_attempts
    ]
