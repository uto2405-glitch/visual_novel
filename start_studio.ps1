# 스튜디오 통합 기동 — 로컬 LLM 서버 + 웹 스튜디오를 한 번에 켠다.
#
# 사용:
#   powershell -ExecutionPolicy Bypass -File start_studio.ps1
#   powershell -ExecutionPolicy Bypass -File start_studio.ps1 -Lan          # 폰에서 접속
#   powershell -ExecutionPolicy Bypass -File start_studio.ps1 -Model "models\Qwen3.5-9B-Q4_K_M.gguf"
#   powershell -ExecutionPolicy Bypass -File start_studio.ps1 -NoLlm        # 스튜디오만
#
# 이미 떠 있는 서버는 다시 켜지 않는다(중복 기동·모델 재적재 방지).
# 이 창을 닫거나 Ctrl+C 하면 스튜디오만 멈춘다. LLM 은 계속 떠 있다:
#   Get-Process llama-server | Stop-Process -Force

param(
    [switch]$Lan,                 # 같은 와이파이의 폰/태블릿에서 접속 허용 (신뢰된 네트워크에서만)
    [string]$Model = "",          # serve.ps1 에 넘길 모델 경로 (생략 시 serve.ps1 기본값)
    [int]$Port = 8765,            # 웹 스튜디오 포트
    [switch]$NoLlm,               # 로컬 LLM 은 건드리지 않음
    [switch]$NoBrowser            # 브라우저 자동 열기 안 함
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$repo = $PSScriptRoot
$llmRoot = "c:\Users\USER\claude\local_llm"
$serve = Join-Path $llmRoot "runtime\serve.ps1"
$llmPort = 8080

function Write-Step($text) { Write-Output "  $text" }

Write-Output "============================================================"
Write-Output " AI 비주얼노벨 스튜디오 기동"
Write-Output "============================================================"

# ---------------------------------------------------------------- 사전 점검
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Output "[중단] python 을 찾을 수 없습니다. Python 3.9+ 설치 후 PATH 를 확인하세요."
    exit 1
}
$webapp = Join-Path $repo "tools\webapp.py"
if (-not (Test-Path $webapp)) {
    Write-Output "[중단] tools\webapp.py 가 없습니다: $webapp"
    exit 1
}

# ---------------------------------------------------------------- 1) 로컬 LLM
if ($NoLlm) {
    Write-Output "[1/2] 로컬 LLM: 건너뜀 (-NoLlm)"
} else {
    $running = Get-Process llama-server -ErrorAction SilentlyContinue
    if ($running) {
        # serve.ps1 은 기존 프로세스를 죽이고 다시 띄운다 → 이미 떠 있으면 호출하지 않는다.
        Write-Output "[1/2] 로컬 LLM: 이미 실행 중 (PID $($running[0].Id)) — 그대로 사용"
    } elseif (-not (Test-Path $serve)) {
        Write-Output "[1/2] 로컬 LLM: serve.ps1 을 찾을 수 없어 건너뜀 ($serve)"
        Write-Step "스토리·프롬프트·대화 탭은 서버가 켜질 때까지 동작하지 않습니다."
    } else {
        Write-Output "[1/2] 로컬 LLM 기동 중..."
        if ($Model) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $serve -Model $Model
        } else {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $serve
        }
        # 모델 적재는 수십 초가 걸린다 — /v1/models 가 응답할 때까지 기다린다.
        $ready = $false
        for ($i = 1; $i -le 45; $i++) {
            try {
                $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 `
                        -Uri "http://127.0.0.1:$llmPort/v1/models"
                if ($r.StatusCode -eq 200) { $ready = $true; break }
            } catch { }
            Start-Sleep -Seconds 2
        }
        if ($ready) {
            Write-Step "준비 완료 (http://127.0.0.1:$llmPort/v1)"
        } else {
            Write-Step "아직 응답이 없습니다 — 모델 적재가 느릴 수 있습니다. 스튜디오는 그대로 띄웁니다."
            Write-Step "확인: python tools\doctor.py"
        }
    }
}

# ---------------------------------------------------------------- 2) 웹 스튜디오
$busy = $null
try {
    $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
} catch { }
if ($busy) {
    Write-Output "[2/2] 웹 스튜디오: 포트 $Port 가 이미 사용 중 — 중복 기동하지 않습니다."
    Write-Output ""
    Write-Output "  이미 열려 있는 주소: http://127.0.0.1:$Port/"
    Write-Output "  다른 포트로 띄우려면: -Port 8766"
    exit 0
}

Write-Output "[2/2] 웹 스튜디오 기동 (포트 $Port)"
if ($Lan) {
    Write-Step "LAN 모드 — 같은 와이파이의 다른 기기도 접속할 수 있습니다. 신뢰된 네트워크에서만 쓰세요."
}
Write-Output ""

$argv = New-Object System.Collections.Generic.List[string]
$argv.Add($webapp)
$argv.Add("--port"); $argv.Add("$Port")
if ($Lan) { $argv.Add("--lan") }
if ($NoBrowser) { $argv.Add("--no-browser") }

Set-Location $repo
# python 이 stderr 로 뭔가 쓸 때 PowerShell 이 이를 종료 오류로 승격시키지 않게 한다.
$ErrorActionPreference = "Continue"
& python $argv.ToArray()
exit $LASTEXITCODE
