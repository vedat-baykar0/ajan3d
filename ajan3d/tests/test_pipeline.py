"""Zincirin akış kuralları — hangi adım durdurur, hangisi durdurmaz.

Gözetimsiz çalışan bir zincirde en pahalı hata **sessiz** hatadır. İki kural
bu yüzden testle kilitli:

* **Ücretli araştırma asla teslimi engellemez.** Bir web aramasının
  başarısız olması müşteriye gidecek sunumu durdurursa, sistem en çok ihtiyaç
  duyulan anda çalışmaz. Hata dosyaya yazılır, montaj tanıma çıktısıyla kurulur.
* **Geçici ve kalıcı hata ayrılır.** Ayrılmazsa zincir ya boşuna döner
  (kalıcı hatayı tekrar dener) ya da sessizce vazgeçer (geçici hatada pes eder).

Hiçbir test ağ veya API kullanmaz; ajanlar yerine sahte işlevler konur.
"""
import dataclasses
import json
from pathlib import Path

import pytest
from PIL import Image

from agents import spec_agent
from agents.vision_agent import VisionError, VisionRunInfo
from core import pipeline
from core.schemas import Identification, ProductIdentity, SpecItem, SpecSheet


def _identity(confident: bool = True) -> ProductIdentity:
    return ProductIdentity(
        product_name="Paslanmaz 3 parçalı küresel vana",
        product_name_en="stainless 3-piece ball valve",
        category="endüstriyel vana", family_hint="ball_valve",
        type_designation="3 parçalı tam geçişli küresel vana, dişli uçlu",
        nominal_size="DN50", pressure_rating="PN40",
        body_material="CF8M paslanmaz çelik", end_connection="dişli",
        actuation="kol", piece_count=3, summary="Küresel vana.",
        visible_features=["ISO 5211 pabucu"], markings=["CF8M"],
        materials=["paslanmaz çelik"],
        identification=Identification(
            confident=confident, confidence="high" if confident else "low",
            issues=[] if confident else ["fotoğraf bulanık, damgalar okunamıyor"]))


def _run_info() -> VisionRunInfo:
    return VisionRunInfo(analyzed_images=["a.jpg"], total_images=1,
                         model="test", input_tokens=0, output_tokens=0,
                         cost_usd=0.0, seconds=0.0)


def _spec() -> SpecSheet:
    return SpecSheet(
        identified_as="3 parçalı CF8M küresel vana", confidence="high",
        nominal_size="DN50", pressure_rating="PN40",
        temperature_range="-20 °C … +180 °C",
        specs=[SpecItem(label="Gövde", value="CF8M")],
        standards=["ASME B16.34"], standard_parts=["Belleville rondela"],
        surface_finish="kumlanmış", applications=["Proses hatları"],
        reference_urls=["https://example.com"])


@pytest.fixture
def folder(tmp_path):
    photos = tmp_path / "fotograflar"
    photos.mkdir()
    Image.new("RGB", (800, 600), (120, 120, 125)).save(photos / "a.jpg")
    return photos


@pytest.fixture
def vision_ok(monkeypatch):
    calls = []

    def fake(path, client=None):
        calls.append(path)
        return _identity(), _run_info()

    monkeypatch.setattr(pipeline, "identify_folder", fake)
    return calls


@pytest.fixture
def no_spec(monkeypatch):
    """Ücretli adım varsayılan olarak kapalı; her test kendi davranışını kurar.

    Settings donmuş bir dataclass olduğu için kopyalanıp modül referansı
    değiştiriliyor (doğrudan atama FrozenInstanceError verir).
    """
    monkeypatch.setattr(pipeline, "settings",
                        dataclasses.replace(pipeline.settings, spec_enabled=False))
    yield


def run(folder, tmp_path, **kwargs):
    return pipeline.run_pipeline(folder, job_dir=tmp_path / "is",
                                 make_zip=False, **kwargs)


