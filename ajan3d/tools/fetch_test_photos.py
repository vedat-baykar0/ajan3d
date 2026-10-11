"""Test için Wikimedia Commons'tan bir objenin 4 farklı açıdan fotoğrafını indirir.

Kaynak: Cooper Hewitt (Smithsonian Design Museum) koleksiyon fotoğrafları. Aynı obje
"(CH <no>)", "(CH <no>-2)", "(CH <no>-3)"... adlarıyla farklı açılardan yüklenmiştir.
Script adayları sırayla dener; en az 4 görseli ve serbest lisansı olan ilk objeyi indirir.

Kullanım:  python tools/fetch_test_photos.py [hedef_klasor]
"""
import re
import sys
from pathlib import Path

import httpx

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "ajan3d-test-photo-fetcher/1.0 (local test script)"}
WIDTH = 1600
FREE_LICENSES = re.compile(r"^(CC0|Public domain|PD|CC BY)", re.I)

# (arama ifadesi, açıklama) — sırayla denenir
# (Cooper Hewitt no, açıklama, kullanılacak görsel sırası — ilki ön görünüm olmalı, 3D üretim onu "ön" kabul eder)
# Elle kontrol edildi: tek obje, sade arka plan, farklı açılar. (CH 18705481 gibi adaylar
# bazı karelerde iki sandalyeyi birlikte gösterdiği için 3D üretime uygun değil.)
CANDIDATES = [
    ("CH 69114927", "Sallanan sandalye (Pratt House, 1912)", [2, 1, 3, 4]),
    ("CH 18431709", "Okuma sandalyesi (~1720–30)", [3, 2, 1, 7]),
]


def find_views(client: httpx.Client, ch_id: str) -> list[dict]:
    r = client.get(API, params={
        "action": "query", "format": "json", "list": "search", "srnamespace": 6,
        "srlimit": 20, "srsearch": f'intitle:"{ch_id}"',
    })
    titles = [s["title"] for s in r.json()["query"]["search"]
              if re.search(rf"\({re.escape(ch_id)}(-\d+)?\)\.jpe?g$", s["title"], re.I)]
    if not titles:
        return []
    r = client.get(API, params={
        "action": "query", "format": "json", "prop": "imageinfo", "titles": "|".join(titles),
        "iiprop": "url|extmetadata|size", "iiurlwidth": WIDTH,
    })
    views = []
    for page in r.json()["query"]["pages"].values():
        info = page["imageinfo"][0]
        license_name = info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
        m = re.search(r"-(\d+)\)\.jpe?g$", page["title"], re.I)
        views.append({
            "title": page["title"], "order": int(m.group(1)) if m else 1,
            "url": info.get("thumburl") or info["url"], "license": license_name,
            "page": info.get("descriptionurl", ""),
        })
    return sorted(views, key=lambda v: v["order"])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    target = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "Test_Fotograflari")
    target.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True) as client:
        for ch_id, label, order in CANDIDATES:
            by_order = {v["order"]: v for v in find_views(client, ch_id) if FREE_LICENSES.match(v["license"])}
            views = [by_order[n] for n in order if n in by_order]
            print(f"{label} [{ch_id}]: {len(views)}/4 serbest lisanslı görsel")
            if len(views) < 4:
                continue
            for old in target.glob("*.jpg"):
                old.unlink()
            credits = []
            for i, v in enumerate(views, 1):
                dest = target / f"{i:02d}_{ch_id.replace(' ', '')}.jpg"
                resp = client.get(v["url"])
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                credits.append(f"{dest.name}: {v['title']} — {v['license']} — {v['page']}")
                print(f"  indirildi: {dest.name} ({len(resp.content) // 1024} KB)")
            (target / "KAYNAK.txt").write_text(
                f"Obje: {label}\nKaynak: Cooper Hewitt, Smithsonian Design Museum (Wikimedia Commons)\n\n"
                + "\n".join(credits) + "\n", encoding="utf-8")
            return 0
    print("Uygun obje bulunamadı.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
