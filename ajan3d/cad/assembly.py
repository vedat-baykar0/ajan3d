"""Montaj veri modeli: parçalar, yerleşimler, patlatma eksenleri, kütle dökümü.

Önceki mimaride parçalama **tahminle** yapılıyordu: tek bir kabuk mesh'i
geodezik Voronoi ile bölünüyor, parça sınırları geometriden uydurulmuş oluyordu.
Burada tersi geçerli: parça **önce** vardır, montaj ondan kurulur. Her parçanın
kendi katısı, kendi malzemesi ve kendi **montaj ekseni** vardır — vida eksenine
göre çıkar, conta yuvasından çıkar, top mil ekseninde yukarı çıkar. Patlatılmış
görünüm bu yüzden bir efekt değil, montaj sırasının kendisidir.

Kavramlar:

* `Part` — tek bir imalat parçası (bir katı). Aynı parça birden fazla yerde
  bulunabilir (4 adet cıvata); bu durumda tek `mesh`, çok `Placement`.
* `Placement` — parçanın montajdaki bir örneği: konum matrisi + patlatma yönü
  + patlatma mesafesi + aşama.
* `group` — X-Ray ve arayüz davranışını belirler:
  `housing` (saydamlaşır), `internal`, `seal`, `fastener`, `actuator`.
* `stage` — patlatma sırası. 0 sabit kalır, büyük numara daha sonra ve daha
  uzağa açılır; böylece sökme sırası izlenebilir hale gelir.
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import trimesh

from cad import materials

Vec = Tuple[float, float, float]


def _unit(vec: Sequence[float]) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm > 1e-12 else np.array([0.0, 1.0, 0.0])


@dataclass
class Placement:
    """Bir parçanın montajdaki tek örneği."""
    matrix: np.ndarray = field(default_factory=lambda: np.eye(4))
    axis: Vec = (0.0, 1.0, 0.0)      # patlatma yönü (birim vektöre çevrilir)
    distance: float = 1.0            # köşegene oranla açılma mesafesi
    stage: int = 1
    suffix: str = ""                 # "1".."4" gibi örnek etiketi

    def __post_init__(self) -> None:
        self.matrix = np.asarray(self.matrix, dtype=np.float64).reshape(4, 4)
        self.axis = tuple(float(v) for v in _unit(self.axis))


@dataclass
class Part:
    """Tek bir imalat parçası."""
    id: str
    name: str
    mesh: trimesh.Trimesh
    material: str = materials.DEFAULT
    group: str = "internal"
    note: str = ""
    standard: str = ""               # ör. "DIN 933", "ISO 5211"
    placements: List[Placement] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.placements:
            self.placements = [Placement()]

    @property
    def qty(self) -> int:
        return len(self.placements)

    @property
    def volume_mm3(self) -> float:
        """Tek parçanın hacmi. Kapalı olmayan katıda 0 döner (kütle de 0)."""
        return float(abs(self.mesh.volume)) if self.mesh.is_watertight else 0.0

    @property
    def mass_g(self) -> float:
        return materials.mass_g(self.volume_mm3, self.material)

    @property
    def watertight(self) -> bool:
        return bool(self.mesh.is_watertight)


@dataclass
class Assembly:
    """Bir ürünün tam montajı."""
    family: str                      # ball_valve, gate_valve ...
    label: str                       # müşteriye gösterilecek montaj adı
    parts: List[Part] = field(default_factory=list)
    params: Dict[str, object] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    representative: bool = False     # temsili (birebir katalog ölçüsü değil)
    notes: List[str] = field(default_factory=list)

    # --- geometri özeti ---

    def add(self, part: Part) -> Part:
        self.parts.append(part)
        return part

    @property
    def bounds(self) -> np.ndarray:
        """Montajın tamamının sınır kutusu (yerleşim matrisleri uygulanmış)."""
        corners = []
        for part in self.parts:
            for place in part.placements:
                pts = trimesh.transform_points(part.mesh.bounds, place.matrix)
                corners.append(pts)
        if not corners:
            return np.zeros((2, 3))
        stacked = np.vstack(corners)
        return np.array([stacked.min(axis=0), stacked.max(axis=0)])

    @property
    def center(self) -> np.ndarray:
        return self.bounds.mean(axis=0)

    def group_bounds(self, *groups: str) -> np.ndarray:
        """Yalnız verilen grupların sınır kutusu (yerleşimler uygulanmış)."""
        corners = []
        for part in self.parts:
            if part.group not in groups:
                continue
            for place in part.placements:
                corners.append(trimesh.transform_points(part.mesh.bounds,
                                                        place.matrix))
        if not corners:
            return self.bounds
        stacked = np.vstack(corners)
        return np.array([stacked.min(axis=0), stacked.max(axis=0)])

    def flow_line(self) -> Dict[str, object]:
        """Hattın geçtiği eksen ve vananın o eksendeki İKİ UÇ YÜZEYİ.

        Sunum sayfası boruyu buraya dayar. Daha önce sayfa bu ikisini
        montajın sınır KUTUSUNDAN tahmin ediyordu ve ikisini de kaçırıyordu:

        * Yanal konum — kutunun merkezi aktüatör yüzünden yukarı kayıyordu
          (ölçüldü: delik ekseni y=0'dayken kutu merkezi y=+69 mm). Borular
          vananın deliğinden değil, gövdenin üstünden geçiyordu.
        * Eksenel uçlar — kutuya gövde cıvataları da giriyor; onlar uçlardan
          taşıyor. Bir yanda boru 31 mm gövdenin içine giriyor, öbür yanda
          arada boşluk kalıyordu.

        Sözleşme bütün ailelerde ortak (bkz. cad/families/*.py başlıkları):
        akış ekseni Z, mil +Y, eksen X=Y=0'dan geçer. Uç yüzeyler basınç
        zarfından, yani `housing` grubundan ölçülür — cıvatalar ve aktüatör
        hesaba girmez.
        """
        axis = tuple(float(v) for v in self.params.get("flow_axis", (0.0, 0.0, 1.0)))
        index = int(np.argmax(np.abs(axis)))
        shell = self.group_bounds("housing", "seal")
        return {"axis": [float(v) for v in axis],
                "origin": [0.0, 0.0, 0.0],
                "ends_mm": [float(shell[0][index]), float(shell[1][index])]}

    @property
    def size_mm(self) -> np.ndarray:
        return self.bounds[1] - self.bounds[0]

    @property
    def diagonal_mm(self) -> float:
        return float(np.linalg.norm(self.size_mm))

    @property
    def mass_g(self) -> float:
        return sum(p.mass_g * p.qty for p in self.parts)

    @property
    def face_count(self) -> int:
        return sum(len(p.mesh.faces) for p in self.parts)

    @property
    def instance_count(self) -> int:
        return sum(p.qty for p in self.parts)

    # --- doğrulama ---

    def validate(self) -> Dict[str, object]:
        """Montajın mühendislik raporu.

        `solid` oranı doğrudan eski mimarinin kusurunu ölçer: parçaların kaçı
        gerçekten kapalı bir katı. Kabuk model üretildiğinde bu sayı düşer ve
        kütle hesabı anlamsızlaşır.
        """
        leaking = [p.id for p in self.parts if not p.watertight]
        explode = self.explode_check()
        return {
            "parts": len(self.parts),
            "instances": self.instance_count,
            "solid_parts": len(self.parts) - len(leaking),
            "leaking_parts": leaking,
            "all_solid": not leaking,
            "faces": self.face_count,
            "mass_g": round(self.mass_g, 1),
            "size_mm": [round(float(v), 1) for v in self.size_mm],
            "diagonal_mm": round(self.diagonal_mm, 1),
            "explode_outward": explode["ok"],
            "explode_spread": explode["spread"],
            "explode_inward": explode["inward"],
            "warnings": list(self.warnings),
        }

    def _instance_centers(self, t: float) -> List[tuple]:
        """(parça kimliği, t anındaki parça merkezi) listesi."""
        out = []
        for part in self.parts:
            local = part.mesh.bounding_box.centroid
            for place in part.placements:
                center = trimesh.transform_points([local], place.matrix)[0]
                center = center + (np.asarray(place.axis) * place.distance
                                   * self.diagonal_mm * t)
                out.append((part.id, place, center))
        return out

    def explode_check(self) -> Dict[str, object]:
        """Patlatma parçaları gerçekten ayırıyor mu.

        İki ölçü, iki farklı hatayı yakalar:

        * **Yayılma oranı** — bütün parça merkezlerinin ortalama ikili uzaklığı
          patlatıldığında artmalı. Yönler tutarsızsa bu sayı neredeyse sabit
          kalır.
        * **İçe hareket** — hiçbir parça, montajın sabit gövdesine (aşama 0)
          yaklaşmamalı. Ters verilmiş bir eksen parçayı gövdenin içine sürer.

        Daha önce bu kontrol sınır kutusunun merkezine göre yapılıyordu ve
        yanlış alarm veriyordu: uzun bir volan merkezi yukarı çekince, kapağın
        altındaki cıvatalar "merkeze doğru" hareket ediyormuş gibi görünüyordu.
        Sabit gövdeyi referans almak bu karışıklığı ortadan kaldırıyor.
        """
        start = self._instance_centers(0.0)
        end = self._instance_centers(1.0)
        if len(start) < 2:
            return {"ok": True, "spread": 1.0, "inward": []}

        def mean_pairwise(points) -> float:
            arr = np.array([p[2] for p in points])
            diff = arr[:, None, :] - arr[None, :, :]
            dist = np.linalg.norm(diff, axis=-1)
            n = len(arr)
            return float(dist.sum() / max(1, n * (n - 1)))

        spread = mean_pairwise(end) / max(1e-6, mean_pairwise(start))

        anchor = None
        for part in self.parts:
            for place in part.placements:
                if place.stage == 0 and place.distance == 0:
                    anchor = trimesh.transform_points(
                        [part.mesh.bounding_box.centroid], place.matrix)[0]
                    break
            if anchor is not None:
                break
        if anchor is None:
            anchor = self.center

        inward = []
        for (pid, place, c0), (_, _, c1) in zip(start, end):
            if place.distance <= 0:
                continue
            before = float(np.linalg.norm(c0 - anchor))
            after = float(np.linalg.norm(c1 - anchor))
            if after < before - self.diagonal_mm * 0.01:
                inward.append(pid + (f"_{place.suffix}" if place.suffix else ""))
        return {"ok": spread > 1.25 and not inward,
                "spread": round(spread, 3), "inward": inward}

    # --- arayüz için parça kataloğu ---

    def explode_overlaps(self, clearance: float = 0.0) -> List[Dict[str, object]]:
        """Tam patlamış hâlde BİRBİRİNE GİREN parça örnekleri.

        Patlatmanın okunur olması tek şarta bağlı: açılan parçalar birbirinin
        içinde durmayacak. Ölçülmeden yazılan mesafeler bunu sessizce bozuyor
        ve ekranda "parçalar havada, rastgele" görünüyordu. Ölçülen iki örnek:
        küre 0,18 köşegen aşağı gidince gövdenin tabanının içinde kalıyordu;
        salmastra bileziği ile yaylı rondela aynı 5 mm'ye oturuyordu.

        İki aşamalı: önce sınır kutusu ELEMESİ, hayatta kalan çiftlerde
        GERÇEK kesişim hacmi. Yalnız sınır kutusuna bakmak işe yaramıyordu —
        bu ürünün yarısı eş eksenli: salmastra halkası milin ETRAFINDA, gövde
        cıvatası kapağın YANINDA durur; kutuları çakışır ama katıları
        çakışmaz. Kutu elemesi 741 çiftten 7'sini bırakıyor, gerisini kesin
        hesaplamak ucuz.
        """
        placed = []
        for part in self.parts:
            for place in part.placements:
                offset = (np.array(place.axis, dtype=np.float64)
                          * place.distance * self.diagonal_mm)
                matrix = place.matrix.copy()
                matrix[:3, 3] += offset
                pts = trimesh.transform_points(part.mesh.bounds, matrix)
                placed.append((f"{part.id}{place.suffix}", part.mesh, matrix,
                               pts.min(axis=0), pts.max(axis=0)))
        pad = clearance * self.diagonal_mm
        floor = (self.diagonal_mm * 0.004) ** 3      # sayısal gürültü eşiği
        hits = []
        for i in range(len(placed)):
            name_a, mesh_a, mat_a, lo_a, hi_a = placed[i]
            for j in range(i + 1, len(placed)):
                name_b, mesh_b, mat_b, lo_b, hi_b = placed[j]
                if not np.all(np.minimum(hi_a, hi_b)
                              - np.maximum(lo_a, lo_b) - pad > 0):
                    continue
                solid_a = mesh_a.copy(); solid_a.apply_transform(mat_a)
                solid_b = mesh_b.copy(); solid_b.apply_transform(mat_b)
                try:
                    shared = trimesh.boolean.intersection([solid_a, solid_b])
                except Exception:          # çözücü düşerse kutuya güven
                    shared = None
                volume = (float(shared.volume)
                          if shared is not None and not shared.is_empty else 0.0)
                if volume > floor:
                    hits.append({"a": name_a, "b": name_b,
                                 "volume_mm3": round(volume, 1)})
        return hits

    def catalog(self) -> List[Dict[str, object]]:
        """Sunum sayfasındaki parça listesi/tablosu için düz veri."""
        out = []
        for index, part in enumerate(self.parts, 1):
            mat = materials.get(part.material)
            out.append({
                "no": index,
                "id": part.id,
                "name": part.name,
                "qty": part.qty,
                "group": part.group,
                "material": part.material,
                "material_label": mat.label,
                "note": part.note,
                "standard": part.standard,
                "volume_cm3": round(part.volume_mm3 / 1000.0, 2),
                "mass_g": round(part.mass_g, 1),
                "total_mass_g": round(part.mass_g * part.qty, 1),
                "watertight": part.watertight,
            })
        return out

    def material_summary(self) -> List[Dict[str, object]]:
        """Malzemeye göre kütle dökümü (ağırdan hafife)."""
        totals: Dict[str, float] = {}
        for part in self.parts:
            totals[part.material] = totals.get(part.material, 0.0) + part.mass_g * part.qty
        rows = [{"material": k, "label": materials.get(k).label, "mass_g": round(v, 1)}
                for k, v in totals.items()]
        return sorted(rows, key=lambda r: -r["mass_g"])


# --------------------------------------------------------------------------- #
# Yerleşim yardımcıları
# --------------------------------------------------------------------------- #

def at(x: float = 0.0, y: float = 0.0, z: float = 0.0, *, axis: Vec = (0, 1, 0),
       distance: float = 1.0, stage: int = 1, suffix: str = "",
       rotation: Optional[Tuple[float, str]] = None) -> Placement:
    """Ötelemeli (ve istenirse döndürmeli) yerleşim."""
    matrix = np.eye(4)
    if rotation is not None:
        degrees, axis_name = rotation
        vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis_name]
        matrix = trimesh.transformations.rotation_matrix(math.radians(degrees), vec)
    matrix[:3, 3] += np.array([x, y, z], dtype=np.float64)
    return Placement(matrix=matrix, axis=axis, distance=distance, stage=stage,
                     suffix=suffix)


def ring(points: Sequence[Tuple[float, float]], z: float = 0.0, *,
         radial: bool = False, axis: Vec = (0, 0, 1), distance: float = 1.0,
         stage: int = 1) -> List[Placement]:
    """Delik dairesi üzerindeki noktalara aynı parçayı yerleştirir.

    `radial=True` ise her örneğin patlatma yönü kendi merkez-dışı doğrultusudur
    (ör. flanş cıvataları dışa yelpaze açar); aksi halde verilen eksen kullanılır.
    """
    out = []
    for index, (x, y) in enumerate(points, 1):
        direction = axis
        if radial:
            norm = math.hypot(x, y) or 1.0
            direction = (x / norm, y / norm, 0.0)
        out.append(at(x, y, z, axis=direction, distance=distance, stage=stage,
                      suffix=str(index)))
    return out
