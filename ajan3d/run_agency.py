"""3D Ajansı orkestratörü — klasör izleme tabanlı, el değmeyen akış.

    python run_agency.py                 # servisi başlat (önerilen)
    python run_agency.py --once          # bir tur tara, işle, çık (test/cron için)
    python run_agency.py --check         # ayarları doğrula, hiçbir şey yapma
    python run_agency.py --retry-blocked # el değmesi gereken işleri yeniden kuyruğa al
    python run_agency.py --no-tunnel     # yalnızca yerel; public link kurulmaz

Kullanım: `inbox\\` klasörüne bir fotoğraf klasörü atın ya da fotoğrafları
doğrudan bırakın. Gerisi otomatik: tanıma -> teknik veri -> CAD montajı ->
paket -> yayın -> public link.

### İki sunucu, tek süreç — kasıtlı

| Port | Ne | Kim erişir |
|------|----|------------|
| 8000 | Yönetim paneli (iş listesi, hatalar, klasör yolları, QR) | yalnızca 127.0.0.1 |
| 8001 | Yayın: `/p/<slug>/` paketleri + galeri | tünel üzerinden **herkes** |

Eskiden tek port vardı ve tünel onu açıyordu; `/p/...` paketlerinin yanında
yönetim paneli de dışarıdan görünüyordu (iş adları, müşteri klasör yolları,
hata mesajları). Dışarıdan ölçülerek doğrulanmış bir sızıntıydı. Ayrı port bu
sorunu ayarla değil mimariyle kapatır: tünel yayın portuna bağlanır, panel
yalnızca yerel arayüzde dinler.

Tetikleme iki katmanlı:
  1. **watchdog** — klasör/dosya olayında anında tarama yapar (hızlı tepki)
  2. **periyodik tarama** — her `AGENCY_SCAN_SECONDS` saniyede bir (güvenlik ağı)
Proje OneDrive altında duruyor ve ağ/senkron klasörlerde watchdog olayları
kaybolabiliyor; periyodik tarama bu yüzden var. `scan_inbox()` idempotent
olduğu için ikisinin birlikte çalışması sorun değil.

Üretim **tek işçi iş parçacığında** sırayla yapılır. CAD montajı artık yerel ve
saniyeler sürüyor; sıraya alınmasının sebebi GPU kotası değil, Anthropic hız
sınırına birden çok işin aynı anda yüklenmemesi ve günlüğün okunur kalması.
"""
import argparse
import html
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from agents import deployer_agent, notifier_agent, receiver_agent
from agents.receiver_agent import Intake
from core.agency import (BLOCKED, DEPLOYED, NOTIFIED, PRODUCED, RECEIVED,
                         AgencyJob, all_jobs, unfinished_jobs)
from core.config import settings
from core.pipeline import PipelineError, resolve_job_dir, run_pipeline
from core.qr import to_svg
from core.tunnel import available_providers, get_tunnel, public_base_url, start_tunnel, stop_tunnel

work: "queue.Queue[Optional[Intake]]" = queue.Queue()
wake = threading.Event()        # watchdog -> tarama döngüsünü erken uyandırır
stopping = threading.Event()
_inflight: set = set()
_lock = threading.Lock()
_log_lines: list = []           # panelde gösterilen son satırlar
_LOG_KEEP = 120


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with _lock:
        _log_lines.append(line)
        del _log_lines[:-_LOG_KEEP]


# --------------------------------------------------------------------------- #
# İş yürütme
# --------------------------------------------------------------------------- #

def _job_for(intake: Intake) -> AgencyJob:
    """Bu klasör için ajans kaydını bulur ya da açar."""
    job_dir = receiver_agent.claimed_job_dir(intake.folder) or resolve_job_dir(intake.folder)
    existing = AgencyJob.load(job_dir)
    if existing:
        return existing
    job = AgencyJob(
        job_dir=str(job_dir),
        source_folder=str(Path(intake.folder).resolve()),
        customer_email=intake.customer_email,
        customer_name=intake.customer_name,
        subject=intake.subject,
        message_id=intake.message_id,
        stage=RECEIVED,
    )
    job.save()
    return job


