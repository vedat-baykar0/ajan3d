"""Public link için QR kodu.

Neden gerekli: akış "linki telefona gönder" üzerine kurulu. Panelde duran bir
QR kodu, linki kopyalayıp yapıştırmadan telefonla okutmayı sağlıyor — geçici
tünel adresleri uzun ve elle yazılamayacak kadar karmaşık.

Neden `segno`: QR kodlaması (Reed-Solomon, maske seçimi, sürüm/kapasite
tabloları) spesifikasyona bağlı, elle yazıldığında sessizce bozulabilen bir
iş. Bu proje için elle bir kodlayıcı yazılıp referans uygulamayla
karşılaştırıldı ve **uyuşmadı**; doğrulanamayan 300 satır yerine saf Python
ve **hiç geçişli bağımlılığı olmayan** `segno` kullanılıyor. Tek dosya SVG
çıktısı panele doğrudan gömülüyor, ek istek gerekmiyor.
"""
import io
from typing import Optional

QR_ERROR_LEVEL = "m"        # ~%15 hata toleransı: ekrandan okutmaya fazlasıyla yeter


def to_svg(text: str, scale: int = 5, border: int = 2,
           dark: str = "#111111", light: str = "#ffffff") -> Optional[str]:
    """QR kodunu satır içi SVG dizesi olarak döner. Üretilemezse None."""
    if not text:
        return None
    try:
        import segno
    except ImportError:
        return None
    try:
        code = segno.make(text, error=QR_ERROR_LEVEL)
        buf = io.BytesIO()
        code.save(buf, kind="svg", scale=scale, border=border,
                  dark=dark, light=light, xmldecl=False, svgns=True, nl=False)
        return buf.getvalue().decode("utf-8")
    except Exception:
        return None


def to_png(text: str, path, scale: int = 8, border: int = 2) -> bool:
    """QR kodunu PNG olarak diske yazar (ör. teslim paketine koymak için)."""
    if not text:
        return False
    try:
        import segno
        segno.make(text, error=QR_ERROR_LEVEL).save(
            str(path), kind="png", scale=scale, border=border)
        return True
    except Exception:
        return False
