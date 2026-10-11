"""GLB yazıcısı: kap geçerliliği, normal bölme ve patlatma sözleşmesi.

Sunum sayfası GLB'yi yalnızca "yüklenebilir bir model" olarak değil, bir
**veri sözleşmesi** olarak okuyor: her düğümün `extras` alanındaki pid / grp /
ax / d / st olmadan ne parçalama ne X-Ray ne de parça listesi çalışır. Bu
yüzden sözleşme burada kilitli.
"""
import json
import math
import struct

import numpy as np
import pytest
import trimesh

from cad import gltf, primitives as P
from cad.assembly import Assembly, Part, at, ring
from cad.families import ball_valve


@pytest.fixture(scope="module")
def valve():
    return ball_valve.build({"dn": 50, "pn": 40, "pieces": 3, "end": "threaded"})


@pytest.fixture(scope="module")
def packed(valve):
    doc, binary = gltf.build_gltf(valve)
    return doc, binary, gltf.pack_glb(doc, binary)


# --------------------------------------------------------------------------- #
# Kap
# --------------------------------------------------------------------------- #

def test_glb_header_and_chunks(packed):
    _, _, data = packed
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2
    assert length == len(data)
    json_len, json_type = struct.unpack_from("<II", data, 12)
    assert json_type == 0x4E4F534A
    bin_len, bin_type = struct.unpack_from("<II", data, 12 + 8 + json_len)
    assert bin_type == 0x004E4942
    assert (json_len % 4 == 0) and (bin_len % 4 == 0)


def test_buffer_views_are_four_byte_aligned(packed):
    doc, binary, _ = packed
    for view in doc["bufferViews"]:
        assert view["byteOffset"] % 4 == 0
        assert view["byteOffset"] + view["byteLength"] <= len(binary)
    assert doc["buffers"][0]["byteLength"] == len(binary)


def test_position_accessors_carry_min_max(packed):
    doc, _, _ = packed
    for mesh in doc["meshes"]:
        position = mesh["primitives"][0]["attributes"]["POSITION"]
        accessor = doc["accessors"][position]
        assert len(accessor["min"]) == 3 and len(accessor["max"]) == 3
        assert all(lo <= hi for lo, hi in zip(accessor["min"], accessor["max"]))


def test_identity_matrices_are_omitted(packed):
    """Birim matris yazmak doğrulayıcıda gereksiz bilgi uyarısı üretiyor."""
    doc, _, _ = packed
    for node in doc["nodes"]:
        if "matrix" in node:
            assert not np.allclose(np.array(node["matrix"]).reshape(4, 4), np.eye(4))


def test_round_trip_through_reader(packed):
    doc, binary, data = packed
    again, again_bin = gltf.read_glb(data)
    assert again["meshes"] == doc["meshes"]
    assert again_bin == binary


# --------------------------------------------------------------------------- #
# Sözleşme
# --------------------------------------------------------------------------- #

def test_every_part_node_carries_the_explode_contract(packed, valve):
    doc, _, _ = packed
    nodes = [n for n in doc["nodes"] if "extras" in n]
    assert len(nodes) == valve.instance_count
    for node in nodes:
        extras = node["extras"]
        assert set(extras) == {"pid", "grp", "ax", "d", "st"}
        assert len(extras["ax"]) == 3
        assert math.isclose(sum(v * v for v in extras["ax"]) ** 0.5, 1.0, abs_tol=1e-4)
        assert extras["grp"] in ("housing", "internal", "seal", "fastener", "actuator")
        assert isinstance(extras["st"], int)


def test_instances_share_one_mesh(packed):
    """Dört cıvata tek mesh, dört düğüm olmalı; aksi halde dosya şişiyor."""
    doc, _, _ = packed
    bolts = [n for n in doc["nodes"]
             if n.get("extras", {}).get("pid") == "govde_civatasi"]
    assert len(bolts) == 4
    assert len({n["mesh"] for n in bolts}) == 1


def test_root_node_scales_millimetres_to_metres(packed):
    doc, _, _ = packed
    root = doc["nodes"][doc["scenes"][0]["nodes"][0]]
    matrix = np.array(root["matrix"]).reshape(4, 4).T
    assert np.allclose(np.diag(matrix)[:3], gltf.MM_TO_M)
    assert "children" in root and len(root["children"]) > 1


def test_scene_extras_describe_the_assembly(packed, valve):
    doc, _, _ = packed
    extras = doc["scenes"][0]["extras"]
    assert extras["family"] == "ball_valve"
    assert extras["diagonal_mm"] == pytest.approx(valve.diagonal_mm, rel=1e-3)
    assert extras["representative"] is False


# --------------------------------------------------------------------------- #
# Normal bölme
# --------------------------------------------------------------------------- #

