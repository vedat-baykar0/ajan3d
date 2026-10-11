"""Montajı GLB'ye yazar — düğüm başına parça, parça başına montaj ekseni.

Neden kendi yazıcısı: `trimesh` bir sahneyi dışa aktarabiliyor ama (a) parça
başına `extras` yazamıyor, (b) PBR değerlerini bizim istediğimiz gibi kurmuyor,
(c) açı bölünmüş normal üretmiyor. Üçü de bu projede sonucu doğrudan belirliyor.

**Açı bölünmüş normaller.** CAD görünümünün sırrı budur. Köşeleri tamamen
kaynaştırmak (yumuşak gölgeleme) pahları ve kenarları eritir, silindirle düzlem
arasındaki keskin geçiş kaybolur — parça plastikten dökülmüş gibi görünür. Her
üçgeni ayırmak (düz gölgeleme) ise devirme yüzeylerini fasetli gösterir. Doğru
yol ikisinin arası: bir köşede buluşan yüzler **aralarındaki açıya göre**
kümelenir; 30°'den az açılı komşular tek normal paylaşır (pürüzsüz silindir),
fazlası ayrı normal alır (keskin pah). Köşe yalnızca gerçekten gerektiğinde
çoğaltıldığı için dosya da düz gölgelemenin üçte biri kadar büyür.

**Birim ve eksen.** Parçalar milimetre cinsinden kurulur; kök düğüm 0.001
ölçek ve merkeze alma taşır, yani sahne glTF geleneğine uygun metre cinsinden
ve orijinde ortalanmış olur. Patlatma ötelemeleri kök düğümün ALTINDA, yani
hâlâ milimetre cinsinden uygulanır (`diagonal_mm` bu yüzden extras'ta).

**Düğüm extras sözleşmesi** (sunum sayfası bunu okur):
    pid  parça kimliği     ax  patlatma yönü [x,y,z]
    d    mesafe çarpanı    st  patlatma aşaması        grp  X-Ray grubu

**Pişirilmiş AO.** Her köşeye, parçanın kendi girintilerinden hesaplanmış
ortam gölgelemesi `COLOR_0` olarak yazılır (`cad/ao.py`). Çalışma zamanı
maliyeti sıfırdır ve örnekleme güvenlidir — 4 cıvata hâlâ tek mesh paylaşır.
İsteğe bağlıdır: hesaplanamazsa nitelik hiç yazılmaz, sayfa AO'suz çalışır.
"""
import json
import math
import struct
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import trimesh

from cad import ao as ao_bake
from cad import materials
from cad.assembly import Assembly

GENERATOR = "ajan3d parametrik CAD"
# Bu açıdan dar komşu yüzler tek normal paylaşır (pürüzsüz), geniş olanlar ayrılır.
SMOOTH_ANGLE = 30.0
MM_TO_M = 0.001

# glTF sabitleri
FLOAT = 5126
UBYTE = 5121
USHORT = 5123
UINT = 5125


# --------------------------------------------------------------------------- #
# Normal bölme
# --------------------------------------------------------------------------- #

