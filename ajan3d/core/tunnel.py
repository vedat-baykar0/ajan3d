"""Public link: yerel yayın sunucusunu internete açan tünel yöneticisi.

Neden gerekli: paketler `public\\` altında 127.0.0.1 üzerinden servis edilir.
Müşteriye WhatsApp'tan link atmak için bu adresin internetten erişilebilir
olması gerekir. Tünel, dışa açık bir HTTPS adresini yerel porta bağlar.

Sağlayıcılar:
  - **cloudflared** (varsayılan): hesap gerekmez, `trycloudflare.com` altında
    rastgele bir adres verir. Proje içinde `tools\\bin\\cloudflared.exe` hazır.
  - **ngrok**: hesap + authtoken ister; kurulu ve ayarlıysa kullanılabilir.

Üç tasarım kararı:

1. **Tünel yalnızca yayın portuna bağlanır (varsayılan 8001), yönetim paneline
   değil.** Önceki kurulumda tünel 8000 portunun tamamını açıyordu; `/p/...`
   paketlerinin yanında iş adları, müşteri klasör yolları ve hata mesajları da
   dışarıdan görünüyordu. Ayrı port bu sızıntıyı mimari olarak kapatır.

2. **Süreç gözetlenir ve ölürse yeniden başlatılır.** Ücretsiz tüneller
   kopabiliyor; gözetmen olmadan sistem sessizce link verir ama link ölüdür.
   Yeni adres `current_url()` üzerinden anında yayılır.

3. **Adres tek yerden okunur.** Geçici tünel adresleri her başlatmada değişir,
   bu yüzden link hiçbir yere kalıcı yazılmaz; `published.json` yalnızca slug
   tutar, tam URL her gösterimde güncel tünelden türetilir.
"""
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from core.config import PROJECT_ROOT, settings

BUNDLED_CLOUDFLARED = PROJECT_ROOT / "tools" / "bin" / "cloudflared.exe"
# `api.` KASITLI olarak dışlanıyor: cloudflared kayıt olurken günlüğe
# `url=https://api.trycloudflare.com/tunnel` yazıyor ve bu satır tünel
# adresiyle aynı kalıba uyuyor. Yaşandı — kayıt birkaç kez başarısız olurken
# sistem bu adresi "PUBLIC LINK HAZIR" diye ilan etti; müşteriye gidecek link
# hiçbir yere gitmiyordu. Aynı tuzak ngrok'un api adresinde de var.
CLOUDFLARED_URL_RE = re.compile(r"https://(?!api\.)[-a-z0-9]+\.trycloudflare\.com")
NGROK_URL_RE = re.compile(r"https://(?!api\.)[-a-z0-9]+\.ngrok[-.][-a-z0-9.]*\w")
# Süreç ölürse yeniden başlatma bekleme süreleri (saniye) — artan geri çekilme.
RESTART_BACKOFF = (3, 5, 10, 20, 30, 60)
DOWNLOAD_HINT = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)


class TunnelError(RuntimeError):
    pass


@dataclass
class TunnelStatus:
    provider: str
    url: str
    running: bool
    restarts: int
    last_error: str


def _resolve_binary(configured: str, bundled: Optional[Path], names: List[str]) -> Optional[Path]:
    """Ayarda verilen yol -> proje içindeki kopya -> PATH sırasıyla arar."""
    if configured:
        p = Path(configured)
        return p if p.exists() else None
    if bundled is not None and bundled.exists():
        return bundled
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def cloudflared_binary() -> Optional[Path]:
    return _resolve_binary(settings.cloudflared_path, BUNDLED_CLOUDFLARED, ["cloudflared"])


def ngrok_binary() -> Optional[Path]:
    return _resolve_binary(settings.ngrok_path, None, ["ngrok"])


def available_providers() -> List[str]:
    out = []
    if cloudflared_binary():
        out.append("cloudflared")
    if ngrok_binary():
        out.append("ngrok")
    return out


