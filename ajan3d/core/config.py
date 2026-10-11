"""Ortam değişkenlerinden okunan ayarlar (.env dosyası desteklenir)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# $ / 1M token (girdi, çıktı) — Anthropic fiyatları. ÜCRETSİZ KATMAN YOKTUR.
MODEL_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

# Web arama sunucu aracının ilan edilen ücreti: $10 / 1000 arama.
WEB_SEARCH_COST_PER_USE = 0.01


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on", "evet")


def _secret(name: str, default: str = "") -> object:
    """Sirlar `repr` disinda tutulur.

    Settings donmus bir dataclass oldugu icin testler onu `dataclasses.replace`
    ile kopyaliyor; bir hata aninda pytest nesnenin tam `repr`ini basiyordu ve
    API anahtari ile SMTP sifresi gunluge dusuyordu (yasandi). `repr=False`
    degeri kullanilabilir birakir, yalnizca yazdirilmasini engeller.
    """
    return field(default=os.getenv(name, default), repr=False)


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str = _secret("ANTHROPIC_API_KEY")
    output_language: str = os.getenv("OUTPUT_LANGUAGE", "Türkçe")

    # --- 1. Tanıma ajanı (Vision) ---
    # Fotoğraf YALNIZCA ürünü tanımak için kullanılır; geometri üretilmez.
    vision_model: str = os.getenv("VISION_MODEL", "claude-sonnet-5-5")
    vision_effort: str = os.getenv("VISION_EFFORT", "low")
    # Tanima adiminda Claude Vision'a gonderilen kare sayisi. 3 kare
    # urunu tanimaya yetiyor ama AYRINTIYA yetmiyor: musterinin sekiz
    # fotografinda pabucun kare ve 8 delikli oldugu yalnizca tepeden
    # cekilen karede goruluyor ve o kare ilk uc temsilcinin arasinda
    # degildi. Gorsel token maliyeti kare basina ~1300 token; 6 kare
    # hala ucuz, karsiliginda geometri dogru kuruluyor.
    vision_max_images: int = int(os.getenv("VISION_MAX_IMAGES", "6"))
    vision_max_side: int = int(os.getenv("VISION_MAX_SIDE", "1280"))
    # Tanıma güveni düşükse iş operatöre bırakılır (true ile otomatik devam).
    force_low_confidence: bool = _flag("FORCE_LOW_CONFIDENCE", "false")

    # --- 2. Teknik veri ajanı (web_search) — ÜCRETLİ, kapatılabilir ---
    spec_enabled: bool = _flag("SPEC_ENABLED", "true")
    spec_model: str = os.getenv("SPEC_MODEL", "claude-sonnet-5-5")
    spec_effort: str = os.getenv("SPEC_EFFORT", "low")
    spec_max_searches: int = int(os.getenv("SPEC_MAX_SEARCHES", "4"))

    # --- 3. CAD edinme ---
    # Kaynak sırası: local (cad_library/), remote (CAD_API_URL), parametric.
    cad_sources: str = os.getenv("CAD_SOURCES", "local,parametric")
    # Uzak katalog sözleşmesi: {query} aranan ifadeyle değiştirilir, yanıtın
    # içinde .glb bağlantısı aranır. Boşsa uzak kaynak hiç denenmez.
    cad_api_url: str = os.getenv("CAD_API_URL", "")
    cad_api_token: str = _secret("CAD_API_TOKEN")
    cad_api_timeout: float = float(os.getenv("CAD_API_TIMEOUT", "25"))

    # --- 4. Web optimizasyonu (Draco) ---
    # Parametrik montaj dokusuz; boyutun tamami kose/indeks verisi oldugu icin
    # Draco ~%88 kazandiriyor. Karsiliginda tarayici ~250 KB cozucu indiriyor,
    # bu yuzden esigin altindaki modeller sikistirilmaz (net kayip olurdu).
    draco_enabled: bool = _flag("DRACO_ENABLED", "true")
    draco_min_bytes: int = int(os.getenv("DRACO_MIN_BYTES", "400000"))

    # --- 5. Sunum ---
    hdri_enabled: bool = _flag("HDRI_ENABLED", "true")
    hdri_width: int = int(os.getenv("HDRI_WIDTH", "1024"))
    # Sağ paneldeki orijinal fotoğrafın uzun kenarı (px).
    photo_max_side: int = int(os.getenv("PHOTO_MAX_SIDE", "1100"))
    # Fotoğraf projeksiyonu (LookDev). Kapatılırsa sayfa saf PBR ile çalışır.
    #
    # VARSAYILAN KAPALI. Çok görüşlü projeksiyon ürünü OLDUĞUNDAN KÖTÜ
    # gösteriyordu: müşterinin 8 karesi sıcak iç mekân ışığında, koyu fon
    # önünde ve kare başına farklı beyaz ayarıyla çekilmiş. Ağırlıklı
    # ortalama alınınca paslanmaz gövde hardal/haki lekelere dönüyor, bir
    # yanı gümüş bir yanı sarı kalıyor ("çamur"). Doğru beyaz ayarı ve
    # kareler arası pozlama eşitlemesi olmadan harmanlama bunu düzeltmiyor.
    # Fotoğrafın tek başına taşıdığı bilgi (damga yazısı) ürünün genel
    # izlenimini bozmaya değmiyor; saf PBR paslanmaz hem daha doğru hem
    # daha temiz. Fotoğraflar sağ panelde ZATEN tam çözünürlükte duruyor.
    projection_enabled: bool = _flag("PROJECTION_ENABLED", "false")
    # Örtüşme eşiği: model fotoğrafla bu kadar bile çakışmıyorsa doku yapıştırmak
    # ürünü tanınmaz hale getirir — projeksiyonu hiç açmamak daha dürüst.
    projection_min_iou: float = float(os.getenv("PROJECTION_MIN_IOU", "0.55"))

    jobs_dir: Path = Path(os.getenv("JOBS_DIR", str(PROJECT_ROOT / "jobs")))

    # --- Ajans katmanı (run_agency.py) ---
    inbox_dir: Path = Path(os.getenv("INBOX_DIR", str(PROJECT_ROOT / "inbox")))
    public_dir: Path = Path(os.getenv("PUBLIC_DIR", str(PROJECT_ROOT / "public")))
    log_dir: Path = Path(os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs")))
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "")
    agency_host: str = os.getenv("AGENCY_HOST", "127.0.0.1")
    agency_port: int = int(os.getenv("AGENCY_PORT", "8000"))
    # Paketlerin yayınlandığı AYRI port. Tünel yalnızca bunu açar; yönetim
    # paneli (iş adları, müşteri klasörleri, hatalar) dışarı sızmaz.
    publish_host: str = os.getenv("PUBLISH_HOST", "127.0.0.1")
    publish_port: int = int(os.getenv("PUBLISH_PORT", "8001"))
    agency_lang: str = os.getenv("AGENCY_LANG", "tr")
    agency_max_attempts: int = int(os.getenv("AGENCY_MAX_ATTEMPTS", "4"))
    agency_retry_seconds: int = int(os.getenv("AGENCY_RETRY_SECONDS", "1800"))
    agency_settle_seconds: float = float(os.getenv("AGENCY_SETTLE_SECONDS", "5"))
    agency_scan_seconds: float = float(os.getenv("AGENCY_SCAN_SECONDS", "10"))

    # --- Public link (tünel) ---
    # cloudflared: ücretsiz, hesap gerekmez, her başlatmada adres değişir.
    # ngrok: hesap + authtoken ister, ücretsiz katmanda da adres değişir.
    tunnel_provider: str = os.getenv("TUNNEL_PROVIDER", "cloudflared").strip().lower()
    tunnel_enabled: bool = _flag("TUNNEL_ENABLED", "true")
    cloudflared_path: str = os.getenv("CLOUDFLARED_PATH", "")
    ngrok_path: str = os.getenv("NGROK_PATH", "")
    ngrok_authtoken: str = _secret("NGROK_AUTHTOKEN")
    # Kalıcı bir alan adınız/tüneliniz varsa buraya yazın; o zaman geçici
    # trycloudflare adresi yerine bu kullanılır ve link hiç değişmez.
    tunnel_hostname: str = os.getenv("TUNNEL_HOSTNAME", "")
    tunnel_start_timeout: float = float(os.getenv("TUNNEL_START_TIMEOUT", "45"))

    # --- Bildirim (SMTP) — TAMAMEN İSTEĞE BAĞLI, boş kalabilir ---
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "465"))
    smtp_user: str = _secret("SMTP_USER")
    smtp_password: str = _secret("SMTP_PASSWORD")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    operator_email: str = os.getenv("OPERATOR_EMAIL", "")

    @property
    def local_publish_url(self) -> str:
        return f"http://{self.publish_host}:{self.publish_port}"


settings = Settings()
