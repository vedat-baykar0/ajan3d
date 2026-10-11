"""2. Teknik Veri Ajanı — Claude + `web_search` sunucu aracı.

Tanıma ajanı ürünün ne olduğunu söyler; bu ajan **sayıları** getirir. Katalog
ve standart sayfalarından anma ölçüsü, basınç sınıfı, sıcaklık aralığı, gövde
ve iç parça malzemeleri, geçerli standartlar ve bu ürün tipinde **standart
olarak bulunan ama fotoğrafta görünmeyen** parçalar toplanır.

Mimaride yeri değişti. Eski kurguda bu adım 3D motoruna gidecek *betimi*
zenginleştiriyordu — yani çıktısı bir metin istemiydi. Artık çıktısı doğrudan
**mühendislik verisi**: ölçüler CAD çekirdeğine parametre olarak girer (DN/PN
ayrıştırılır), geri kalanı sunum sayfasındaki teknik özellik tablosunu doldurur.
Model üretimi bu adımın başarısına bağlı değildir; ölçü bulunamazsa tanıma
ajanının tahmini ve tablo varsayılanları kullanılır.

İki aşamalı çağrı, tek aşama yerine:
  1. `web_search` aracıyla serbest metin teknik rapor üretilir.
  2. Rapor, araçsız ikinci bir çağrıda `SpecSheet` şemasına oturtulur.
Sebep: sunucu araçları uzun turlarda `pause_turn` ile durabiliyor; yapılandırılmış
çıktıyı aynı turda zorlamak yarım JSON riski taşıyor.

Maliyet: arama başına ~$0.01 + token. `.env` → `SPEC_ENABLED=false` ile
tamamen kapatılabilir; kapalıyken zincir tanıma çıktısıyla devam eder.
"""
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

import anthropic

from core.config import MODEL_PRICES, WEB_SEARCH_COST_PER_USE, settings
from core.schemas import SpecSheet

MAX_TOKENS = 8000
# Dinamik filtrelemeli güncel sürüm; Sonnet 5.5 / Opus 5.x bunu destekler.
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_PAUSE_RESUMES = 3

SPEC_SYSTEM = """Sen endüstriyel ürün veri uzmanısın. Elinde bir ürünün \
fotoğraftan çıkarılmış teknik kimliği var. Görevin internetten bu ürün tipinin \
KATALOG VERİLERİNİ bulmak.

Aradıkların:
- Anma ölçüsü ve basınç sınıfı (verilen tahmini DOĞRULA veya düzelt).
- Çalışma sıcaklığı aralığı ve basınç-sıcaklık ilişkisi.
- Gövde, iç parça ve sızdırmazlık malzemeleri (döküm kodlarıyla: CF8M, WCB, …).
- Geçerli standartlar (EN, ISO, ASME, API, DIN numaralarıyla).
- Bu ürün tipinde STANDART olarak bulunan parçaların tam listesi; fotoğrafta \
GÖRÜNMEYENLER dahil (oturma halkası, salmastra, yaylı rondela, antistatik \
eleman, burç, kör delik tapası). Bu liste müşteriye parça listesi olarak \
gösterilecek, eksik bırakma.
- Tipik yüzey işlemi ve kullanım alanları.

Kaynak bulamazsan uydurmadan "bulunamadı" de. Aramayı en çok {max_searches} kez kullan."""

STRUCTURE_SYSTEM = """Aşağıdaki teknik raporu verilen şemaya dönüştür.

- Ölçü alanlarını (nominal_size, pressure_rating) raporda geçtiği biçimde yaz: \
'DN50', 'PN40', '2 inç', 'Class 150'. Birden fazla değer varsa en olasısını seç.
- specs tablosunda her satır tek bir ölçülebilir özellik olsun; değer birimiyle \
birlikte yazılsın.
- Raporda olmayan bilgiyi uydurma; alan boş kalabilir.
- Metin alanlarını {language} yaz, standart numaraları ve döküm kodları ham kalsın."""


class SpecError(RuntimeError):
    """Teknik veri adımının hatası. Zincir için ASLA kritik değildir."""


@dataclass
class SpecRunInfo:
    model: str
    searches: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    seconds: float
    sources: List[str] = field(default_factory=list)


def build_client() -> anthropic.Anthropic:
    if not settings.anthropic_api_key or settings.anthropic_api_key.endswith("..."):
        raise SpecError("ANTHROPIC_API_KEY ayarlı değil")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _question(identity: dict) -> str:
    """Tanıma çıktısından arama sorusu kurar."""
    def join(key: str) -> str:
        return ", ".join(str(v) for v in (identity.get(key) or [])) or "yok"

    return (
        f"Ürün: {identity.get('product_name')} / İngilizce: "
        f"{identity.get('product_name_en')}\n"
        f"Tip tanımı: {identity.get('type_designation')}\n"
        f"Anma ölçüsü (fotoğraftan): {identity.get('nominal_size') or 'okunamadı'}\n"
        f"Basınç sınıfı (fotoğraftan): {identity.get('pressure_rating') or 'okunamadı'}\n"
        f"Gövde malzemesi: {identity.get('body_material')}\n"
        f"Bağlantı: {identity.get('end_connection')} · "
        f"Kumanda: {identity.get('actuation')} · "
        f"Gövde parça sayısı: {identity.get('piece_count')}\n"
        f"Üzerindeki damgalar: {join('markings')}\n"
        f"Görünen özellikler: {join('visible_features')}\n\n"
        f"Bu ürün tipinin katalog verilerini ve standart parça listesini araştır."
    )