def corner_normals(mesh: trimesh.Trimesh,
                   angle: float = SMOOTH_ANGLE) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(köşeler, normaller, yüzler) — köşeler yalnızca gereken yerde çoğaltılır.

    Her köşede buluşan yüzler, normalleri arasındaki açı `angle`'dan küçükse
    aynı kümeye girer. Küme sayısı o köşeden üretilecek kopya sayısıdır.

    Hız: köşelerin büyük bölümü iki uç durumdan birine girer — ya bütün komşu
    yüzler pürüzsüz (devirme yüzeyi) ya da hiçbiri (kutu köşesi). İkisi de
    küme hesabı yapılmadan geçilir; yalnızca karışık köşeler için küçük
    bitişiklik matrisi üzerinde etiket yayılımı çalışır.
    """
    faces = np.asarray(mesh.faces)
    fnormals = np.asarray(mesh.face_normals, dtype=np.float64)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    cos_limit = math.cos(math.radians(angle))

    flat = faces.reshape(-1)
    face_ids = np.repeat(np.arange(len(faces)), 3)
    order = np.argsort(flat, kind="stable")
    flat, face_ids = flat[order], face_ids[order]
    starts = np.searchsorted(flat, np.arange(len(vertices)), side="left")
    ends = np.searchsorted(flat, np.arange(len(vertices)), side="right")

    out_vertices: List[np.ndarray] = []
    out_normals: List[np.ndarray] = []
    out_faces = np.zeros((len(faces), 3), dtype=np.int64)

    for vertex in range(len(vertices)):
        incident = face_ids[starts[vertex]:ends[vertex]]
        count = len(incident)
        if count == 0:
            continue
        normals = fnormals[incident]
        if count == 1:
            clusters = [[0]]
        else:
            adjacency = (normals @ normals.T) >= cos_limit
            # Köşegen zorla doğru: devirme ekseninde sıfır alanlı üçgenler
            # kalıyor ve onların normali sıfır vektör oluyor, yani yüz kendi
            # kendisiyle bile "pürüzsüz" sayılmıyordu ve küme boş kalıyordu.
            np.fill_diagonal(adjacency, True)
            if adjacency.all():                             # tamamen pürüzsüz
                clusters = [list(range(count))]
            elif adjacency.sum() == count:                  # tamamen keskin
                clusters = [[i] for i in range(count)]
            else:
                labels = np.arange(count)
                for _ in range(count):
                    changed = False
                    for i in range(count):
                        lowest = labels[adjacency[i]].min()
                        if lowest < labels[i]:
                            labels[labels == labels[i]] = lowest
                            changed = True
                    if not changed:
                        break
                clusters = [np.flatnonzero(labels == label).tolist()
                            for label in np.unique(labels)]

        for members in clusters:
            accumulated = normals[members].sum(axis=0)
            length = float(np.linalg.norm(accumulated))
            # glTF birim normal ister; dejenere yüzlerin normali sıfırdır,
            # bunlar görünmez olduğu için sabit bir yön yeterli.
            normal = accumulated / length if length > 1e-9 else np.array([0.0, 0.0, 1.0])
            index = len(out_vertices)
            out_vertices.append(vertices[vertex])
            out_normals.append(normal)
            for member in members:
                face = incident[member]
                corner = int(np.flatnonzero(faces[face] == vertex)[0])
                out_faces[face, corner] = index

    return (np.asarray(out_vertices, dtype=np.float32),
            np.asarray(out_normals, dtype=np.float32),
            out_faces)


# --------------------------------------------------------------------------- #
# Renk uzayı
# --------------------------------------------------------------------------- #

def srgb_to_linear(value: float) -> float:
    """glTF `baseColorFactor` LİNEER ister; malzeme tablosu sRGB tutar."""
    value = max(0.0, min(1.0, float(value)))
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


# --------------------------------------------------------------------------- #
# GLB yazıcı
# --------------------------------------------------------------------------- #

class _Buffer:
    """Tek ikili tampon; her görünüm 4 bayta hizalanır (glTF şartı)."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.views: List[dict] = []

    def add(self, payload: bytes, target: Optional[int] = None) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        offset = len(self.data)
        self.data.extend(payload)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        self.views.append(view)
        return len(self.views) - 1


def _material_json(key: str) -> dict:
    mat = materials.get(key)
    return {
        "name": key,
        "doubleSided": False,
        "pbrMetallicRoughness": {
            "baseColorFactor": [srgb_to_linear(c) for c in mat.color] + [1.0],
            "metallicFactor": float(mat.metallic),
            "roughnessFactor": float(mat.roughness),
        },
    }