def _meta(job: Path) -> dict:
    return json.loads((job / "metadata.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Mutlu yol
# --------------------------------------------------------------------------- #

def test_chain_produces_a_package(folder, tmp_path, vision_ok, monkeypatch):
    monkeypatch.setattr(spec_agent, "research", lambda *a, **k: (_spec(), None))
    monkeypatch.setattr(spec_agent, "attach_to_metadata",
                        lambda job, result, info: _attach(job, result))
    result = run(folder, tmp_path)
    assert (result.delivery_dir / "index.html").exists()
    assert (result.job_dir / "model.glb").exists()
    assert (result.job_dir / "cad.json").exists()
    assert result.object_name.startswith("Paslanmaz")


def _attach(job, result):
    path = Path(job) / "metadata.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["spec"] = result.model_dump()
    payload["spec_run"] = {"ok": True, "searches": 2, "cost_usd": 0.1}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Ücretli adım zinciri durdurmaz
# --------------------------------------------------------------------------- #

def test_failing_web_search_does_not_stop_delivery(folder, tmp_path, vision_ok,
                                                   monkeypatch):
    def boom(*_a, **_k):
        raise spec_agent.SpecError("arama kotası doldu")

    monkeypatch.setattr(spec_agent, "research", boom)
    messages = []
    result = run(folder, tmp_path, on_progress=messages.append)
    assert (result.delivery_dir / "index.html").exists()
    assert _meta(result.job_dir)["spec_run"] == {"ok": False,
                                                 "error": "arama kotası doldu"}
    assert any("Teknik veri atlandı" in m for m in messages)


def test_unexpected_exception_in_search_is_also_survived(folder, tmp_path,
                                                         vision_ok, monkeypatch):
    """SpecError disinda bir hata da zinciri durdurmamali."""
    monkeypatch.setattr(spec_agent, "research",
                        lambda *a, **k: (_ for _ in ()).throw(KeyError("beklenmedik")))
    result = run(folder, tmp_path)
    assert (result.delivery_dir / "index.html").exists()
    assert _meta(result.job_dir)["spec_run"]["ok"] is False


def test_disabled_search_is_never_called(folder, tmp_path, vision_ok, no_spec,
                                         monkeypatch):
    called = []
    monkeypatch.setattr(spec_agent, "research",
                        lambda *a, **k: called.append(1) or (_spec(), None))
    result = run(folder, tmp_path)
    assert called == []
    assert "spec" not in _meta(result.job_dir)
    assert (result.delivery_dir / "index.html").exists()


def test_existing_spec_is_not_paid_for_twice(folder, tmp_path, vision_ok,
                                             monkeypatch):
    calls = []
    monkeypatch.setattr(spec_agent, "research",
                        lambda *a, **k: (calls.append(1), (_spec(), None))[1])
    monkeypatch.setattr(spec_agent, "attach_to_metadata",
                        lambda job, result, info: _attach(job, result))
    run(folder, tmp_path)
    run(folder, tmp_path, repackage=True)
    assert len(calls) == 1, "ücretli arama ikinci kez yapıldı"


# --------------------------------------------------------------------------- #
# Tanıma hataları
# --------------------------------------------------------------------------- #

def test_low_confidence_blocks_the_job(folder, tmp_path, no_spec, monkeypatch):
    monkeypatch.setattr(pipeline, "identify_folder",
                        lambda p, client=None: (_identity(False), _run_info()))
    with pytest.raises(pipeline.PipelineError) as err:
        run(folder, tmp_path)
    assert err.value.stage == "identification"
    assert not err.value.retriable          # aynı fotoğrafla tekrar denemek anlamsız
    assert "bulanık" in str(err.value)


def test_force_overrides_low_confidence(folder, tmp_path, no_spec, monkeypatch):
    monkeypatch.setattr(pipeline, "identify_folder",
                        lambda p, client=None: (_identity(False), _run_info()))
    result = run(folder, tmp_path, force=True)
    assert (result.delivery_dir / "index.html").exists()


@pytest.mark.parametrize("message,retriable", [
    ("Anthropic hız sınırına takıldı; sonra tekrar denenecek.", True),
    ("Anthropic sunucu hatası 503 (geçici): overloaded", True),
    ("Anthropic API'ye bağlanılamadı (geçici): timeout", True),
    ("Anthropic hesabının kredi bakiyesi yetersiz.", False),
    ("Anthropic API anahtarı geçersiz", False),
])
def test_vision_errors_are_classified(folder, tmp_path, no_spec, monkeypatch,
                                      message, retriable):
    def boom(*_a, **_k):
        raise VisionError(message)

    monkeypatch.setattr(pipeline, "identify_folder", boom)
    with pytest.raises(pipeline.PipelineError) as err:
        run(folder, tmp_path)
    assert err.value.stage == "vision"
    assert err.value.retriable is retriable


def test_missing_folder_is_a_clear_error(tmp_path, no_spec):
    with pytest.raises(pipeline.PipelineError) as err:
        pipeline.run_pipeline(tmp_path / "yok", job_dir=tmp_path / "is")
    assert err.value.stage == "input"


# --------------------------------------------------------------------------- #
# Tamamlanmış adımlar atlanır
# --------------------------------------------------------------------------- #

def test_second_run_skips_finished_steps(folder, tmp_path, vision_ok, no_spec):
    first = run(folder, tmp_path)
    messages = []
    second = run(folder, tmp_path, on_progress=messages.append)
    assert len(vision_ok) == 1, "tanıma ikinci kez çağrıldı"
    assert second.delivery_dir == first.delivery_dir
    text = " ".join(messages)
    assert "Tanıma atlandı" in text
    assert "CAD montajı atlandı" in text
    assert "Paket atlandı" in text


def test_rebuild_cad_forces_a_new_assembly(folder, tmp_path, vision_ok, no_spec):
    """--rebuild-cad montaji da paketi de yeniler.

    Paket klasorunun adi saniye cozunurluklu tarih tasir; ayni saniye icinde
    yeniden paketlenirse ayni klasor uzerine yazilir. Burada onemli olan
    icerigin tazelenmesi, klasor adinin degismesi degil.
    """
    first = run(folder, tmp_path)
    before_job = (first.job_dir / "model.glb").stat().st_mtime_ns
    before_pkg = (first.delivery_dir / "model.glb").stat().st_mtime_ns
    second = run(folder, tmp_path, rebuild_cad=True)
    assert (second.job_dir / "model.glb").stat().st_mtime_ns != before_job
    assert (second.delivery_dir / "model.glb").stat().st_mtime_ns != before_pkg


def test_cad_report_records_the_match_decision(folder, tmp_path, vision_ok, no_spec):
    result = run(folder, tmp_path)
    report = json.loads((result.job_dir / "cad.json").read_text(encoding="utf-8"))
    assert report["family"] == "ball_valve"
    assert report["source"] == "parametric"
    assert report["representative"] is False
    assert report["validation"]["all_solid"] is True
    assert report["params"]["dn"] == 50 and report["params"]["pieces"] == 3
    assert "Küresel vana" in report["match_reason"]
