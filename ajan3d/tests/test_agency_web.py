"""Yönetim paneli / yayın sunucusu ayrımının testi.

Bu bir **güvenlik** testi. Önceki kurulumda tek port vardı ve tünel onu
açıyordu; `/p/...` paketlerinin yanında iş adları, müşteri klasör yolları ve
hata mesajları da internetten görünüyordu. Ayrımın sessizce geri gelmemesi
için burada kilitleniyor.
"""
import dataclasses
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

import run_agency
from agents import deployer_agent
from core.agency import BLOCKED, DEPLOYED, NOTIFIED, AgencyJob


@pytest.fixture
def world(tmp_path, monkeypatch):
    """İçinde bir yayınlanmış paket ve bir engellenmiş iş olan sahte dünya."""
    public = tmp_path / "public"
    jobs = tmp_path / "jobs"
    inbox = tmp_path / "inbox"
    for d in (public, jobs, inbox):
        d.mkdir()

    replaced = dataclasses.replace(run_agency.settings, public_dir=public,
                                   jobs_dir=jobs, inbox_dir=inbox)
    monkeypatch.setattr(run_agency, "settings", replaced)
    monkeypatch.setattr(deployer_agent, "settings", replaced)
    monkeypatch.setattr(deployer_agent, "public_base_url",
                        lambda: "https://sahte.trycloudflare.com")

    # Yayınlanmış paket
    package = public / "gizli-urun-20261010-010101"
    package.mkdir()
    (package / "index.html").write_text("<html>sunum</html>", encoding="utf-8")
    (package / "published.json").write_text(json.dumps({
        "slug": package.name, "object_name": "Gizli Ürün",
        "published_at": "2026-10-10T01:01:01", "size_mb": 1.0,
    }, ensure_ascii=False), encoding="utf-8")

    # Engellenmiş iş: müşteri klasör yolu ve hata mesajı taşır
    job_dir = jobs / "musteri-isi-20261010"
    job_dir.mkdir()
    AgencyJob(
        job_dir=str(job_dir),
        source_folder=str(inbox / "GizliMusteri-Kasim-Siparisi"),
        customer_email="musteri@ornek.com",
        object_name="Gizli Ürün",
        stage=BLOCKED,
        last_error="Anthropic hesabının kredi bakiyesi yetersiz",
        public_slug=package.name,
    ).save()
    return replaced


# --------------------------------------------------------------------------- #
# Yayın sunucusu — dışa açık
# --------------------------------------------------------------------------- #

def test_publish_server_serves_packages(world):
    client = TestClient(run_agency.build_publish_app())
    response = client.get("/p/gizli-urun-20261010-010101/")
    assert response.status_code == 200
    assert "sunum" in response.text


def test_publish_gallery_lists_published_packages(world):
    client = TestClient(run_agency.build_publish_app())
    body = client.get("/").text
    assert "Gizli Ürün" in body, "galeri yayınlanmış paketi göstermeli"
    assert "/p/gizli-urun-20261010-010101/" in body


def test_publish_server_leaks_no_operational_detail(world):
    """Asıl güvence: dışa açık sunucuda yönetim bilgisi görünmemeli."""
    client = TestClient(run_agency.build_publish_app())
    body = client.get("/").text
    forbidden = [
        "GizliMusteri-Kasim-Siparisi",      # müşteri klasör adı
        "musteri@ornek.com",                # müşteri e-postası
        "kredi bakiyesi",                   # işletme hatası
        "BLOCKED",                          # iş aşaması
        "musteri-isi-20261010",             # iş dizini
        "agency.json",
    ]
    leaked = [token for token in forbidden if token in body]
    assert leaked == [], f"yayın sunucusu sızdırıyor: {leaked}"


def test_publish_server_has_no_management_endpoints(world):
    client = TestClient(run_agency.build_publish_app())
    assert client.get("/api/jobs").status_code == 404
    assert client.get("/go").status_code == 404