def process(job: AgencyJob) -> None:
    """Bir işi bulunduğu aşamadan sonuna kadar yürütür."""
    folder = Path(job.source_folder)
    log(f"İş: {folder.name} -> {Path(job.job_dir).name} (aşama={job.stage})")

    # --- Üretim ---
    if job.stage == RECEIVED:
        try:
            result = run_pipeline(
                folder,
                job_dir=Path(job.job_dir),
                force=settings.force_low_confidence,
                lang=settings.agency_lang,
                on_progress=lambda m: log(f"  {m}"),
            )
        except PipelineError as e:
            job.fail(f"[{e.stage}] {e}", blocked=not e.retriable)
            log(f"  BAŞARISIZ ({e.stage}, "
                f"{'sonra tekrar denenecek' if e.retriable else 'el değmesi gerekiyor'}): {e}")
            _maybe_alert(job, e)
            return
        job.advance(PRODUCED, object_name=result.object_name)
        log(f"  üretildi: {result.delivery_dir.name}")

    # --- Yayın ---
    if job.stage == PRODUCED:
        delivery = _latest_delivery(Path(job.job_dir))
        if delivery is None:
            job.fail("Teslim paketi bulunamadı", blocked=True)
            _maybe_alert(job, RuntimeError("Teslim paketi bulunamadı"))
            return
        try:
            dep = deployer_agent.deploy(delivery, job.object_name)
        except deployer_agent.DeployError as e:
            job.fail(f"[deploy] {e}", blocked=True)
            log(f"  YAYIN BAŞARISIZ: {e}")
            _maybe_alert(job, e)
            return
        job.advance(DEPLOYED, public_slug=dep.slug, public_url=dep.public_url,
                    embed_code=dep.embed_code)
        log(f"  yayında: {dep.public_url} ({dep.size_mb} MB)")

    # --- Sonucu teslim et ---
    if job.stage == DEPLOYED:
        # E-posta yok; sonuç fotoğrafların bırakıldığı klasöre yazılır.
        url = deployer_agent.url_for(job.slug) if job.slug else job.public_url
        embed = (deployer_agent.embed_for(job.slug, job.object_name)
                 if job.slug else job.embed_code)
        try:
            out = deployer_agent.write_result_file(folder, job.object_name, url, embed)
            log(f"  sonuç dosyası: {out.name}")
        except OSError as e:
            log(f"  sonuç dosyası yazılamadı: {e}")

        # SMTP doluysa bilgi maili de gider; yoksa sessizce atlanır.
        if job.customer_email:
            try:
                notifier_agent.send_success(job.customer_email, job.customer_name,
                                            job.object_name, url, embed)
            except notifier_agent.NotifyError as e:
                log(f"  bilgi e-postası gönderilemedi (kritik değil): {e}")
        job.advance(NOTIFIED)
        log(f"  TAMAMLANDI — PUBLIC LINK: {url}")


def _latest_delivery(job_dir: Path) -> Optional[Path]:
    dirs = sorted(p for p in job_dir.glob("delivery_*") if p.is_dir())
    return dirs[-1] if dirs else None


def _maybe_alert(job: AgencyJob, error: Exception) -> None:
    """Engellenen ya da deneme hakkı tükenen işi operatöre bildir (SMTP varsa)."""
    exhausted = job.attempts >= settings.agency_max_attempts
    if not (job.stage == BLOCKED or exhausted) or job.operator_alerted:
        return
    try:
        if notifier_agent.send_operator_alert(
            f"İş el değmesi gerektiriyor: {Path(job.job_dir).name}",
            f"Klasör: {job.source_folder}\nAşama: {job.stage}\n"
            f"Deneme: {job.attempts}\nHata: {error}",
            job_dir=job.job_dir,
        ):
            job.operator_alerted = True
            job.save()
    except notifier_agent.NotifyError:
        pass        # bildirim kritik değil; panelde görünüyor


