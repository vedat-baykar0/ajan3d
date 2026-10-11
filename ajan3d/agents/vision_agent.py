"""1. Tanıma Ajanı (Vision) — Anthropic Claude.

**Bu ajan 3D geometri üretmez ve üretmeye çalışmaz.** Fotoğrafın tek görevi
ürünün *kimliğini* söylemektir: hangi tip, hangi anma çapı, hangi basınç
sınıfı, hangi gövde malzemesi, hangi bağlantı ve kumanda, kaç parçalı gövde,
üstünde hangi damgalar yazıyor.

Neden böyle: Image-to-3D ağları ürünün yalnızca dış kabuğunu üretir. İçinin
dolu olduğunu, vidanın nereye girdiğini, contanın hangi yuvaya oturduğunu
bilemez — o bilgi fotoğrafta zaten yoktur. Kabuğu parçalamaya kalkınca kâğıt
gibi yırtılıyordu. Oysa ürünün *ne olduğu* bilinirse geometri, standart ölçü
tablolarından ve parametrik CAD çekirdeğinden **doğru** kurulabiliyor. Bu
yüzden fotoğraf artık sınıflandırma girdisidir, modelleme girdisi değil.

Pratik sonucu: artık fotoğraf sayısı ve açısı kalite için belirleyici değil;
belirleyici olan damgaların okunabilmesi. Bu yüzden eskiye göre daha çok
fotoğraf (3) ve daha yüksek çözünürlük (1280 px) gönderiliyor — maliyeti
kabul edilebilir, kazancı doğrudan ölçü tespiti.
"""
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import anthropic

from core.config import MODEL_PRICES, settings
from core.images import encode_for_vision, list_images, pick_representatives
from core.schemas import ProductIdentity

MAX_TOKENS = 12000
# Güvenlik filtresi isteği reddederse API aynı istek içinde uygun bir modele düşer.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """Sen endüstriyel ürün tanıma uzmanısın. Sana bir ürünün \
fotoğrafları veriliyor. Görevin ürünün TEKNİK KİMLİĞİNİ çıkarmak.

Bu bilgi, ürünün parametrik CAD modelini standart ölçü tablolarından kurmak \
için kullanılacak. Yani ne kadar kesin olursan model o kadar doğru çıkar.