def _bake_ao(part, vertices: np.ndarray) -> Optional[np.ndarray]:
    """Parçanın köşe AO'su; hesaplanamazsa None (teslimi asla durdurmaz)."""
    try:
        return ao_bake.bake(part.mesh, vertices)
    except Exception as exc:                       # scipy yok, dejenere katı...
        part_id = getattr(part, "id", "?")
        print(f"  Uyarı: {part_id} AO pişirilemedi ({type(exc).__name__})")
        return None


def build_gltf(assembly: Assembly, bake_ao: bool = True) -> Tuple[dict, bytes]:
    """(glTF JSON, ikili tampon) üretir.

    `bake_ao` kapatılırsa `COLOR_0` hiç yazılmaz (test ve hız için).
    """
    buffer = _Buffer()
    accessors: List[dict] = []
    meshes: List[dict] = []
    nodes: List[dict] = []
    material_index: Dict[str, int] = {}
    gltf_materials: List[dict] = []

    def accessor(entry: dict) -> int:
        accessors.append(entry)
        return len(accessors) - 1

    for part in assembly.parts:
        vertices, normals, faces = corner_normals(part.mesh)
        if len(vertices) == 0 or len(faces) == 0:
            assembly.warnings.append(f"{part.id}: boş geometri, atlandı")
            continue

        position_view = buffer.add(vertices.astype("<f4").tobytes(), target=34962)
        normal_view = buffer.add(normals.astype("<f4").tobytes(), target=34962)
        small = len(vertices) <= 65535
        index_data = faces.astype("<u2" if small else "<u4").reshape(-1).tobytes()
        index_view = buffer.add(index_data, target=34963)

        position = accessor({
            "bufferView": position_view, "componentType": FLOAT,
            "count": int(len(vertices)), "type": "VEC3",
            "min": [float(v) for v in vertices.min(axis=0)],
            "max": [float(v) for v in vertices.max(axis=0)],
        })
        normal = accessor({"bufferView": normal_view, "componentType": FLOAT,
                           "count": int(len(normals)), "type": "VEC3"})
        indices = accessor({"bufferView": index_view,
                            "componentType": USHORT if small else UINT,
                            "count": int(faces.size), "type": "SCALAR"})

        attributes = {"POSITION": position, "NORMAL": normal}
        # Pişirilmiş AO isteğe bağlıdır: hesaplanamazsa parça AO'suz yazılır,
        # sayfa o parçayı 1.0 (kararma yok) kabul eder.
        occlusion = _bake_ao(part, vertices) if bake_ao else None
        if occlusion is not None:
            color_view = buffer.add(ao_bake.to_color_bytes(occlusion).tobytes(),
                                    target=34962)
            attributes["COLOR_0"] = accessor({
                "bufferView": color_view, "componentType": UBYTE,
                "count": int(len(vertices)), "type": "VEC4", "normalized": True})

        if part.material not in material_index:
            material_index[part.material] = len(gltf_materials)
            gltf_materials.append(_material_json(part.material))

        meshes.append({
            "name": part.id,
            "primitives": [{
                "attributes": attributes,
                "indices": indices,
                "material": material_index[part.material],
            }],
        })
        mesh_index = len(meshes) - 1

        for placement in part.placements:
            name = part.id + (f"_{placement.suffix}" if placement.suffix else "")
            node = {
                "name": name,
                "mesh": mesh_index,
                "extras": {
                    "pid": part.id,
                    "grp": part.group,
                    "ax": [round(float(v), 6) for v in placement.axis],
                    "d": round(float(placement.distance), 4),
                    "st": int(placement.stage),
                },
            }
            # glTF matrisi SÜTUN sıralıdır; satır sıralı numpy matrisinin
            # devriği doğrudan o sırayı verir. Birim matris yazılmaz —
            # doğrulayıcı onu gereksiz bilgi olarak işaretliyor.
            if not np.allclose(placement.matrix, np.eye(4), atol=1e-9):
                node["matrix"] = [float(v) for v in placement.matrix.T.reshape(-1)]
            nodes.append(node)

    # Kök düğüm: mm -> m ölçeği ve merkeze alma. Çocuk ötelemeleri mm kalır.
    center = assembly.center
    root = np.eye(4)
    root[:3, :3] *= MM_TO_M
    root[:3, 3] = -center * MM_TO_M
    child_indices = list(range(len(nodes)))
    nodes.append({
        "name": "assembly",
        "matrix": [float(v) for v in root.T.reshape(-1)],
        "children": child_indices,
    })
    root_index = len(nodes) - 1

    report = assembly.validate()
    gltf = {
        "asset": {"version": "2.0", "generator": GENERATOR},
        "scene": 0,
        "scenes": [{
            "nodes": [root_index],
            "extras": {
                "family": assembly.family,
                "label": assembly.label,
                "diagonal_mm": report["diagonal_mm"],
                "size_mm": report["size_mm"],
                "mass_g": report["mass_g"],
                "representative": assembly.representative,
            },
        }],
        "nodes": nodes,
        "meshes": meshes,
        "materials": gltf_materials,
        "accessors": accessors,
        "bufferViews": buffer.views,
        "buffers": [{"byteLength": len(buffer.data)}],
    }
    return gltf, bytes(buffer.data)