def worker() -> None:
    while True:
        intake = work.get()
        if intake is None:
            work.task_done()
            return
        key = str(Path(intake.folder).resolve()).lower()
        try:
            process(_job_for(intake))
        except Exception as e:      # işçi asla ölmemeli
            log(f"  BEKLENMEYEN HATA: {type(e).__name__}: {e}")
        finally:
            with _lock:
                _inflight.discard(key)
            work.task_done()


# --------------------------------------------------------------------------- #
# Tetikleyiciler
# --------------------------------------------------------------------------- #

def enqueue(intake: Intake, job_dir: Optional[Path] = None) -> bool:
    """Kuyruğa ekler. Aynı klasör işlenirken ikinci kez eklenmez."""
    key = str(Path(intake.folder).resolve()).lower()
    with _lock:
        if key in _inflight:
            return False
        _inflight.add(key)
    receiver_agent.claim(intake.folder, job_dir or resolve_job_dir(intake.folder))
    work.put(intake)
    return True


def scan_once() -> int:
    """`inbox\\` taranır, hazır klasörler kuyruğa alınır. Eklenen iş sayısını döner."""
    added = 0
    for intake in receiver_agent.scan_inbox():
        if enqueue(intake):
            log(f"Algılandı: {intake.folder.name} ({intake.image_count} fotoğraf)")
            added += 1
    return added


def reset_blocked(pattern: str = "") -> int:
    """`BLOCKED` işleri yeniden denenebilir hale getirir.

    Engellenen işler kasıtlı olarak kendiliğinden tekrar denenmez (fotoğraf kalitesi,
    geçersiz anahtar, kredi bitmesi gibi dışarıdan bir müdahale gerektiren durumlar).
    Sebep ortadan kalktığında — kredi yüklendi, anahtar düzeltildi — işleri elle
    `agency.json` düzenlemeden geri almanın yolu bu.

    `pattern` verilirse yalnızca son hatası o metni içeren işler sıfırlanır
    (büyük/küçük harf duyarsız), ör. "credit" veya "kalite".
    """
    needle = pattern.lower().strip()
    count = 0
    for job in all_jobs(settings.jobs_dir):
        if job.stage != BLOCKED:
            continue
        if needle and needle not in job.last_error.lower():
            continue
        job.stage, job.attempts, job.last_error, job.operator_alerted = RECEIVED, 0, "", False
        job.save()
        count += 1
        log(f"Sıfırlandı: {Path(job.source_folder).name}")
    return count


def retry_unfinished() -> int:
    """Kota/ağ yüzünden yarım kalmış işleri tekrar kuyruğa alır."""
    added = 0
    for job in unfinished_jobs(settings.jobs_dir, settings.agency_max_attempts):
        folder = Path(job.source_folder)
        if not folder.is_dir():
            continue
        if enqueue(receiver_agent.intake_from_folder(folder), job_dir=Path(job.job_dir)):
            log(f"Tekrar deneme: {folder.name} (deneme {job.attempts})")
            added += 1
    return added


def scan_loop() -> None:
    """Periyodik tarama + tekrar deneme. watchdog olayı `wake` ile erken tetikler."""
    last_retry = time.monotonic()
    while not stopping.is_set():
        try:
            scan_once()
            if time.monotonic() - last_retry >= settings.agency_retry_seconds:
                retry_unfinished()
                last_retry = time.monotonic()
        except Exception as e:
            log(f"Tarama hatası: {type(e).__name__}: {e}")
        wake.wait(timeout=settings.agency_scan_seconds)
        wake.clear()


class InboxHandler(FileSystemEventHandler):
    """Herhangi bir değişiklikte taramayı erken tetikler.

    Olayın kendisini yorumlamaya çalışmıyoruz; hangi dosya/klasör olduğu
    önemli değil, `scan_inbox()` zaten neyin hazır olduğuna karar veriyor.
    Bu, kısmi kopyalama ve Windows'un parçalı olaylarına karşı en dayanıklı yol.
    """

    def on_any_event(self, event) -> None:
        wake.set()