def test_smooth_surface_shares_normals():
    """Devirme yüzeyi tek kümeye girmeli; aksi halde silindir fasetli görünür."""
    cylinder = P.cylinder(10, 30)
    vertices, _, _ = gltf.corner_normals(cylinder)
    welded = cylinder.copy()
    welded.merge_vertices()
    # Yan yüzey paylaşılır, yalnız kapak kenarları çoğalır
    assert len(vertices) < len(cylinder.faces) * 3 * 0.75


def test_sharp_edges_get_separate_normals():
    box = P.box(10, 10, 10)
    vertices, normals, faces = gltf.corner_normals(box)
    assert len(vertices) == 24                 # 8 köşe × 3 yüz yönü
    assert np.allclose(np.linalg.norm(normals, axis=1), 1.0)


def test_all_normals_are_unit_length(valve):
    """Dejenere yüzlerin sıfır normali glTF'de geçersizdir."""
    for part in valve.parts:
        _, normals, _ = gltf.corner_normals(part.mesh)
        lengths = np.linalg.norm(normals, axis=1)
        assert np.allclose(lengths, 1.0, atol=1e-4), part.id


def test_face_count_is_preserved(valve):
    for part in valve.parts:
        _, _, faces = gltf.corner_normals(part.mesh)
        assert len(faces) == len(part.mesh.faces)
        assert faces.max() >= 0


def test_degenerate_faces_do_not_crash_the_writer():
    """Devirme ekseninde sıfır alanlı üçgenler kalıyor; normali sıfır vektör."""
    mesh = P.cylinder(10, 20)
    mesh.vertices = np.vstack([mesh.vertices, mesh.vertices[0]])
    mesh.faces = np.vstack([mesh.faces, [0, 0, len(mesh.vertices) - 1]])
    vertices, normals, _ = gltf.corner_normals(mesh)
    assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-4)


# --------------------------------------------------------------------------- #
# Malzeme
# --------------------------------------------------------------------------- #

def test_materials_are_written_in_linear_space(packed):
    doc, _, _ = packed
    assert doc["materials"], "malzeme yazılmamış"
    for material in doc["materials"]:
        pbr = material["pbrMetallicRoughness"]
        assert len(pbr["baseColorFactor"]) == 4
        assert 0.0 <= pbr["metallicFactor"] <= 1.0
        assert 0.0 < pbr["roughnessFactor"] <= 1.0


def test_srgb_to_linear_matches_the_standard_curve():
    assert gltf.srgb_to_linear(0.0) == 0.0
    assert gltf.srgb_to_linear(1.0) == pytest.approx(1.0)
    assert gltf.srgb_to_linear(0.5) == pytest.approx(0.2140, abs=1e-3)


def test_each_material_is_written_once(packed, valve):
    doc, _, _ = packed
    used = {p.material for p in valve.parts}
    assert len(doc["materials"]) == len(used)


# --------------------------------------------------------------------------- #
# Hazır GLB'ye sözleşme ekleme (yerel kütüphane yolu)
# --------------------------------------------------------------------------- #

def test_patch_extras_adds_contract_without_touching_geometry(packed):
    doc, binary, data = packed
    patched = gltf.patch_extras(
        data, {"top": {"pid": "top", "grp": "internal", "ax": [0, 1, 0],
                       "d": 0.5, "st": 2}},
        scene_extras={"label": "yerel"})
    new_doc, new_bin = gltf.read_glb(patched)
    assert new_bin == binary                       # geometri aynı
    node = next(n for n in new_doc["nodes"] if n.get("name") == "top")
    assert node["extras"]["d"] == 0.5
    assert new_doc["scenes"][0]["extras"]["label"] == "yerel"


def test_reader_rejects_non_glb():
    with pytest.raises(ValueError):
        gltf.read_glb(b"not a glb file at all, really")


def test_node_names_are_listed(packed):
    _, _, data = packed
    names = gltf.node_names(data)
    assert "govde" in names and "govde_civatasi_1" in names


# --------------------------------------------------------------------------- #
# Patlatma doğrulaması
# --------------------------------------------------------------------------- #

def test_reversed_axis_is_reported_as_inward():
    """Ters verilmiş eksen parçayı gövdenin içine sürer; yakalanmalı."""
    body = Part(id="govde", name="Gövde", mesh=P.cylinder(20, 40),
                placements=[at(stage=0, distance=0.0)])
    good = Part(id="kapak", name="Kapak", mesh=P.cylinder(20, 6, 40),
                placements=[at(0, 0, 40, axis=(0, 0, 1), distance=0.8, stage=1)])
    bad = Part(id="kapak", name="Kapak", mesh=P.cylinder(20, 6, 40),
               placements=[at(0, 0, 40, axis=(0, 0, -1), distance=0.8, stage=1)])
    assert Assembly("t", "t", [body, good]).explode_check()["ok"]
    report = Assembly("t", "t", [body, bad]).explode_check()
    assert not report["ok"] and "kapak" in report["inward"]


def test_explode_increases_separation(valve):
    report = valve.explode_check()
    assert report["spread"] > 1.4, "patlatma parçaları yeterince ayırmıyor"
    assert report["inward"] == []