def pack_glb(gltf: dict, binary: bytes) -> bytes:
    """glTF JSON + ikili veriyi tek GLB kabına koyar."""
    json_chunk = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    bin_chunk = binary + b"\x00" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(json_chunk) + (8 + len(bin_chunk) if bin_chunk else 0)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
    if bin_chunk:
        out += struct.pack("<II", len(bin_chunk), 0x004E4942) + bin_chunk
    return bytes(out)


def write_glb(assembly: Assembly, path: Path, bake_ao: bool = True) -> Path:
    gltf, binary = build_gltf(assembly, bake_ao=bake_ao)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pack_glb(gltf, binary))
    return path


# --------------------------------------------------------------------------- #
# Hazır GLB'ye extras ekleme (yerel CAD kütüphanesi yolu)
# --------------------------------------------------------------------------- #

def read_glb(data: bytes) -> Tuple[dict, bytes]:
    """GLB kabını açar: (JSON, ikili bölüm)."""
    magic, version, _ = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2:
        raise ValueError("geçerli bir GLB 2.0 dosyası değil")
    offset, gltf, binary = 12, None, b""
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8:offset + 8 + length]
        if kind == 0x4E4F534A:
            gltf = json.loads(chunk.decode("utf-8"))
        elif kind == 0x004E4942:
            binary = chunk
        offset += 8 + length
    if gltf is None:
        raise ValueError("GLB içinde JSON bölümü yok")
    return gltf, binary


def patch_extras(data: bytes, mapping: Dict[str, dict],
                 scene_extras: Optional[dict] = None) -> bytes:
    """Hazır bir GLB'nin düğümlerine patlatma sözleşmesini yazar.

    Yerel CAD kütüphanesinden gelen modeller için: dosya olduğu gibi korunur,
    yalnızca `manifest.json` içinde adı geçen düğümlere `extras` eklenir.
    Böylece kütüphane modeli de parametrik modelle aynı arayüzü besler.
    """
    gltf, binary = read_glb(data)
    for node in gltf.get("nodes", []):
        extras = mapping.get(node.get("name", ""))
        if extras:
            node["extras"] = {**node.get("extras", {}), **extras}
    if scene_extras:
        scenes = gltf.setdefault("scenes", [{}])
        index = gltf.get("scene", 0)
        if index < len(scenes):
            scenes[index]["extras"] = {**scenes[index].get("extras", {}), **scene_extras}
    return pack_glb(gltf, binary)


def node_names(data: bytes) -> List[str]:
    gltf, _ = read_glb(data)
    return [node.get("name", "") for node in gltf.get("nodes", [])]
