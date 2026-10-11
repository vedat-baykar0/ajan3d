"""Tünel yöneticisi testleri — gerçek ağ veya cloudflared süreci gerektirmez.

Tünel süreci taklit edilir (fake Popen): adres ayıklama, gözetmen davranışı ve
link türetme mantığı test edilir. Gerçek cloudflared bağlantısı ayrıca elle
doğrulandı; burada test edilen şey o değil, **adres değiştiğinde linklerin
doğru güncellenmesi**.
"""
import dataclasses
import threading
import time

import pytest

from core import tunnel as tunnel_module
from core.tunnel import (CLOUDFLARED_URL_RE, NGROK_URL_RE, Tunnel, TunnelError,
                         public_base_url)


def patch_settings(monkeypatch, **changes):
    """`Settings` dondurulmuş bir dataclass; alan değiştirmek yerine kopya koyar."""
    replacement = dataclasses.replace(tunnel_module.settings, **changes)
    monkeypatch.setattr(tunnel_module, "settings", replacement)
    return replacement

CF_LINE = ("2026-10-10T01:20:11Z INF |  https://equal-leeds-fraser-unknown."
           "trycloudflare.com  |\n")


class FakeProc:
    """subprocess.Popen taklidi: verilen satırları akıtır, sonra çıkar."""

    def __init__(self, lines, exit_code=0, hold=False):
        self.stdout = iter(lines)
        self.returncode = None
        self._exit_code = exit_code
        self._hold = hold
        self.terminated = False

    def wait(self, timeout=None):
        if self._hold and not self.terminated:
            # Gerçek süreç gibi davran: durdurulana kadar yaşar
            for _ in range(100):
                if self.terminated:
                    break
                time.sleep(0.01)
        self.returncode = self._exit_code
        return self._exit_code

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = self._exit_code

    def kill(self):
        self.terminate()


@pytest.fixture(autouse=True)
def _reset_singleton():
    tunnel_module._tunnel = None
    yield
    tunnel_module._tunnel = None


# --------------------------------------------------------------------------- #
# Adres ayıklama
# --------------------------------------------------------------------------- #

def test_cloudflared_regex_extracts_url():
    assert CLOUDFLARED_URL_RE.search(CF_LINE).group(0) == \
        "https://equal-leeds-fraser-unknown.trycloudflare.com"


def test_cloudflared_regex_ignores_unrelated_lines():
    assert CLOUDFLARED_URL_RE.search("INF Starting tunnel, no url yet") is None


def test_ngrok_regex_extracts_url():
    line = 'msg="started tunnel" url=https://1a2b-3c.ngrok-free.app\n'
    assert NGROK_URL_RE.search(line).group(0) == "https://1a2b-3c.ngrok-free.app"


# --------------------------------------------------------------------------- #
# Yaşam döngüsü
# --------------------------------------------------------------------------- #

def test_tunnel_publishes_url_from_process_output(monkeypatch):
    t = Tunnel(port=8001, log=lambda m: None)
    monkeypatch.setattr(t, "_command", lambda: ["fake"])
    monkeypatch.setattr(tunnel_module.subprocess, "Popen",
                        lambda *a, **k: FakeProc([CF_LINE], hold=True))
    t.start()
    url = t.wait_ready(timeout=5)
    assert url == "https://equal-leeds-fraser-unknown.trycloudflare.com"
    assert t.status().running
    t.stop()


def test_tunnel_status_reports_error_when_binary_missing(monkeypatch):
    t = Tunnel(port=8001, log=lambda m: None)

    def boom():
        raise TunnelError("cloudflared bulunamadi")

    monkeypatch.setattr(t, "_command", boom)
    t.start()
    assert t.wait_ready(timeout=5) == ""
    assert "bulunamadi" in t.status().last_error
    t.stop()


def test_tunnel_restarts_when_process_dies(monkeypatch):
    """Ücretsiz tüneller kopuyor; gözetmen yeniden kurmalı."""
    monkeypatch.setattr(tunnel_module, "RESTART_BACKOFF", (0.01,))
    starts = []

    def fake_popen(*a, **k):
        starts.append(1)
        # İlk süreç hemen ölür, ikincisi yaşar
        return FakeProc([CF_LINE], hold=len(starts) > 1)

    t = Tunnel(port=8001, log=lambda m: None)
    monkeypatch.setattr(t, "_command", lambda: ["fake"])
    monkeypatch.setattr(tunnel_module.subprocess, "Popen", fake_popen)
    t.start()
    # Sayaç, yeniden başlatmadan ÖNCE artıyor; bu yüzden gerçek ölçüt
    # ikinci sürecin kurulmuş olması.
    deadline = time.monotonic() + 5
    while len(starts) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(starts) >= 2, "gözetmen yeniden başlatmadı"
    assert t.status().restarts >= 1
    assert t.wait_ready(timeout=5), "yeniden kurulan tünel adres vermeli"
    t.stop()