def _text_of(response) -> str:
    return "\n".join(b.text for b in response.content if getattr(b, "type", "") == "text")


def _count_searches(response) -> tuple:
    """Kaç arama yapıldığını ve kaynak adreslerini toplar.

    Sunucu araçları hata verdiğinde istisna atmaz; HTTP 200 içinde
    `web_search_tool_result` bloğunun `content` alanı liste yerine tek bir
    hata nesnesi olur. Bu yüzden indekslemeden önce tür kontrolü şart.
    """
    searches, sources = 0, []
    for block in response.content:
        if getattr(block, "type", "") != "web_search_tool_result":
            continue
        searches += 1
        content = getattr(block, "content", None)
        if not isinstance(content, list):
            continue        # hata nesnesi (ör. max_uses_exceeded)
        for item in content:
            url = getattr(item, "url", None)
            if url:
                sources.append(url)
    return searches, sources


def _price(model: str) -> tuple:
    return MODEL_PRICES.get(model, MODEL_PRICES.get(settings.spec_model, (0.0, 0.0)))


def research(identity: dict, client: Optional[anthropic.Anthropic] = None,
             on_progress=lambda msg: None) -> tuple:
    """Ürünü internette araştırır. (SpecSheet, SpecRunInfo) döner."""
    client = client or build_client()
    model = settings.spec_model
    started = time.perf_counter()
    in_price, out_price = _price(model)
    input_tokens = output_tokens = 0

    # --- 1. Arama turu ---
    on_progress("katalog ve standart verileri aranıyor")
    messages: list = [{"role": "user", "content": _question(identity)}]
    tools = [{
        "type": WEB_SEARCH_TOOL_TYPE,
        "name": "web_search",
        "max_uses": max(1, settings.spec_max_searches),
    }]

    searches, sources, report = 0, [], ""
    for attempt in range(MAX_PAUSE_RESUMES + 1):
        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SPEC_SYSTEM.format(max_searches=settings.spec_max_searches),
                messages=messages,
                tools=tools,
                output_config={"effort": settings.spec_effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIStatusError as e:
            raise SpecError(f"teknik veri çağrısı başarısız ({e.status_code}): "
                            f"{e.message}") from e
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
            raise SpecError(f"teknik veri için API'ye bağlanılamadı: {e}") from e

        input_tokens += int(getattr(response.usage, "input_tokens", 0) or 0)
        output_tokens += int(getattr(response.usage, "output_tokens", 0) or 0)
        used, found = _count_searches(response)
        searches += used
        sources += found
        report += _text_of(response)

        if response.stop_reason == "refusal":
            raise SpecError("model araştırmayı reddetti")
        if response.stop_reason != "pause_turn":
            break
        # Uzun sunucu aracı turu bölündü: duraklamış turu geri ekleyip sürdür.
        messages.append({"role": "assistant", "content": response.content})
        on_progress(f"arama turu sürdürülüyor ({attempt + 1})")

    extra_cost = searches * WEB_SEARCH_COST_PER_USE
    if not report.strip():
        raise SpecError("teknik veri raporu boş döndü")
    on_progress(f"{searches} arama, {len(set(sources))} kaynak; rapor yapılandırılıyor")

    # --- 2. Yapılandırma turu (araçsız) ---
    try:
        structured = client.beta.messages.parse(
            model=model,
            max_tokens=MAX_TOKENS,
            system=STRUCTURE_SYSTEM.format(language=settings.output_language),
            messages=[{"role": "user", "content": report}],
            output_format=SpecSheet,
            output_config={"effort": "low"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
    except anthropic.APIStatusError as e:
        raise SpecError(f"rapor yapılandırılamadı ({e.status_code}): {e.message}") from e

    input_tokens += int(getattr(structured.usage, "input_tokens", 0) or 0)
    output_tokens += int(getattr(structured.usage, "output_tokens", 0) or 0)
    result = structured.parsed_output
    if result is None:
        raise SpecError(f"yapılandırılmış teknik veri alınamadı "
                        f"(stop_reason={structured.stop_reason})")

    # Model kaynak listesini atlarsa aramadan toplananları kullan.
    if not result.reference_urls:
        result.reference_urls = sorted(set(sources))[:8]

    info = SpecRunInfo(
        model=model,
        searches=searches,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round((input_tokens * in_price + output_tokens * out_price) / 1_000_000
                       + extra_cost, 5),
        seconds=round(time.perf_counter() - started, 1),
        sources=sorted(set(sources))[:12],
    )
    return result, info


def attach_to_metadata(job_dir: Path, result: SpecSheet, info: SpecRunInfo) -> Path:
    """Teknik veriyi metadata.json içine yazar (tanıma çıktısını bozmadan)."""
    path = Path(job_dir) / "metadata.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["spec"] = result.model_dump()
    payload["spec_run"] = asdict(info)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
