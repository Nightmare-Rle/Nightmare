# NIGHTMARE build script.
#   .\build.ps1            -> compile, PyInstaller bundle, deploy, launch
#   .\build.ps1 -NoLaunch  -> stop before launching
#
# IMPORTANT: user data must never be copied from the dev .nightmare folder into
# dist, otherwise a rebuild silently overwrites the user's real settings,
# memory, chat history, watches and routines.
param([switch]$NoLaunch)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$USER_DATA = @('settings.json', 'memory.json', 'chatlog.json', 'autonomy.json', 'nai_crash.log',
               # the Groq key lives in the data dir and must never be copied
               # into a shipped folder
               'groq_key.txt', 'groq_key.txt.bak',
               # the enrolled face is biometric data: never ship a developer's
               # face, and never overwrite the real one on rebuild
               'face_lock.json', 'face_lock.log', 'startup.log', 'voice.log')

Write-Host '== stopping running NIGHTMARE ==' -ForegroundColor Cyan
Get-Process Nightmare -ErrorAction SilentlyContinue | ForEach-Object {
    try { $_.CloseMainWindow() | Out-Null; Start-Sleep -Seconds 3 } catch {}
}
Get-Process Nightmare -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Ollama can hold ~5 GB per model; this box has 16 GB and no GPU. Release the
# resident model so the build (and later the app) has room.
Write-Host '== releasing Ollama models (frees RAM) ==' -ForegroundColor Cyan
try {
    $tags = (Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5).models
    foreach ($m in $tags) {
        $body = @{ model = $m.name; prompt = 'x'; stream = $false; keep_alive = 0 } |
                ConvertTo-Json -Compress
        try { Invoke-RestMethod 'http://127.0.0.1:11434/api/generate' -Method Post `
                -Body $body -ContentType 'application/json' -TimeoutSec 60 | Out-Null } catch {}
    }
    Write-Host ('   unloaded ' + $tags.Count + ' model(s)') -ForegroundColor DarkGray
} catch { Write-Host '   ollama not running, skipping' -ForegroundColor DarkGray }

Write-Host '== cleaning orphaned PyInstaller temp dirs ==' -ForegroundColor Cyan
$stale = Get-ChildItem -Path $env:TEMP -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue
$freed = 0
foreach ($d in $stale) {
    $sz = (Get-ChildItem -LiteralPath $d.FullName -Recurse -File -ErrorAction SilentlyContinue |
           Measure-Object -Property Length -Sum).Sum
    try { Remove-Item -LiteralPath $d.FullName -Recurse -Force -ErrorAction Stop; $freed += $sz }
    catch { }
}
if ($stale.Count) {
    Write-Host ('   removed ' + $stale.Count + ' stale dir(s), freed ' +
                [math]::Round($freed / 1GB, 2) + ' GB') -ForegroundColor DarkGray
}

Write-Host '== compiling ==' -ForegroundColor Cyan
python -m py_compile `
    nai_protocol.pyw `
    modules\ai_brain.py modules\action_executor.py modules\autonomy.py `
    modules\agentic.py modules\gui_agent.py modules\uia.py `
    modules\local_vision.py modules\screen_analysis.py modules\voice_input.py `
    modules\user_model.py modules\child_processes.py modules\facelock.py `
    modules\vision.py modules\system.py modules\system_control.py
if ($LASTEXITCODE -ne 0) { throw 'compile failed' }

Write-Host '== building (onedir: no temp extraction, no _MEI leak) ==' -ForegroundColor Cyan
python -m PyInstaller N.AI_Protocol.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

$appDir = 'dist\Nightmare'
Write-Host '== deploying data (skipping user data) ==' -ForegroundColor Cyan
if (Test-Path .nightmare) {
    $excluded = @()
    Get-ChildItem .nightmare -Force | ForEach-Object {
        if ($_.PSIsContainer) {
            Copy-Item $_.FullName -Destination "$appDir\.nightmare" -Recurse -Force
        } elseif ($USER_DATA -notcontains $_.Name) {
            Copy-Item $_.FullName -Destination "$appDir\.nightmare" -Force
        } else {
            $excluded += $_.Name
        }
    }
    if ($excluded.Count) {
        Write-Host ('   preserved user data: ' + ($excluded -join ', ')) -ForegroundColor Yellow
    }
}
Copy-Item Nightmare.png -Destination "$appDir\" -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path "$appDir\.nightmare" -Force | Out-Null

# Remove the old onefile artefact now that we ship an onedir layout.
$oldExe = 'dist\Nightmare.exe'
if (Test-Path $oldExe) {
    Remove-Item $oldExe -Force -ErrorAction SilentlyContinue
    Write-Host '   removed old onefile dist\Nightmare.exe' -ForegroundColor DarkGray
}

$exe = Join-Path $appDir 'Nightmare.exe'
$sizeMB = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$totalGB = [math]::Round((Get-ChildItem $appDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1GB, 2)
Write-Host ('== built: ' + (Resolve-Path $exe)) -ForegroundColor Green
Write-Host ('   launcher: ' + $sizeMB + ' MB | folder: ' + $totalGB + ' GB') -ForegroundColor Green

if (-not $NoLaunch) {
    Write-Host '== launching ==' -ForegroundColor Cyan
    Start-Process -FilePath (Resolve-Path $exe)
}