# --------------------------------------------------------------------------- #
# Web: yayın sunucusu (dışa açık) ve yönetim paneli (yerel)
# --------------------------------------------------------------------------- #

GALLERY_CSS = """
:root{--bg:#0e0e11;--card:#17171c;--line:#26262e;--text:#f1f1f4;--dim:#8f8f9c;
--accent:#fff;--radius:14px}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:48px 22px 64px}
h1{font-size:clamp(24px,3vw,32px);letter-spacing:-.02em;margin:0 0 6px;font-weight:650}
.sub{color:var(--dim);margin:0 0 34px;font-size:14px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
a.card{display:block;background:var(--card);border:1px solid var(--line);
border-radius:var(--radius);overflow:hidden;text-decoration:none;color:inherit;
transition:transform .18s cubic-bezier(.22,.61,.36,1),border-color .18s}
a.card:hover{transform:translateY(-3px);border-color:#3a3a46}
a.card img{display:block;width:100%;aspect-ratio:4/3;object-fit:cover;background:#0b0b0e}
.card .body{padding:13px 15px 15px}
.card .name{font-weight:600;font-size:14.5px;margin-bottom:3px}
.card .meta{color:var(--dim);font-size:12px}
.empty{color:var(--dim);border:1px dashed var(--line);border-radius:var(--radius);
padding:40px;text-align:center}
"""


def build_publish_app() -> FastAPI:
    """Dışa açık sunucu: YALNIZCA paketler ve bir galeri. Yönetim bilgisi yok."""
    app = FastAPI(title="3D Sunumlar", docs_url=None, redoc_url=None, openapi_url=None)
    settings.public_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/p", StaticFiles(directory=str(settings.public_dir), html=True), name="public")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def gallery() -> str:
        cards = []
        for item in deployer_agent.published():
            slug = item["slug"]
            name = html.escape(item.get("object_name") or slug)
            date = html.escape((item.get("published_at") or "")[:10])
            size = item.get("size_mb", 0)
            thumb = settings.public_dir / slug / "thumbnail.png"
            img = (f'<img src="/p/{slug}/thumbnail.png" alt="{name}" loading="lazy">'
                   if thumb.exists() else "")
            cards.append(
                f'<a class="card" href="/p/{slug}/">{img}<div class="body">'
                f'<div class="name">{name}</div>'
                f'<div class="meta">{date} · {size} MB</div></div></a>'
            )
        body = (f'<div class="grid">{"".join(cards)}</div>' if cards else
                '<div class="empty">Henüz yayınlanmış sunum yok.</div>')
        return (f'<!doctype html><html lang="tr"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>3D Ürün Sunumları</title><style>{GALLERY_CSS}</style></head>'
                f'<body><div class="wrap"><h1>3D Ürün Sunumları</h1>'
                f'<p class="sub">{len(cards)} interaktif sunum</p>{body}</div></body></html>')

    return app


