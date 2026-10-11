# 3D Ajansı — kalıcı başlatıcı.
#
# Terminali kapatmak sistemi durdurmasın diye ajan AYRI bir süreçte,
# terminale bağlı olmadan başlatılır. Önceki kurulumda `python run_agency.py`
# terminalin çocuğu olduğu için pencere kapandığında web sunucusu ve tünel de
# ölüyordu; bu betik o sorunu çözer.
#
#   .\baslat.ps1            # başlat (zaten çalışıyorsa durumu yazar)
#   .\baslat.ps1 -Durdur    # durdur
#   .\baslat.ps1 -Durum     # çalışıyor mu, public link ne
#   .\baslat.ps1 -Gunluk    # günlüğü canlı izle
#   .\baslat.ps1 -Yeniden   # durdur + başlat
param(
    [switch]$Durdur,
    [switch]$Durum,
    [switch]$Gunluk,
    [switch]$Yeniden
)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$python  = Join-Path $root '.venv\Scripts\pythonw.exe'   # pencere açmayan yorumlayıcı
$fallback= Join-Path $root '.venv\Scripts\python.exe'
$script  = Join-Path $root 'run_agency.py'
$logDir  = Join-Path $root 'logs'
$logFile = Join-Path $logDir 'agency.log'
$pidFile = Join-Path $logDir 'agency.pid'

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
if (-not (Test-Path $python)) { $python = $fallback }

function Get-AgencyProcess {
    if (-not (Test-Path $pidFile)) { return $null }
    $id = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $id) { return $null }
    try { return Get-Process -Id ([int]$id) -ErrorAction Stop } catch { return $null }
}

function Show-Status {
    $proc = Get-AgencyProcess
    if ($proc) {
        Write-Host "ÇALIŞIYOR  (PID $($proc.Id), başlangıç $($proc.StartTime.ToString('HH:mm:ss')))" -ForegroundColor Green
    } else {
        Write-Host "DURMUŞ" -ForegroundColor Yellow
        return
    }
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5
        Write-Host "Panel      : http://127.0.0.1:8000/"
        Write-Host "Kuyruk     : $($health.queue) iş"
        if ($health.tunnel -and $health.tunnel.url) {
            Write-Host ""
            Write-Host "PUBLIC LINK: $($health.tunnel.url)/" -ForegroundColor Cyan
            Write-Host "             (müşteriye bu adresi gönderin)"
        } else {
            Write-Host "Public link: henüz hazır değil (birkaç saniye sürebilir)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Panele ulaşılamadı; süreç yeni başlamış olabilir. Günlük: .\baslat.ps1 -Gunluk" -ForegroundColor Yellow
    }
}

function Stop-Agency {
    $proc = Get-AgencyProcess
    if (-not $proc) {
        Write-Host "Zaten durmuş."
    } else {
        # Önce ajan, sonra ondan arta kalmış tünel süreci
        Stop-Process -Id $proc.Id -Force
        Write-Host "Durduruldu (PID $($proc.Id))." -ForegroundColor Green
    }
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
}

if ($Durdur)  { Stop-Agency; exit 0 }
if ($Durum)   { Show-Status; exit 0 }
if ($Gunluk)  { Get-Content $logFile -Wait -Tail 40; exit 0 }
if ($Yeniden) { Stop-Agency; Start-Sleep -Seconds 2 }

$existing = Get-AgencyProcess
if ($existing) {
    Write-Host "Ajan zaten çalışıyor." -ForegroundColor Yellow
    Show-Status
    exit 0
}

# Günlüğü döndür: eskisini .1 olarak sakla, yenisini sıfırdan başlat
if (Test-Path $logFile) { Move-Item $logFile "$logFile.1" -Force }

# -u: çıktı tamponlanmasın, günlük canlı izlenebilsin.
# Terminale bağlı olmayan ayrı süreç; pencere kapansa da yaşar.
# Yol boşluk içeriyor ("claude falan filan"), bu yüzden tırnaklanması şart.
$proc = Start-Process -FilePath $python `
                      -ArgumentList @('-u', "`"$script`"") `
                      -WorkingDirectory $root `
                      -RedirectStandardOutput $logFile `
                      -RedirectStandardError "$logFile.err" `
                      -WindowStyle Hidden `
                      -PassThru
$proc.Id | Set-Content -Path $pidFile -Encoding ascii

Write-Host "3D Ajansı başlatıldı (PID $($proc.Id))." -ForegroundColor Green
Write-Host "Public link kuruluyor, bekleniyor…"

# Tünel adresi gelene kadar bekle (en çok 60 sn), sonra linki yaz
$url = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) {
        Write-Host "Ajan beklenmedik şekilde kapandı. Günlük:" -ForegroundColor Red
        if (Test-Path $logFile)      { Get-Content $logFile -Tail 25 }
        if (Test-Path "$logFile.err"){ Get-Content "$logFile.err" -Tail 25 }
        exit 1
    }
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
        if ($health.tunnel -and $health.tunnel.url) { $url = $health.tunnel.url; break }
    } catch { }
}

Write-Host ""
if ($url) {
    Write-Host "=======================================================" -ForegroundColor Cyan
    Write-Host " PUBLIC LINK (WhatsApp'tan gönderebilirsiniz):" -ForegroundColor Cyan
    Write-Host "   $url/" -ForegroundColor White
    Write-Host "=======================================================" -ForegroundColor Cyan
    try { Set-Clipboard -Value "$url/"; Write-Host " (link panoya kopyalandı)" -ForegroundColor DarkGray } catch { }
} else {
    Write-Host "Public link henüz gelmedi. Panelden izleyebilirsiniz:" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Yönetim paneli : http://127.0.0.1:8000/"
Write-Host "Fotoğraf atın  : $(Join-Path $root 'inbox')"
Write-Host "Durum          : .\baslat.ps1 -Durum"
Write-Host "Günlük         : .\baslat.ps1 -Gunluk"
Write-Host "Durdur         : .\baslat.ps1 -Durdur"
