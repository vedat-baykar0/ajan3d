"""Web optimizasyonu: Draco ne zaman uygulanir, uygulanmazsa ne olur.

Bu adim **asla zorunlu degildir**. Node kurulu olmasa, paketler eksik olsa ya
da butunluk dogrulamasi dusse bile zincir sikistirilmamis modelle devam eder.
Testler hem kazanci hem de bu dayanikliligi kilitliyor.
"""
import dataclasses
import json
import shutil

import pytest

from cad import gltf
from cad.families import ball_valve
from core import optimize


@pytest.fixture(scope="module")
def raw_model(tmp_path_factory):
    out = tmp_path_factory.mktemp("cad") / "model.glb"
    gltf.write_glb(ball_valve.build({"dn": 50, "pn": 63, "pieces": 3}), out)
    return out


def _settings(monkeypatch, **over):
    monkeypatch.setattr(optimize, "settings",
                        dataclasses.replace(optimize.settings, **over))


# --------------------------------------------------------------------------- #
# Esik mantigi
# --------------------------------------------------------------------------- #

def test_small_models_are_not_compressed(monkeypatch):
    """Cozucu ~250 KB; kucuk modelde sikistirmak toplam indirmeyi ARTIRIR."""
    _settings(monkeypatch, draco_min_bytes=400_000)
    assert not optimize.worth_it(120_000)
    assert optimize.worth_it(900_000)


def test_disabled_setting_skips_the_step(monkeypatch, raw_model, tmp_path):
    _settings(monkeypatch, draco_enabled=False)
    result = optimize.optimize(raw_model, tmp_path / "web.glb")
    assert not result.ok and not result.draco
    assert result.path == raw_model
    assert result.reason == "kapalı"
    assert not (tmp_path / "web.glb").exists()


def test_small_model_reports_why_it_was_skipped(monkeypatch, tmp_path):
    _settings(monkeypatch, draco_enabled=True, draco_min_bytes=10_000_000)
    small = tmp_path / "kucuk.glb"
    shutil.copy2(__file__, small)          # icerik onemsiz, boyut onemli
    result = optimize.optimize(small, tmp_path / "web.glb")
    assert not result.ok
    assert "küçük" in result.reason


def test_missing_toolchain_is_not_an_error(monkeypatch, raw_model, tmp_path):
    """Node yoksa adim atlanir, zincir durmaz."""
    _settings(monkeypatch, draco_enabled=True, draco_min_bytes=1)
    monkeypatch.setattr(optimize, "node_binary", lambda: None)
    result = optimize.optimize(raw_model, tmp_path / "web.glb")
    assert not result.ok and result.path == raw_model
    assert "Node" in result.reason


def test_broken_tool_output_falls_back_to_the_raw_model(monkeypatch, raw_model,
                                                        tmp_path):
    _settings(monkeypatch, draco_enabled=True, draco_min_bytes=1)
    monkeypatch.setattr(optimize, "SCRIPT", tmp_path / "yok.mjs")
    result = optimize.optimize(raw_model, tmp_path / "web.glb")
    assert not result.ok and result.path == raw_model


# --------------------------------------------------------------------------- #
# Gercek sikistirma (Node varsa)
# --------------------------------------------------------------------------- #

needs_node = pytest.mark.skipif(not optimize.available(),
                                reason="Node/gltf-transform kurulu degil")


@needs_node
def test_compression_is_substantial_and_keeps_the_contract(monkeypatch, raw_model,
                                                           tmp_path):
    _settings(monkeypatch, draco_enabled=True, draco_min_bytes=1)
    target = tmp_path / "web.glb"
    result = optimize.optimize(raw_model, target)
    assert result.ok and result.draco and result.path == target
    assert result.saved_pct >= 60, f"yalnizca %{result.saved_pct} kazanc"

    doc, _ = gltf.read_glb(target.read_bytes())
    assert "KHR_draco_mesh_compression" in doc.get("extensionsRequired", [])
    # Patlatma sozlesmesi her dugumde korunmali
    source_doc, _ = gltf.read_glb(raw_model.read_bytes())
    before = [n["extras"] for n in source_doc["nodes"] if "extras" in n]
    after = [n["extras"] for n in doc["nodes"] if "extras" in n]
    assert len(after) == len(before)
    assert {e["pid"] for e in after} == {e["pid"] for e in before}
    for extras in after:
        assert set(extras) == {"pid", "grp", "ax", "d", "st"}


@needs_node
def test_mesh_and_material_counts_survive(monkeypatch, raw_model, tmp_path):
    _settings(monkeypatch, draco_enabled=True, draco_min_bytes=1)
    target = tmp_path / "web.glb"
    assert optimize.optimize(raw_model, target).ok
    before, _ = gltf.read_glb(raw_model.read_bytes())
    after, _ = gltf.read_glb(target.read_bytes())
    assert len(after["meshes"]) == len(before["meshes"])
    assert len(after["materials"]) == len(before["materials"])
    assert after["scenes"][0]["extras"] == before["scenes"][0]["extras"]


@needs_node
def test_decoder_is_available_to_ship(tmp_path):
    assert optimize.copy_decoder(tmp_path)
    assert (tmp_path / "vendor" / "draco" / "draco_decoder.wasm").exists()
