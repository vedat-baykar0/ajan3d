"""5. Bildirim Ajanı — müşteriye ve operatöre e-posta gönderir.

Üç mesaj tipi:
  - `send_ack`      : "fotoğraflarınızı aldık" (işi alır almaz, beklenti yönetimi)
  - `send_success`  : public link + siteye yapıştırılacak iframe kodu
  - `send_operator_alert` : tekrarlayan hatada SİZE gider, müşteriye gitmez

Tasarım kuralı: **müşteriye asla hata gönderilmez.** Gözetimsiz bir zincirde
hata mesajı müşteriye giderse hem profesyonellik kaybı hem gereksiz panik olur.
Hatalar operatöre gider, müşteri yalnızca sonucu görür.

SMTP ayarı yoksa ajan sessizce "gönderilmedi" döner (False) ve zinciri kırmaz;
iş `agency.json` içinde NOTIFIED olmadığı için sonra tekrar denenir.
"""
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

from core.config import settings


class NotifyError(RuntimeError):
    pass


def _configured() -> bool:
    return bool(
        settings.smtp_host
        and settings.smtp_user
        and settings.smtp_password
        and not settings.smtp_password.endswith("...")
    )


def _send(to: str, subject: str, body: str) -> bool:
    """Tek bir e-posta gönderir. Ayar yoksa False döner, hata fırlatmaz."""
    if not _configured():
        return False
    if not to or "@" not in to:
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                  context=ssl.create_default_context(), timeout=30) as s:
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise NotifyError(
            f"SMTP girişi reddedildi: {e}. Gmail'de normal şifre değil "
            f"'uygulama şifresi' gerekir."
        ) from e
    except (smtplib.SMTPException, OSError) as e:
        raise NotifyError(f"E-posta gönderilemedi: {e}") from e
    return True


def send_ack(to: str, customer_name: str, image_count: int) -> bool:
    name = customer_name or "Merhaba"
    body = (
        f"{name},\n\n"
        f"{image_count} fotoğrafınızı aldık. Ürününüzün etkileşimli 3D modelini "
        f"hazırlamaya başladık.\n"
        f"Hazır olduğunda size linki içeren bir e-posta göndereceğiz.\n\n"
        f"İyi çalışmalar."
    )
    return _send(to, "Fotoğraflarınızı aldık — 3D modeliniz hazırlanıyor", body)


def send_success(to: str, customer_name: str, object_name: str,
                 public_url: str, embed_code: str) -> bool:
    name = customer_name or "Merhaba"
    body = (
        f"{name},\n\n"
        f"\"{object_name}\" için etkileşimli 3D modeliniz hazır ve yayında:\n\n"
        f"  {public_url}\n\n"
        f"Modeli kendi web sitenize eklemek için aşağıdaki kodu sayfanıza yapıştırmanız "
        f"yeterli (WordPress'te 'Custom HTML' bloğu, Shopify'da ürün açıklaması "
        f"HTML görünümü):\n\n"
        f"{embed_code}\n\n"
        f"Model mobilde de çalışır; ziyaretçiler parçalara dokunarak detayları görebilir.\n\n"
        f"İyi çalışmalar."
    )
    return _send(to, f"3D modeliniz hazır: {object_name}", body)


def send_operator_alert(subject: str, detail: str, job_dir: Optional[str] = None) -> bool:
    """Hata/engel bildirimi — yalnızca operatöre."""
    to = settings.operator_email or settings.smtp_user
    body = f"{detail}\n"
    if job_dir:
        body += f"\nİş dizini: {job_dir}\n"
    body += "\nBu mesaj müşteriye gönderilmedi."
    return _send(to, f"[ajan3d] {subject}", body)