def test_permanent_hostname_skips_process(monkeypatch):
    """Kalıcı alan adı verilmişse süreç hiç başlatılmaz."""
    patch_settings(monkeypatch, tunnel_hostname="https://3d.firmam.com/")
    called = []
    monkeypatch.setattr(tunnel_module.subprocess, "Popen",
                        lambda *a, **k: called.append(1))
    t = Tunnel(port=8001, log=lambda m: None)
    t.start()
    assert t.wait_ready(timeout=2) == "https://3d.firmam.com"
    assert not called


def test_current_url_is_thread_safe(monkeypatch):
    t = Tunnel(port=8001, log=lambda m: None)
    monkeypatch.setattr(t, "_command", lambda: ["fake"])
    monkeypatch.setattr(tunnel_module.subprocess, "Popen",
                        lambda *a, **k: FakeProc([CF_LINE], hold=True))
    t.start()
    t.wait_ready(timeout=5)
    seen = []
    threads = [threading.Thread(target=lambda: seen.append(t.current_url()))
               for _ in range(12)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(set(seen)) == 1
    t.stop()


# --------------------------------------------------------------------------- #
# Link kök adresi — tek doğruluk kaynağı
# --------------------------------------------------------------------------- #

def test_public_base_url_prefers_live_tunnel(monkeypatch):
    class Stub:
        def current_url(self):
            return "https://canli.trycloudflare.com"

    monkeypatch.setattr(tunnel_module, "_tunnel", Stub())
    assert public_base_url() == "https://canli.trycloudflare.com"


def test_public_base_url_falls_back_to_setting(monkeypatch):
    monkeypatch.setattr(tunnel_module, "_tunnel", None)
    patch_settings(monkeypatch, public_base_url="https://3d.firmam.com/")
    assert public_base_url() == "https://3d.firmam.com"


def test_public_base_url_falls_back_to_local_publish_port(monkeypatch):
    """Son çare YAYIN portu olmalı; panel portu (8000) dışa verilmez."""
    monkeypatch.setattr(tunnel_module, "_tunnel", None)
    replaced = patch_settings(monkeypatch, public_base_url="")
    assert public_base_url() == replaced.local_publish_url
    assert str(replaced.publish_port) in public_base_url()


def test_public_base_url_ignores_tunnel_without_address(monkeypatch):
    """Tünel kuruluyorsa (adres yok) ayara düşülmeli, boş link üretilmemeli."""
    class Stub:
        def current_url(self):
            return ""

    monkeypatch.setattr(tunnel_module, "_tunnel", Stub())
    replaced = patch_settings(monkeypatch, public_base_url="")
    assert public_base_url() == replaced.local_publish_url


def test_start_tunnel_disabled_returns_none(monkeypatch):
    patch_settings(monkeypatch, tunnel_enabled=False)
    assert tunnel_module.start_tunnel(log=lambda m: None) is None


# --------------------------------------------------------------------------- #
# Kayit adresi public link sanilmasin
# --------------------------------------------------------------------------- #

def test_cloudflared_registration_endpoint_is_not_a_public_link():
    """cloudflared kayit olurken gunluge kendi API adresini yaziyor.

    Yasandi: kayit birkac kez basarisiz olurken sistem
    `https://api.trycloudflare.com` adresini "PUBLIC LINK HAZIR" diye ilan
    etti ve bu adres `3D_SONUC.txt`'ye yazildi. Musteriye gonderilecek link
    hicbir yere gitmiyordu.
    """
    from core.tunnel import CLOUDFLARED_URL_RE as RE
    assert RE.search("INF Retrying to register tunnel "
                     "url=https://api.trycloudflare.com/tunnel") is None
    assert RE.search("INF |  https://cad-sat-usually-thousands.trycloudflare.com  |"
                     ).group(0) == "https://cad-sat-usually-thousands.trycloudflare.com"
    assert RE.search("INF Requesting new quick Tunnel on trycloudflare.com...") is None


def test_ngrok_api_endpoint_is_not_a_public_link():
    from core.tunnel import NGROK_URL_RE as RE
    assert RE.search("msg=\"starting\" url=https://api.ngrok.com/tunnels") is None
    assert RE.search("url=https://a1b2-c3.ngrok-free.app").group(0) == \
        "https://a1b2-c3.ngrok-free.app"
