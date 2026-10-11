"""Pişirilmiş ortam ışığı gölgelemesi (AO).

AO burada bir "efekt" değil, **ölçülebilir bir geometri büyüklüğü**: bir yüzey
noktasının çevresindeki katı oranı. Testler o tanımın karşılığını kilitliyor —
düzlem kararmaz, iç köşe kararır, delik dibi en çok kararır, dış kenar hiç
kararmaz. Bu dört kural tutuyorsa sonuç girintileri doğru yerden karartıyordur.
"""
import numpy as np
import pytest
import trimesh

from cad import ao, gltf
from cad.families import ball_valve


# --------------------------------------------------------------------------- #
# Geometriler
# --------------------------------------------------------------------------- #

def box(size, center=(0, 0, 0)):
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation(center)
    return mesh


@pytest.fixture(scope="module")
def ell():
    """L profili: iç köşesi olan en basit katı."""
    a = box((40, 40, 20), (0, 0, 0))
    b = box((40, 20, 40), (0, -10, 20))
    return trimesh.boolean.union([a, b])


@pytest.fixture(scope="module")
def drilled():
    """Kör delikli blok: deliğin dibi, dış yüzeyden belirgin koyu olmalı."""
    block = box((60, 60, 60))
    hole = trimesh.creation.cylinder(radius=5, height=50)
    hole.apply_translation((0, 0, 10))          # z = -15 .. +35, dibi -15'te
    return trimesh.boolean.difference([block, hole])


# --------------------------------------------------------------------------- #
# Tanımın karşılığı
# --------------------------------------------------------------------------- #

def test_flat_surface_is_not_darkened():
    """Düzlemde çevrenin yarısı katıdır; tanım gereği AO = 1."""
    mesh = box((60, 60, 60))
    points = np.array([[0.0, 0.0, 30.0], [0.0, 30.0, 0.0], [30.0, 0.0, 0.0]])
    values = ao.bake(mesh, points)
    assert values is not None
    assert (values > 0.95).all(), values


def test_convex_corner_is_not_darkened():
    """Dış köşede çevrenin dörtte biri katıdır — kararma YOK (kırpılır)."""
    mesh = box((60, 60, 60))
    values = ao.bake(mesh, np.array([[30.0, 30.0, 30.0]]))
    assert values is not None and values[0] > 0.95


def test_concave_corner_is_darker_than_the_open_face(ell):
    inner = np.array([[0.0, -10.0, 10.0]])     # iç köşe
    outer = np.array([[0.0, 20.0, 0.0]])       # açık yan yüz
    dark = ao.bake(ell, inner)
    light = ao.bake(ell, outer)
    assert dark is not None and light is not None
    assert dark[0] < light[0] - 0.08, (dark[0], light[0])


def test_hole_bottom_is_the_darkest_place(drilled):
    bottom = np.array([[0.0, 0.0, -15.0]])     # kör deliğin dibi
    mouth = np.array([[20.0, 20.0, 30.0]])     # delikten uzak üst yüzey
    face = np.array([[30.0, 0.0, 0.0]])        # yan dış yüzey
    deep = ao.bake(drilled, bottom)[0]
    assert deep < ao.bake(drilled, mouth)[0] - 0.2, deep
    assert deep < ao.bake(drilled, face)[0] - 0.2, deep


def test_values_stay_inside_the_contract():
    mesh = box((40, 40, 40))
    points = np.random.default_rng(0).uniform(-20, 20, size=(300, 3))
    values = ao.bake(mesh, points)
    assert values is not None
    assert values.min() >= ao.FLOOR - 1e-6 and values.max() <= 1.0 + 1e-6
    assert values.dtype == np.float32


def test_ao_is_translation_invariant(ell):
    """Parçanın KENDİ gölgesi; montajdaki yeri değiştirmemeli.

    Örnekleme buna dayanıyor: 4 cıvata tek mesh paylaşıyor, AO o mesh'e bir kez
    yazılıyor. Konuma bağlı olsaydı dördünden üçü yanlış olurdu.
    """
    points = np.array([[0.0, -10.0, 10.0], [0.0, 20.0, 0.0], [10.0, 0.0, 10.0]])
    here = ao.bake(ell, points)
    moved = ell.copy()
    moved.apply_translation((137.0, -58.0, 9.0))
    there = ao.bake(moved, points + np.array([137.0, -58.0, 9.0]))
    assert np.allclose(here, there, atol=0.02), (here, there)


