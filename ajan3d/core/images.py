"""Klasördeki fotoğrafları bulma, temsilci seçme ve token tasarrufu için küçültme."""
import base64
import io
from pathlib import Path
from typing import List

from PIL import Image, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def list_images(folder: Path) -> List[Path]:
    """Klasördeki tüm desteklenen fotoğrafları isim sırasıyla döner (alt klasörlere inmez)."""
    images = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS),
        key=lambda p: p.name.lower(),
    )
    if not images:
        raise FileNotFoundError(f"'{folder}' içinde fotoğraf bulunamadı ({', '.join(sorted(IMAGE_EXTS))})")
    return images


def pick_representatives(images: List[Path], count: int) -> List[Path]:
    """Analiz için temsilci fotoğrafları seçer.

    İlk fotoğraf + dizinin ortasındaki fotoğraf: müşteriler genelde objenin
    etrafında dönerek çeker, bu yüzden ortadaki kare çoğunlukla farklı bir
    açıdır (ör. arka taraf) ve ikinci bir 'ilk' kareden daha fazla bilgi verir.
    """
    count = max(1, min(count, len(images)))
    if count == 1:
        return [images[0]]
    step = len(images) / count
    return [images[int(i * step)] for i in range(count)]


def encode_for_vision(path: Path, max_side: int) -> str:
    """Fotoğrafı uzun kenarı max_side olacak şekilde küçültüp base64 JPEG döner.

    Görsel token maliyeti piksel sayısıyla orantılıdır (~genişlik*yükseklik/750).
    12 MP bir telefon fotoğrafı yerine 1024 px göndermek, nesne tanıma kalitesini
    düşürmeden maliyeti kat kat azaltır. Anthropic görseli base64 beklediği için
    ham bayt değil kodlanmış dize döner.
    """
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)  # telefon fotoğraflarındaki dönüş bilgisini uygula
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")