class Tunnel:
    """Tünel sürecini başlatır, adresini okur ve ölürse yeniden başlatır.

    Thread güvenli: `current_url()` ve `status()` herhangi bir iş parçacığından
    çağrılabilir (yayın ajanı, panel, işçi).
    """

    def __init__(self, port: int, provider: str = "", log: Callable[[str], None] = print):
        self.port = port
        self.provider = (provider or settings.tunnel_provider or "cloudflared").lower()
        self.log = log
        self._url = ""
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._restarts = 0
        self._last_error = ""

    # --- dışa açık okuma ---

    def current_url(self) -> str:
        with self._lock:
            return self._url

    def status(self) -> TunnelStatus:
        with self._lock:
            return TunnelStatus(
                provider=self.provider,
                url=self._url,
                running=bool(self._proc and self._proc.poll() is None),
                restarts=self._restarts,
                last_error=self._last_error,
            )

    def wait_ready(self, timeout: Optional[float] = None) -> str:
        """İlk adres gelene kadar bekler. Dönen değer boşsa tünel kurulamadı."""
        self._ready.wait(timeout if timeout is not None else settings.tunnel_start_timeout)
        return self.current_url()

    # --- yaşam döngüsü ---

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Kalıcı bir alan adı verilmişse süreç yönetimine hiç girilmez.
        if settings.tunnel_hostname:
            with self._lock:
                self._url = settings.tunnel_hostname.rstrip("/")
            self._ready.set()
            self.log(f"Kalıcı public adres kullanılıyor: {self._url}")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._supervise, daemon=True, name="tunnel")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kill()
        if self._thread:
            self._thread.join(timeout=8)

    def _kill(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass

    # --- süreç ---

    def _command(self) -> List[str]:
        if self.provider == "ngrok":
            binary = ngrok_binary()
            if not binary:
                raise TunnelError(
                    "ngrok bulunamadi. .env -> NGROK_PATH verin ya da "
                    "TUNNEL_PROVIDER=cloudflared kullanin (proje icinde hazir)."
                )
            cmd = [str(binary), "http", str(self.port), "--log", "stdout",
                   "--log-format", "logfmt"]
            if settings.ngrok_authtoken:
                cmd += ["--authtoken", settings.ngrok_authtoken]
            return cmd
        binary = cloudflared_binary()
        if not binary:
            raise TunnelError(
                "cloudflared bulunamadi. Su adresten indirip "
                "tools\\bin\\cloudflared.exe olarak kaydedin: " + DOWNLOAD_HINT
            )
        return [str(binary), "tunnel", "--no-autoupdate",
                "--url", f"http://127.0.0.1:{self.port}"]

    def _supervise(self) -> None:
        """Tünel sürecini çalışır tutar; her ölümde artan gecikmeyle yeniden kurar."""
        attempt = 0
        while not self._stop.is_set():
            try:
                code = self._run_once()
            except TunnelError as e:
                with self._lock:
                    self._last_error = str(e)
                self.log(f"Tünel kurulamadı: {e}")
                self._ready.set()       # bekleyenler boş adresle devam etsin
                return
            except Exception as e:      # gözetmen asla ölmemeli
                code = -1
                with self._lock:
                    self._last_error = f"{type(e).__name__}: {e}"
            if self._stop.is_set():
                return
            with self._lock:
                self._url = ""
                self._restarts += 1
            delay = RESTART_BACKOFF[min(attempt, len(RESTART_BACKOFF) - 1)]
            attempt += 1
            self.log(f"Tünel kapandı (çıkış {code}); {delay} sn sonra yeniden kuruluyor")
            if self._stop.wait(delay):
                return

    def _run_once(self) -> int:
        cmd = self._command()
        self.log(f"Public link kuruluyor ({self.provider}) -> port {self.port}")
        # cloudflared adresi stderr'e yazar; ikisi birleştirilip tek akış okunur.
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        pattern = NGROK_URL_RE if self.provider == "ngrok" else CLOUDFLARED_URL_RE
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            match = pattern.search(line)
            if match and not self.current_url():
                url = match.group(0).rstrip("/")
                with self._lock:
                    self._url = url
                    self._last_error = ""
                self._ready.set()
                self.log(f"PUBLIC LINK HAZIR: {url}")
            low = line.lower()
            if "error" in low and "failed to" in low:
                with self._lock:
                    self._last_error = line.strip()[:300]
        self._proc.wait()
        return self._proc.returncode if self._proc.returncode is not None else -1


# --------------------------------------------------------------------------- #
# Süreç genelinde tek tünel
# --------------------------------------------------------------------------- #

_tunnel: Optional[Tunnel] = None
_tunnel_lock = threading.Lock()


def get_tunnel() -> Optional[Tunnel]:
    with _tunnel_lock:
        return _tunnel


def start_tunnel(port: Optional[int] = None, log: Callable[[str], None] = print) -> Optional[Tunnel]:
    """Tüneli (tekil) başlatır. Kapalıysa None döner."""
    global _tunnel
    if not settings.tunnel_enabled:
        log("Tünel kapalı (.env -> TUNNEL_ENABLED=false); yalnızca yerel link üretilir.")
        return None
    with _tunnel_lock:
        if _tunnel is None:
            _tunnel = Tunnel(port or settings.publish_port, log=log)
            _tunnel.start()
        return _tunnel


def stop_tunnel() -> None:
    global _tunnel
    with _tunnel_lock:
        if _tunnel is not None:
            _tunnel.stop()
            _tunnel = None


def public_base_url() -> str:
    """Linklerin kök adresi: canlı tünel -> .env ayarı -> yerel adres.

    Tek doğruluk kaynağı burasıdır; yayın ajanı ve panel bunu çağırır, böylece
    tünel adresi değiştiğinde üretilen her link kendiliğinden güncellenir.
    """
    t = get_tunnel()
    if t is not None:
        url = t.current_url()
        if url:
            return url
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return settings.local_publish_url
