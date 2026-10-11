"""Kaynak seçimi: yerel kütüphane → uzak API → parametrik üretim.

Bu zincirin kritik özelliği **hiç durmamasıdır**. Yerel kütüphane boşsa, uzak
API kapalıysa ya da indirilen dosya bozuksa sistem sessizce parametrik yola
düşer ve yine kullanılabilir bir montaj verir. Aşağıdaki testler hem bu
dayanıklılığı hem de yerel kütüphanenin gerçekten tercih edildiğini kilitliyor.
"""
import dataclasses
import json

import pytest

from cad import gltf, retrieval
from cad.families import flange_joint

IDENTITY = {
    "product_name": "Paslanmaz 3 parçalı küresel vana",
    "product_name_en": "stainless 3-piece ball valve",
    "family_hint": "ball_valve",
    "type_designation": "3 parçalı tam geçişli küresel vana, dişli uçlu",
    "nominal_size": "DN50",
    "pressure_rating": "PN40",
    "body_material": "CF8M paslanmaz çelik",
    "end_connection": "dişli",
    "actuation": "kol",
    "piece_count": 3,
}


def with_settings(monkeypatch, **overrides):
    """Settings donmus bir dataclass: kopyalanip modul referansi degistirilir."""
    monkeypatch.setattr(retrieval, "settings",
                        dataclasses.replace(retrieval.settings, **overrides))


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Tek girdili sahte bir yerel kütüphane kurar."""
    entry = tmp_path / "dn50-kuresel-vana"
    entry.mkdir()
    assembly = flange_joint.build({"dn": 50, "pn": 16})      # içerik önemsiz
    gltf.write_glb(assembly, entry / "model.glb")
    manifest = {
        "label": "DN50 3 parçalı küresel vana (tedarikçi modeli)",
        "family": "ball_valve",
        "keywords": ["küresel vana", "ball valve", "dn50", "3 parçalı"],
        "model": "model.glb",
        "representative": False,
        "diagonal_mm": 285.0,
        "specs": [{"label": "Katalog kodu", "value": "2103-50"}],
        "parts": [
            {"node": "flans_1", "id": "govde", "name": "Orta gövde",
             "group": "housing", "material": "stainless_cast",
             "axis": [0, 1, 0], "distance": 0, "stage": 0,
             "standard": "ASME B16.34", "note": "Döküm gövde"},
            {"node": "flans_2", "id": "kapak", "name": "Uç kapağı",
             "group": "housing", "material": "stainless_cast",
             "axis": [0, 0, -3], "distance": 0.72, "stage": 2, "qty": 2},
        ],
    }
    (entry / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                         encoding="utf-8")
    monkeypatch.setattr(retrieval, "LIBRARY_DIR", tmp_path)
    return entry


# --------------------------------------------------------------------------- #
# Yerel kütüphane
# --------------------------------------------------------------------------- #

def test_local_entry_is_discovered(library):
    entries = retrieval.local_entries()
    assert len(entries) == 1
    assert entries[0]["label"].startswith("DN50")


def test_entry_without_model_file_is_skipped(library, monkeypatch):
    (library / "model.glb").unlink()
    assert retrieval.local_entries() == []


def test_broken_manifest_does_not_crash_discovery(library):
    (library / "manifest.json").write_text("{ bozuk json", encoding="utf-8")
    assert retrieval.local_entries() == []


def test_matching_product_uses_the_library(library):
    model = retrieval.from_local(IDENTITY, None)
    assert model is not None
    assert model.source == "local"
    assert model.confidence == "high"
    assert "dn50-kuresel-vana" in model.match_reason
    assert model.specs == [{"label": "Katalog kodu", "value": "2103-50"}]


def test_unrelated_product_does_not_match(library):
    assert retrieval.from_local({"product_name": "Mutfak robotu",
                                 "family_hint": "other"}, None) is None


def test_library_model_gets_the_explode_contract(library):
    """Kütüphane modeli de parametrik modelle aynı arayüzü beslemeli."""
    model = retrieval.from_local(IDENTITY, None)
    doc, _ = gltf.read_glb(model.glb)
    named = {n["name"]: n for n in doc["nodes"] if "name" in n}
    assert named["flans_1"]["extras"] == {"pid": "govde", "grp": "housing",
                                          "ax": [0.0, 1.0, 0.0], "d": 0.0, "st": 0}
    # Birim olmayan eksen normalize edilmeli
    assert named["flans_2"]["extras"]["ax"] == [0.0, 0.0, -1.0]
    assert doc["scenes"][0]["extras"]["label"].startswith("DN50")


def test_library_geometry_is_untouched(library):
    """Dosya olduğu gibi korunur; yalnızca extras eklenir."""
    original = (library / "model.glb").read_bytes()
    model = retrieval.from_local(IDENTITY, None)
    assert gltf.read_glb(model.glb)[1] == gltf.read_glb(original)[1]


def test_library_catalog_matches_manifest(library):
    model = retrieval.from_local(IDENTITY, None)
    assert [row["id"] for row in model.catalog] == ["govde", "kapak"]
    assert model.catalog[1]["qty"] == 2
    assert model.catalog[0]["standard"] == "ASME B16.34"
    # Kütle hesaplanmaz: dosyanın kapalı katı olduğu bilinemez
    assert all(row["mass_g"] == 0.0 for row in model.catalog)


# --------------------------------------------------------------------------- #
# Sıralı deneme
# --------------------------------------------------------------------------- #

def test_local_is_preferred_over_parametric(library, monkeypatch):
    with_settings(monkeypatch, cad_sources="local,parametric")
    assert retrieval.acquire(IDENTITY).source == "local"


def test_falls_back_to_parametric_when_library_misses(library, monkeypatch):
    with_settings(monkeypatch, cad_sources="local,parametric")
    model = retrieval.acquire({"product_name": "DN80 kelebek vana",
                               "family_hint": "butterfly_valve"})
    assert model.source == "parametric"
    assert model.family == "butterfly_valve"
    assert model.assembly is not None


def test_parametric_only_ignores_the_library(library, monkeypatch):
    with_settings(monkeypatch, cad_sources="parametric")
    assert retrieval.acquire(IDENTITY).source == "parametric"


def test_remote_is_skipped_when_unconfigured(monkeypatch):
    with_settings(monkeypatch, cad_api_url="")
    assert retrieval.from_remote(IDENTITY, None) is None


def test_a_failing_source_does_not_stop_the_chain(monkeypatch):
    """Bir kaynak patlarsa zincir durmaz; sonraki kaynağa geçer."""
    def boom(*_args, **_kwargs):
        raise RuntimeError("kütüphane diski okunamadı")

    monkeypatch.setattr(retrieval, "from_local", boom)
    with_settings(monkeypatch, cad_sources="local,parametric")
    messages = []
    model = retrieval.acquire(IDENTITY, on_progress=messages.append)
    assert model.source == "parametric"
    assert any("local" in m for m in messages)


def test_unknown_source_name_is_ignored(monkeypatch):
    with_settings(monkeypatch, cad_sources="sihirli-kaynak")
    assert retrieval.acquire(IDENTITY).source == "parametric"


def test_parametric_result_carries_validation(monkeypatch):
    with_settings(monkeypatch, cad_sources="parametric")
    model = retrieval.acquire(IDENTITY)
    assert model.report["all_solid"] is True
    assert model.report["parts"] >= 10
    assert model.diagonal_mm > 0
    assert model.confidence == "high"