PANEL_CSS = """
:root{--bg:#fbfaf8;--card:#fff;--line:#e6e4df;--text:#17171c;--dim:#73737f;
--ok:#0a7d4b;--warn:#8a5a00;--err:#b4232c;--chip:#f1efec}
@media(prefers-color-scheme:dark){:root{--bg:#101014;--card:#18181d;--line:#2a2a33;
--text:#f0f0f3;--dim:#8f8f9c;--ok:#4ade80;--warn:#fbbf24;--err:#f87171;--chip:#22222a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:30px 22px 60px}
h1{font-size:24px;margin:0 0 4px;letter-spacing:-.02em;font-weight:650}
h2{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);
margin:30px 0 11px;font-weight:600}
.sub{color:var(--dim);margin:0;font-size:13px}
.cards{display:grid;gap:14px;grid-template-columns:1.3fr .7fr;margin-top:22px}
@media(max-width:860px){.cards{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.link{display:flex;align-items:center;gap:10px;margin:10px 0 2px}
.link input{flex:1;min-width:0;font:13px ui-monospace,monospace;padding:9px 11px;
border:1px solid var(--line);border-radius:9px;background:var(--bg);color:var(--text)}
button.copy{border:1px solid var(--line);background:var(--chip);color:var(--text);
border-radius:9px;padding:9px 14px;font:inherit;font-size:13px;cursor:pointer}
button.copy:hover{border-color:var(--dim)}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:3px 10px;
border-radius:999px;background:var(--chip);color:var(--dim)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok)}
.dot.off{background:var(--err)}
.qr{text-align:center}
.qr svg{max-width:184px;height:auto;border-radius:10px}
.qr p{color:var(--dim);font-size:12px;margin:9px 0 0}
table{border-collapse:collapse;width:100%;background:var(--card);
border:1px solid var(--line);border-radius:14px;overflow:hidden;font-size:13.5px}
th,td{padding:11px 14px;text-align:left;border-bottom:1px solid var(--line)}
th{background:var(--chip);font-size:11px;letter-spacing:.08em;text-transform:uppercase;
color:var(--dim);font-weight:600}
tr:last-child td{border-bottom:0}
td a{color:var(--text)}
.stage{font-size:11.5px;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--chip)}
.s-NOTIFIED,.s-DEPLOYED{color:var(--ok)}.s-BLOCKED{color:var(--err)}.s-RECEIVED,.s-PRODUCED{color:var(--warn)}
.err{color:var(--err);font-size:12px}
pre.logs{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:14px 16px;font:11.5px/1.65 ui-monospace,monospace;max-height:260px;
overflow:auto;margin:0;color:var(--dim);white-space:pre-wrap}
code{background:var(--chip);padding:1px 6px;border-radius:5px;font-size:12.5px}
"""