def test_elongated_part_still_resolves_its_thread_scale():
    """Adım en uzun kenardan seçilseydi ince parçanın dişi ızgaraya sığmazdı.

    M16×96 bir cıvatada "en uzun kenar / 64" kuralı 1,5 mm adım veriyor; 1 mm
    derinliğindeki diş görünmez oluyordu. Hacimden seçilen adım 0,5 mm'ye
    iniyor ve diş kökü kararıyor.
    """
    shaft = trimesh.creation.cylinder(radius=8, height=96)
    groove = trimesh.creation.torus(major_radius=8, minor_radius=1.2)
    cut = trimesh.boolean.difference([shaft, groove])
    values = ao.bake(cut, np.array([[6.9, 0.0, 0.0], [8.0, 0.0, 20.0]]))
    assert values is not None
    assert values[0] < values[1] - 0.05, values


def test_degenerate_input_is_refused_not_crashed():
    mesh = box((10, 10, 10))
    assert ao.bake(mesh, np.zeros((0, 3))) is None
    assert ao.bake(mesh, np.zeros((3, 2))) is None
    flat = trimesh.Trimesh(vertices=np.zeros((3, 3)), faces=np.array([[0, 1, 2]]))
    assert ao.bake(flat, np.zeros((1, 3))) is None


# --------------------------------------------------------------------------- #
# glTF'ye yazım
# --------------------------------------------------------------------------- #

def test_color_bytes_are_grey_and_opaque():
    values = np.array([0.0, 0.5, 1.0])
    out = ao.to_color_bytes(values)
    assert out.shape == (3, 4) and out.dtype == np.uint8
    assert (out[:, 3] == 255).all()
    assert (out[:, 0] == out[:, 1]).all() and (out[:, 1] == out[:, 2]).all()
    assert out[0, 0] == 0 and out[2, 0] == 255


@pytest.fixture(scope="module")
def valve_doc():
    assembly = ball_valve.build({"dn": 25, "pn": 40, "pieces": 2, "end": "threaded"})
    return gltf.build_gltf(assembly)


def test_every_primitive_carries_baked_ao(valve_doc):
    doc, binary = valve_doc
    for mesh in doc["meshes"]:
        attributes = mesh["primitives"][0]["attributes"]
        assert "COLOR_0" in attributes, mesh["name"]
        color = doc["accessors"][attributes["COLOR_0"]]
        position = doc["accessors"][attributes["POSITION"]]
        assert color["type"] == "VEC4"
        assert color["componentType"] == gltf.UBYTE and color["normalized"]
        assert color["count"] == position["count"]


def test_ao_buffer_views_keep_four_byte_alignment(valve_doc):
    """glTF köşe niteliklerinde adım 4'ün katı olmalı; VEC3/ubyte 3 bayt eder
    ve doğrulayıcı onu HATA sayar. Bu yüzden VEC4 yazılıyor."""
    doc, binary = valve_doc
    for mesh in doc["meshes"]:
        index = mesh["primitives"][0]["attributes"]["COLOR_0"]
        view = doc["bufferViews"][doc["accessors"][index]["bufferView"]]
        assert view["byteOffset"] % 4 == 0
        assert view["byteLength"] % 4 == 0


def test_baking_can_be_turned_off():
    assembly = ball_valve.build({"dn": 25, "pn": 40, "pieces": 2, "end": "threaded"})
    doc, _ = gltf.build_gltf(assembly, bake_ao=False)
    assert all("COLOR_0" not in m["primitives"][0]["attributes"]
               for m in doc["meshes"])


def test_assembly_actually_has_darkened_vertices(valve_doc):
    """Sözleşme dolu olsa da değerler hep 1.0 olsaydı AO görünmezdi."""
    doc, binary = valve_doc
    darkest = 1.0
    for mesh in doc["meshes"]:
        accessor = doc["accessors"][mesh["primitives"][0]["attributes"]["COLOR_0"]]
        view = doc["bufferViews"][accessor["bufferView"]]
        raw = np.frombuffer(binary, dtype=np.uint8, count=view["byteLength"],
                            offset=view["byteOffset"]).reshape(-1, 4)
        darkest = min(darkest, float(raw[:, 0].min()) / 255.0)
    assert darkest < 0.75, darkest