Yapman gerekenler:
- Ürünün tam tipini belirle (ör: "3 parçalı tam geçişli küresel vana").
- Ürün üzerindeki BÜTÜN yazı ve damgaları oku: döküm kodu (CF8M, WCB), anma \
ölçüsü (DN50, 2"), basınç (PN40, 1000 WOG, CLASS 150), marka, parti numarası. \
Bunları markings alanına ham haliyle yaz.
- Anma ölçüsünü damgadan okuyamazsan oranlardan tahmin et (flanş çapı / boru \
çapı / el aleti karşılaştırması). Tahminse yine yaz, boş bırakma.
- Bağlantı tipini (flanşlı, dişli, kaynaklı, wafer, clamp) ve kumanda tipini \
(kol, volan, redüktör, pnömatik) söyle.
- Küresel vanada gövdenin kaç parçadan oluştuğunu say: gövde cıvatası varsa ve \
iki uç kapak ayrıysa 3 parçalıdır.
- family_hint alanında verilen listeden EN UYGUN aileyi seç. Ürün listedeki \
hiçbir aileye girmiyorsa 'other' seç; zorlama.
- GÖRMEDİĞİN şeyi uydurma. Emin olmadığın alanı boş bırak ve identification \
içinde bunu belirt.
- Fotoğraf bulanıksa, parlama damgayı siliyorsa veya birden fazla ürün varsa \
identification.issues alanında bildir.
- Müşteriye gösterilecek metinleri ({language}) yaz; markings ham kalsın."""


class VisionError(RuntimeError):
    """Tanıma adımının kullanıcıya gösterilebilir hatası.

    Mesaj metni `core/pipeline.py` tarafından geçici/kalıcı ayrımı için taranır;
    geçici hatalarda "geçici" veya "hız sınırı" gibi ipucu kelimeler bulunur.
    """


@dataclass
class VisionRunInfo:
    analyzed_images: List[str]
    total_images: int
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    seconds: float


def build_client() -> anthropic.Anthropic:
    if not settings.anthropic_api_key or settings.anthropic_api_key.endswith("..."):
        raise VisionError(r"ANTHROPIC_API_KEY ayarlı değil — ajan3d\.env dosyasına ekleyin")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _content(chosen: List[Path]) -> list:
    blocks: list = []
    for i, path in enumerate(chosen, 1):
        blocks.append({"type": "text", "text": f"Fotoğraf {i}:"})
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": encode_for_vision(path, settings.vision_max_side),
            },
        })
    blocks.append({"type": "text",
                   "text": "Bu ürünün teknik kimliğini çıkar. Damgaları oku."})
    return blocks


def _call(client: anthropic.Anthropic, blocks: list):
    """Claude'u çağırır; API hatalarını okunabilir VisionError'a çevirir."""
    try:
        return client.beta.messages.parse(
            model=settings.vision_model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT.format(language=settings.output_language),
            messages=[{"role": "user", "content": blocks}],
            output_format=ProductIdentity,
            output_config={"effort": settings.vision_effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise VisionError(f"Anthropic API anahtarı geçersiz (.env -> ANTHROPIC_API_KEY). {e}") from e
    except anthropic.PermissionDeniedError as e:
        raise VisionError(
            f"API anahtarı bu isteğe yetkili değil; plan/kredi kontrolü gerekebilir. {e}"
        ) from e
    except anthropic.NotFoundError as e:
        raise VisionError(
            f"Model bulunamadı: {settings.vision_model}. ajan3d\\.env içinde VISION_MODEL "
            f"değerini geçerli bir modelle değiştirin (ör. claude-sonnet-5-5). {e}"
        ) from e
    except anthropic.RateLimitError as e:
        after = e.response.headers.get("retry-after") if e.response is not None else None
        extra = f" (retry-after: {after} sn)" if after else ""
        raise VisionError(f"Anthropic hız sınırına takıldı{extra}; sonra tekrar denenecek.") from e
    except anthropic.BadRequestError as e:
        # Kredi bakiyesi hatası da 400 ile gelir; genel "istek reddedildi" mesajı
        # bunu gizliyor ve panelde ne yapılacağı anlaşılmıyor.
        if "credit balance" in str(e).lower():
            raise VisionError(
                "Anthropic hesabının kredi bakiyesi yetersiz. Anahtar geçerli, sorun "
                "faturalama: console.anthropic.com -> Plans & Billing bölümünden kredi "
                "yükleyin. (Kredi yükledikten sonra BLOCKED işleri sıfırlamak gerekir.)"
            ) from e
        raise VisionError(f"Anthropic isteği reddetti (kalıcı hata): {e}") from e
    except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
        raise VisionError(f"Anthropic API'ye bağlanılamadı (geçici): {e}") from e
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            raise VisionError(f"Anthropic sunucu hatası {e.status_code} (geçici): {e.message}") from e
        raise VisionError(f"Anthropic API hatası {e.status_code}: {e.message}") from e


def _parse(response) -> ProductIdentity:
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None) if response.stop_details else None
        raise VisionError(f"Model tanımayı reddetti (kategori: {category})")
    if response.stop_reason == "max_tokens":
        raise VisionError(f"Yanıt {MAX_TOKENS} token sınırında kesildi; sınırı artırın")
    result = response.parsed_output
    if result is None:
        raise VisionError(f"Yapılandırılmış çıktı alınamadı (stop_reason={response.stop_reason})")
    return result


def identify_folder(
    folder: Path, client: Optional[anthropic.Anthropic] = None
) -> tuple[ProductIdentity, VisionRunInfo]:
    folder = Path(folder)
    all_images = list_images(folder)
    chosen = pick_representatives(all_images, settings.vision_max_images)

    client = client or build_client()
    started = time.perf_counter()
    response = _call(client, _content(chosen))
    elapsed = time.perf_counter() - started

    result = _parse(response)

    usage = response.usage
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    # Fallback devreye girdiyse yanıtı veren model istenenden farklı olabilir.
    served_model = getattr(response, "model", None) or settings.vision_model
    in_price, out_price = MODEL_PRICES.get(
        served_model, MODEL_PRICES.get(settings.vision_model, (0.0, 0.0))
    )

    info = VisionRunInfo(
        analyzed_images=[p.name for p in chosen],
        total_images=len(all_images),
        model=served_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round((input_tokens * in_price + output_tokens * out_price) / 1_000_000, 5),
        seconds=round(elapsed, 1),
    )
    return result, info


def save_metadata(job_dir: Path, source_folder: Path, result: ProductIdentity,
                  info: VisionRunInfo) -> Path:
    job_dir.mkdir(parents=True, exist_ok=True)
    out = job_dir / "metadata.json"
    payload = {
        "source_folder": str(Path(source_folder).resolve()),
        "identity": result.model_dump(),
        "vision_run": info.__dict__,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