def test_publish_server_hides_api_docs(world):
    """Otomatik /docs ve /openapi.json dışarıya uç listesi vermemeli."""
    client = TestClient(run_agency.build_publish_app())
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_publish_gallery_empty_state(tmp_path, monkeypatch):
    replaced = dataclasses.replace(run_agency.settings, public_dir=tmp_path / "bos")
    monkeypatch.setattr(run_agency, "settings", replaced)
    monkeypatch.setattr(deployer_agent, "settings", replaced)
    client = TestClient(run_agency.build_publish_app())
    assert client.get("/").status_code == 200


# --------------------------------------------------------------------------- #
# Yönetim paneli — yerel
# --------------------------------------------------------------------------- #

def test_panel_shows_operational_detail(world):
    """Panel tam tersi: operatörün ihtiyacı olan her şeyi göstermeli."""
    client = TestClient(run_agency.build_panel_app())
    body = client.get("/").text
    assert "GizliMusteri-Kasim-Siparisi" in body
    assert "BLOCKED" in body
    assert "kredi bakiyesi" in body


def test_panel_health_reports_tunnel_state(world, monkeypatch):
    monkeypatch.setattr(run_agency, "get_tunnel", lambda: None)
    client = TestClient(run_agency.build_panel_app())
    data = client.get("/health").json()
    assert data["ok"] is True
    assert "public_base_url" in data
    assert data["tunnel"] is None


def test_panel_api_jobs_regenerates_links(world, monkeypatch):
    client = TestClient(run_agency.build_panel_app())
    rows = client.get("/api/jobs").json()
    assert rows[0]["public_url"] == \
        "https://sahte.trycloudflare.com/p/gizli-urun-20261010-010101/"

    # Tünel adresi değişti: panel yeni adresi göstermeli, eskisini değil
    monkeypatch.setattr(deployer_agent, "public_base_url", lambda: "https://yeni.com")
    rows = client.get("/api/jobs").json()
    assert rows[0]["public_url"] == "https://yeni.com/p/gizli-urun-20261010-010101/"


def test_panel_escapes_job_fields(world):
    """İş alanları klasör adlarından ve Vision çıktısından geliyor.

    Not: `</script>` gibi bir yük klasör adı üzerinden panele hiç ulaşamıyor,
    çünkü Windows'ta `/` yol ayırıcısıdır ve `Path.name` son bileşeni alır.
    Bu yüzden kaçışlama, yol ayırıcısı içermeyen bir yükle denetleniyor.
    """
    jobs_dir = world.jobs_dir
    job_dir = jobs_dir / "xss-isi"
    job_dir.mkdir()
    AgencyJob(job_dir=str(job_dir),
              source_folder=str(jobs_dir / "klasor"),
              customer_email="",
              object_name='<img src=x onerror=alert(1)>',
              stage=DEPLOYED,
              last_error='<b onmouseover="x">hata</b>').save()
    body = TestClient(run_agency.build_panel_app()).get("/").text
    assert "<img src=x onerror=" not in body, "ürün adı ham HTML olarak girdi"
    assert '<b onmouseover=' not in body, "hata mesajı ham HTML olarak girdi"
    assert "&lt;img src=x onerror=alert(1)&gt;" in body


def test_panel_go_redirects_to_public_base(world, monkeypatch):
    monkeypatch.setattr(run_agency, "public_base_url", lambda: "https://sahte.com")
    client = TestClient(run_agency.build_panel_app())
    response = client.get("/go", follow_redirects=False)
    assert response.status_code in (307, 302)
    assert response.headers["location"] == "https://sahte.com/"


# --------------------------------------------------------------------------- #
# Ayar doğrulaması
# --------------------------------------------------------------------------- #

def test_check_config_rejects_identical_ports(monkeypatch):
    """Aynı port, panelin internete sızması demek; başlamadan yakalanmalı."""
    monkeypatch.setattr(run_agency, "settings",
                        dataclasses.replace(run_agency.settings,
                                            agency_port=8000, publish_port=8000))
    problems = run_agency.check_config()
    assert any("ayrı portta" in p for p in problems)


def test_check_config_accepts_default_ports():
    assert run_agency.check_config() == []