def build_panel_app() -> FastAPI:
    """Yerel yönetim paneli. Tünele BAĞLANMAZ; 127.0.0.1 üzerinde dinler."""
    app = FastAPI(title="ajan3d ajans", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> dict:
        tunnel = get_tunnel()
        status = tunnel.status() if tunnel else None
        return {
            "ok": True,
            "queue": work.qsize(),
            "public_base_url": public_base_url(),
            "tunnel": {
                "provider": status.provider, "url": status.url,
                "running": status.running, "restarts": status.restarts,
                "last_error": status.last_error,
            } if status else None,
        }

    @app.get("/api/jobs")
    def api_jobs() -> JSONResponse:
        return JSONResponse([
            {
                "folder": Path(j.source_folder).name,
                "object_name": j.object_name,
                "stage": j.stage,
                "attempts": j.attempts,
                "public_url": (deployer_agent.url_for(j.slug)
                               if deployer_agent.is_live(j.slug) else ""),
                "last_error": j.last_error[:300],
            } for j in all_jobs(settings.jobs_dir)
        ])

    @app.get("/go")
    def go() -> RedirectResponse:
        """Public galeriye git (tünel varsa dış adres, yoksa yerel)."""
        return RedirectResponse(public_base_url() + "/")

    @app.get("/", response_class=HTMLResponse)
    def status_page() -> str:
        tunnel = get_tunnel()
        tstatus = tunnel.status() if tunnel else None
        base = public_base_url()
        gallery_url = base + "/"
        live = bool(tstatus and tstatus.running and tstatus.url)

        if tstatus is None:
            pill = '<span class="pill"><span class="dot off"></span>tünel kapalı</span>'
        elif live:
            pill = (f'<span class="pill"><span class="dot"></span>{html.escape(tstatus.provider)}'
                    f' · canlı</span>')
        else:
            detail = html.escape(tstatus.last_error[:90]) if tstatus.last_error else "kuruluyor…"
            pill = f'<span class="pill"><span class="dot off"></span>{detail}</span>'

        qr = to_svg(gallery_url) if live else None
        qr_block = (f'<div class="card qr">{qr}<p>Telefonla okutun</p></div>' if qr else
                    '<div class="card qr"><p>Public link hazır olduğunda QR burada çıkar.</p></div>')

        rows = []
        for j in all_jobs(settings.jobs_dir):
            live = deployer_agent.is_live(j.slug)
            url = deployer_agent.url_for(j.slug) if live else ""
            link = (f'<a href="{html.escape(url)}" target="_blank" rel="noopener">aç</a>'
                    if live else ("yayında değil" if j.slug else "—"))
            rows.append(
                f"<tr><td>{html.escape(Path(j.source_folder).name)}</td>"
                f"<td>{html.escape(j.object_name or '—')}</td>"
                f'<td><span class="stage s-{html.escape(j.stage)}">{html.escape(j.stage)}</span></td>'
                f"<td>{j.attempts}</td><td>{link}</td>"
                f'<td class="err">{html.escape(j.last_error[:140])}</td></tr>'
            )
        body = "".join(rows) or ('<tr><td colspan="6">Henüz iş yok — '
                                 'inbox klasörüne fotoğraf klasörü atın</td></tr>')
        with _lock:
            logs = html.escape("\n".join(_log_lines[-60:]) or "—")

        return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15"><title>3D Ajansı</title>
<style>{PANEL_CSS}</style></head><body><div class="wrap">
<h1>3D Ajansı</h1>
<p class="sub">Kuyrukta <code>{work.qsize()}</code> iş ·
<code>{len(deployer_agent.published())}</code> yayında paket ·
gelen klasör <code>{html.escape(str(settings.inbox_dir))}</code></p>

<div class="cards">
  <div class="card">
    <h2 style="margin-top:0">Public link {pill}</h2>
    <div class="link">
      <input id="pub" value="{html.escape(gallery_url)}" readonly onclick="this.select()">
      <button class="copy" onclick="cp('pub',this)">Kopyala</button>
    </div>
    <p class="sub">Bu adresi WhatsApp'tan müşteriye gönderebilirsiniz; galeriden
    tüm sunumlara girilir. Tek bir ürünün linki için aşağıdaki tablodaki
    <b>aç</b> bağlantısını kullanın.</p>
    <p class="sub" style="margin-top:8px">Yönetim paneli (bu sayfa) yalnızca bu
    bilgisayarda açılır; tünel yalnızca yayın portunu
    (<code>{settings.publish_port}</code>) dışarı verir.</p>
  </div>
  {qr_block}
</div>

<h2>İşler</h2>
<table><tr><th>Klasör</th><th>Ürün</th><th>Aşama</th><th>Deneme</th>
<th>Link</th><th>Son hata</th></tr>{body}</table>

<h2>Günlük</h2>
<pre class="logs">{logs}</pre>
</div>
<script>
function cp(id, btn) {{
  const el = document.getElementById(id);
  navigator.clipboard.writeText(el.value).then(() => {{
    const old = btn.textContent; btn.textContent = "Kopyalandı";
    setTimeout(() => btn.textContent = old, 1500);
  }});
}}
</script></body></html>"""

    return app


def _serve(app: FastAPI, host: str, port: int, name: str) -> uvicorn.Server:
    """Sunucuyu arka plan iş parçacığında başlatır.

    `install_signal_handlers=False` şart: sinyal işleyicileri yalnızca ana
    iş parçacığında kurulabilir, aksi halde uvicorn ValueError atar.
    """
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    threading.Thread(target=server.run, daemon=True, name=name).start()
    return server


# --------------------------------------------------------------------------- #
# Giriş
# --------------------------------------------------------------------------- #

def check_config() -> list:
    """Yalnızca gerçekten zorunlu olanı zorunlu sayar."""
    problems = []
    if not settings.anthropic_api_key or settings.anthropic_api_key.endswith("..."):
        problems.append("ANTHROPIC_API_KEY eksik (zorunlu)")
    # PUBLIC_BASE_URL artık zorunlu değil: adres canlı tünelden türetiliyor,
    # tünel de kapalıysa yerel yayın adresine düşülüyor.
    if settings.tunnel_enabled and not settings.tunnel_hostname and not available_providers():
        problems.append("Tünel açık ama ne cloudflared ne ngrok bulundu — "
                        "tools\\bin\\cloudflared.exe eksik olabilir "
                        "(TUNNEL_ENABLED=false ile yalnızca yerel çalışır)")
    if settings.agency_port == settings.publish_port:
        problems.append("AGENCY_PORT ve PUBLISH_PORT aynı olamaz — panelin dışarı "
                        "sızmaması için ayrı portta durması gerekiyor")
    return problems


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="3D Ajansı: inbox klasörü -> 3D sunum -> public link")
    parser.add_argument("--once", action="store_true", help="Bir tur tara ve işle, sonra çık")
    parser.add_argument("--check", action="store_true", help="Yalnızca ayarları doğrula")
    parser.add_argument("--no-tunnel", action="store_true",
                        help="Public link kurma; yalnızca yerel adres üret")
    parser.add_argument("--retry-blocked", nargs="?", const="", metavar="METIN",
                        help="BLOCKED işleri yeniden kuyruğa al; METIN verilirse yalnızca "
                             "son hatası o metni içerenler (ör. --retry-blocked credit)")
    args = parser.parse_args()

    if args.retry_blocked is not None:
        count = reset_blocked(args.retry_blocked)
        print(f"{count} iş yeniden denenmek üzere sıfırlandı."
              + (" Şimdi 'python run_agency.py' ile çalıştırın." if count else ""))
        return 0

    problems = check_config()
    print("Ayar kontrolü: " + ("tamam" if not problems else ""))
    for p in problems:
        print(f"  EKSİK: {p}")
    if args.check:
        print(f"Tünel sağlayıcıları: {', '.join(available_providers()) or '(yok)'}")
        return 1 if problems else 0
    if problems:
        print("Zorunlu ayar eksik; başlatılmadı.", file=sys.stderr)
        return 2

    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    settings.public_dir.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=worker, daemon=True, name="worker").start()

    if args.once:
        # Kararlılık kontrolü dosyayı iki taramada görmek ister: ilk tarama
        # boyutları kaydeder, bekleme sonrası ikinci tarama hazır olanı alır.
        scan_once()
        time.sleep(settings.agency_settle_seconds + 0.5)
        added = scan_once() + retry_unfinished()
        if added == 0:
            print("İşlenecek yeni klasör yok.")
        work.join()
        print("Tur tamamlandı.")
        return 0

    # --- Yayın sunucusu: tünelin bağlanacağı port ---
    _serve(build_publish_app(), settings.publish_host, settings.publish_port, "publish")
    log(f"Yayın sunucusu: {settings.local_publish_url}  (paketler + galeri)")

    # --- Public link ---
    if not args.no_tunnel and settings.tunnel_enabled:
        tunnel = start_tunnel(settings.publish_port, log=log)
        if tunnel is not None:
            # Adresi beklemek üretimi geciktirmemeli; arka planda bildir.
            def announce() -> None:
                url = tunnel.wait_ready()
                if url:
                    log(f"PUBLIC GALERİ: {url}/")
                else:
                    log("Public link kurulamadı; linkler yerel adrese düşecek. "
                        "Panelde ayrıntı var.")
            threading.Thread(target=announce, daemon=True, name="tunnel-announce").start()
    else:
        log("Public link kapalı; linkler yerel adresle üretilecek.")

    # --- Klasör izleme ---
    threading.Thread(target=scan_loop, daemon=True, name="scanner").start()
    observer = Observer()
    observer.schedule(InboxHandler(), str(settings.inbox_dir), recursive=True)
    observer.start()

    log(f"Gelen klasör izleniyor: {settings.inbox_dir}")
    log("Fotoğrafları buraya atın (klasör veya doğrudan dosya)")
    log(f"YÖNETİM PANELİ: http://{settings.agency_host}:{settings.agency_port}/")

    try:
        # Panel ana iş parçacığında çalışır: Ctrl+C'yi o yakalar.
        uvicorn.run(build_panel_app(), host=settings.agency_host,
                    port=settings.agency_port, log_level="warning")
    except KeyboardInterrupt:
        pass
    finally:
        log("Kapatılıyor…")
        stopping.set()
        wake.set()
        observer.stop()
        observer.join(timeout=5)
        stop_tunnel()
        work.put(None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