def test_check_config_flags_missing_api_key(monkeypatch):
    monkeypatch.setattr(run_agency, "settings",
                        dataclasses.replace(run_agency.settings, anthropic_api_key=""))
    assert any("ANTHROPIC_API_KEY" in p for p in run_agency.check_config())


def test_legacy_job_without_slug_still_produces_link(world, monkeypatch):
    """`public_slug` alanı sonradan eklendi; eski işlerin linki boş kalmamalı.

    Eski `agency.json` yalnızca (artık geçersiz) tam adresi taşıyor; slug
    ondan geri çıkarılıp güncel tünel adresiyle birleştirilmeli.
    """
    legacy_slug = "eski-urun-20261001-120000"
    package = world.public_dir / legacy_slug
    package.mkdir()
    (package / "index.html").write_text("<html>eski</html>", encoding="utf-8")

    job_dir = world.jobs_dir / "eski-is"
    job_dir.mkdir()
    AgencyJob(job_dir=str(job_dir), source_folder=str(world.inbox_dir / "eski"),
              customer_email="", object_name="Eski Ürün", stage=NOTIFIED,
              public_url=f"http://localhost:8000/p/{legacy_slug}/").save()

    loaded = AgencyJob.load(job_dir)
    assert loaded.public_slug == "", "eski kayıtta slug alanı yok"
    assert loaded.slug == legacy_slug, "slug eski adresten çıkarılamadı"

    rows = TestClient(run_agency.build_panel_app()).get("/api/jobs").json()
    legacy = next(r for r in rows if r["object_name"] == "Eski Ürün")
    assert legacy["public_url"] == f"https://sahte.trycloudflare.com/p/{legacy_slug}/"


def test_job_without_any_url_has_empty_slug():
    job = AgencyJob(job_dir="x", source_folder="y", customer_email="")
    assert job.slug == ""


def test_panel_hides_link_for_unpublished_package(world):
    """Yayından kaldırılmış paketin linki gösterilmemeli; 404 verir ve
    operatör onu farkında olmadan müşteriye gönderebilir."""
    from agents import deployer_agent

    assert deployer_agent.is_live("gizli-urun-20261010-010101")
    deployer_agent.unpublish("gizli-urun-20261010-010101")
    assert not deployer_agent.is_live("gizli-urun-20261010-010101")

    rows = TestClient(run_agency.build_panel_app()).get("/api/jobs").json()
    assert all(r["public_url"] == "" for r in rows)
    body = TestClient(run_agency.build_panel_app()).get("/").text
    assert "yayında değil" in body


# --------------------------------------------------------------------------- #
# Takılmış işaret (claim) kurtarma
# --------------------------------------------------------------------------- #

def test_stale_claim_without_job_record_is_released(tmp_path):
    """İşaretlenip iş kaydı açılmadan kapanan klasör tekrar alınabilmeli.

    Servis `claim()` ile `AgencyJob.save()` arasında kapanırsa klasör sonsuza
    kadar atlanıyordu (yaşandı). İş kaydı yoksa ve işaret tazeliğini
    yitirmişse klasör serbest sayılır.
    """
    import os
    import time as _time
    from agents import receiver_agent

    folder = tmp_path / "musteri"
    folder.mkdir()
    job_dir = tmp_path / "jobs" / "musteri-123"
    receiver_agent.claim(folder, job_dir)

    # Taze işaret: işçi henüz devralmamış olabilir, korunur
    assert receiver_agent.is_claimed(folder)

    # İşaret eskitilir, iş kaydı hâlâ yok -> serbest
    old = _time.time() - receiver_agent.STALE_CLAIM_SECONDS - 10
    os.utime(receiver_agent.marker_path(folder), (old, old))
    assert not receiver_agent.is_claimed(folder)

    # İş kaydı varsa yaşı önemli değil, klasör alınmış sayılır
    job_dir.mkdir(parents=True)
    (job_dir / "agency.json").write_text("{}", encoding="utf-8")
    assert receiver_agent.is_claimed(folder)


def test_unclaimed_folder_is_never_considered_claimed(tmp_path):
    from agents import receiver_agent
    folder = tmp_path / "bos"
    folder.mkdir()
    assert not receiver_agent.is_claimed(folder)
