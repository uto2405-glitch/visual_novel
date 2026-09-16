# 스튜디오 통합 기동 — 로컬 LLM 서버 + 웹 스튜디오를 한 번에 켠다.
#
# 사용:
#   powershell -ExecutionPolicy Bypass -File start_studio.ps1
#   powershell -ExecutionPolicy Bypass -File start_studio.ps1 -Lan          # 폰에서 접속
#   powershell -ExecutionPolicy Bypass -File start_studio.ps1 -Model "models\Qwen3.5-9B-Q4_K_M.gguf"
#   powershell -ExecutionPolicy Bypass -File start_studio.ps1 -NoLlm        # 스튜디오만
#   powershell -ExecutionPolicy Bypass -File start_studio.ps1 -NoComfy      # 이미지 엔진은 그대로
#
# 더블클릭용: start_studio.bat (같은 폴더) — 실행 정책을 건드리지 않고 이 파일을 부른다.
#
# 이미 떠 있는 서버는 다시 켜지 않는다(중복 기동·모델 재적재 방지).
# 이 창을 닫거나 Ctrl+C 하면 스튜디오만 멈춘다. LLM 은 계속 떠 있다:
#   Get-Process llama-server | Stop-Process -Force

param(
    [switch]$Lan,                 # 같은 와이파이의 폰/태블릿에서 접속 허용 (신뢰된 네트워크에서만)
    [string]$Model = "",          # serve.ps1 에 넘길 모델 경로 (생략 시 serve.ps1 기본값)
    [int]$Port = 8765,            # 웹 스튜디오 포트
    [switch]$NoLlm,               # 로컬 LLM 은 건드리지 않음
    [switch]$NoComfy,             # 이미지 엔진(ComfyUI)은 건드리지 않음
    [switch]$NoBrowser,           # 브라우저 자동 열기 안 함
    [string]$LlmRoot = "",        # 로컬 LLM(llama.cpp) 설치 폴더 · 환경변수 LOCAL_LLM_HOME 로도 지정
    [string[]]$Trust = @(),       # 이 기기(IP)만 PIN 없이 들어온다 — 내 폰 하나만 열 때
    [string]$Comfy = "",          # 그림 엔진 주소(다른 PC 에 있을 때). 예: http://DESKTOP-06ACMT6:8188
    [string]$Llm = ""             # 글 엔진 주소. 매니페스트를 덮는다 — 아래 주석 참고
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$repo = $PSScriptRoot
# 로컬 LLM 설치 위치. 예전에는 여기에 개발 PC 의 경로가 그대로 박혀 있어서, 다른 기기에서는
# 어떤 값을 넣어도 찾지 못했다(스토리·장면·프롬프트·대화 네 탭이 전부 그 서버에 달려 있다).
# 순서: -LlmRoot > 환경변수 LOCAL_LLM_HOME > 이 사용자의 홈 아래 claude\local_llm.
$llmRoot = if ($LlmRoot) { $LlmRoot }
           elseif ($env:LOCAL_LLM_HOME) { $env:LOCAL_LLM_HOME }
           else { Join-Path $env:USERPROFILE "claude\local_llm" }
$serve = Join-Path $llmRoot "runtime\serve.ps1"
$llmPort = 8080

function Write-Step($text) { Write-Output "  $text" }

# LLM 주소 해석 — 순서는 tools/local_llm.py 의 base_url() 과 **같아야 한다**.
# (여기서만 다르게 고르면 기동 배너와 스튜디오가 서로 다른 서버를 가리키고,
#  그 어긋남은 "켰다는데 왜 안 되지" 로만 드러난다.)
# -Llm 은 환경변수 LOCAL_LLM_URL 로 넣는다.
#
# 왜 매니페스트를 안 고치는가: project\manifest.json 은 **git 에 올라가는 파일**이라
# 두 기계가 같은 한 줄을 나눠 쓴다. 그런데 올바른 값이 서로 다르다 — 노트북은 그 모델을
# 자기가 들고 있으니 127.0.0.1 이 맞고(자기 자신을 LAN 주소로 부르면 DHCP 가 바뀔
# 때마다 같이 깨진다), 데스크탑은 노트북 주소가 맞다. 한 파일로는 둘 다 만족할 수
# 없으므로, 기계별 값은 이번 실행에만 유효한 환경변수로 덮는다(저장소는 그대로 둔다).
if ($Llm) { $env:LOCAL_LLM_URL = $Llm.TrimEnd("/") }

function Get-LlmUrl {
    if ($env:LOCAL_LLM_URL) { return ([string]$env:LOCAL_LLM_URL).TrimEnd('/') }
    $mf = Join-Path $repo "project\manifest.json"
    if (Test-Path $mf) {
        try {
            $j = Get-Content $mf -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($u in @($j.talk.base_url, $j.orchestrator.api.base_url)) {
                if ($u) { return ([string]$u).TrimEnd('/') }
            }
        } catch { }
    }
    return "http://127.0.0.1:$llmPort/v1"
}

# 이 기계 자신을 가리키는 주소들 — 루프백 + 이 PC 의 LAN IP + 호스트 이름.
#
# 왜 필요한가: 매니페스트에 적힌 LLM 주소가 **이 기계 자신의 LAN 주소**인 경우가 있다.
# 노트북이 메인이 되면 정확히 그렇다(orchestrator.api.base_url = http://192.168.219.182:8080/v1
# 인데 그 IP 가 노트북 자신이다). 예전 판정은 "루프백이 아니면 남의 기계" 였으므로 그때
# llama-server 를 **켜지 않고** "다른 기기에 있습니다" 라고만 적었다 — 원클릭의 핵심이
# 바로 거기서 죽는다. 사람은 아이콘을 눌렀는데 글 관련 탭이 전부 먹통인 화면을 본다.
function Get-SelfHosts {
    $self = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($n in @("127.0.0.1", "localhost", "::1")) { [void]$self.Add($n) }
    try { [void]$self.Add($env:COMPUTERNAME.ToLower()) } catch { }
    try { [void]$self.Add([System.Net.Dns]::GetHostName().ToLower()) } catch { }
    try {
        foreach ($a in [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName())) {
            [void]$self.Add($a.IPAddressToString.ToLower())
        }
    } catch { }
    return $self
}

# 이 주소가 **다른 기기**인가. 여기서 켤 수 있는지를 가른다.
function Test-RemoteLlm($url) {
    try { $h = ([uri]$url).Host.ToLower() } catch { return $false }
    if (-not $h) { return $false }
    $self = Get-SelfHosts
    if ($self.Contains($h)) { return $false }
    if ($self.Contains(($h -split '\.')[0])) { return $false }   # LENOVO.local → LENOVO
    $ip = [System.Net.IPAddress]::None
    if ([System.Net.IPAddress]::TryParse($h, [ref]$ip)) {
        return (-not [System.Net.IPAddress]::IsLoopback($ip))
    }
    return $true
}

Write-Output "============================================================"
Write-Output " AI 비주얼노벨 스튜디오 기동"
Write-Output "============================================================"

# ---------------------------------------------------------------- 사전 점검
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Output "[중단] python 을 찾을 수 없습니다. Python 3.9+ 설치 후 PATH 를 확인하세요."
    exit 1
}

# 저장소 전용 가상환경을 우선한다. 있는 이유는 딱 하나, Pillow 다 — 없는 파이썬으로
# 스튜디오를 띄우면 /img?w=224 가 썸네일 대신 원본 PNG 를 그대로 보낸다(장면 탭 한 번에 수십 MB).
# 없으면 그냥 python 으로 돌아간다 — 가상환경은 선택사항이지 준비물이 아니다.
$studioPy = Join-Path $repo ".venv\Scripts\python.exe"
if (Test-Path $studioPy) {
    $pyNote = "저장소 가상환경 .venv (Pillow 포함 — 썸네일·인화 마스터·컨택트시트 동작)"
} else {
    $studioPy = "python"
    $pyNote = "시스템 python (.venv 없음 — Pillow 가 없으면 썸네일 없이 원본 PNG 를 보냅니다: python -m venv .venv)"
}
$webapp = Join-Path $repo "tools\webapp.py"
if (-not (Test-Path $webapp)) {
    Write-Output "[중단] tools\webapp.py 가 없습니다: $webapp"
    exit 1
}

# ---------------------------------------------------------------- 1) 이미지 엔진
# 매니페스트 image_generator.engine 이 comfyui 면 로컬 ComfyUI 가 떠 있어야 [🎨 이미지 생성]
# 버튼이 동작한다. 스튜디오만 먼저 켜 두면 사람이 그 사실을 생성 실패로 처음 알게 된다 —
# 그래서 기동 순서의 맨 앞에 둔다. 주소는 COMFYUI_URL > 매니페스트 > 기본값 순이고,
# **이미 떠 있으면 절대 건드리지 않는다**(모델 재적재·VRAM 중복 점유 방지).
$comfyPort = 8188
$comfyUrl = "http://127.0.0.1:8188"
$engine = "makefun"
try {
    $mf = Get-Content (Join-Path $repo "project\manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $ig = $mf.image_generator
    if ($ig) {
        if ($ig.engine) { $engine = "$($ig.engine)".ToLower() }
        elseif ($ig.comfyui) { $engine = "comfyui" }
        if ($ig.comfyui -and $ig.comfyui.api -and $ig.comfyui.api.base_url) { $comfyUrl = "$($ig.comfyui.api.base_url)" }
    }
} catch { }
# -Comfy 는 환경변수로 넣는다 — 매니페스트를 고치지 않고 이번 실행만 다른 기계를 보게 한다.
# (자식 프로세스인 스튜디오가 그대로 물려받는다. comfyui_client 의 순서: COMFYUI_URL > 매니페스트.)
if ($Comfy) { $env:COMFYUI_URL = $Comfy.TrimEnd("/") }
if ($env:COMFYUI_URL) { $comfyUrl = $env:COMFYUI_URL }
$comfyUrl = $comfyUrl.TrimEnd("/")
try { $comfyPort = ([uri]$comfyUrl).Port } catch { }

function Test-Comfy {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "$comfyUrl/system_stats"
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

if ($engine -ne "comfyui") {
    Write-Output "[1/3] 이미지 엔진: $engine — ComfyUI 기동 없음"
} elseif ($NoComfy) {
    Write-Output "[1/3] 이미지 엔진: 건너뜀 (-NoComfy)"
} elseif (Test-Comfy) {
    Write-Output "[1/3] 이미지 엔진: ComfyUI 이미 실행 중 ($comfyUrl) — 그대로 사용"
} else {
    # 내 PC 에 있는 설치본만 띄운다. 주소가 다른 기기를 가리키면 그 기기에서 켜야 한다.
    $local = $false
    try { $local = @("127.0.0.1", "localhost", "::1") -contains ([uri]$comfyUrl).Host } catch { }
    $comfyHome = ""
    foreach ($cand in @($env:COMFYUI_HOME, (Join-Path (Split-Path $repo -Parent) "ComfyUI"))) {
        if ($cand -and (Test-Path (Join-Path $cand "main.py"))) { $comfyHome = $cand; break }
    }
    if (-not $local) {
        Write-Output "[1/3] 이미지 엔진: $comfyUrl 응답 없음 — 다른 기기 주소라 여기서 켤 수 없습니다."
        Write-Step "그 PC 에서 ComfyUI 를 켜세요. 확인: python tools\comfyui_client.py --check --online"
    } elseif (-not $comfyHome) {
        Write-Output "[1/3] 이미지 엔진: ComfyUI 설치본을 찾지 못했습니다 — 건너뜀"
        Write-Step "환경변수 COMFYUI_HOME 에 ComfyUI 폴더(main.py 가 있는 곳)를 지정하세요."
    } else {
        Write-Output "[1/3] 이미지 엔진 기동 중... ($comfyHome)"
        $comfyPy = Join-Path $comfyHome "venv\Scripts\python.exe"
        if (-not (Test-Path $comfyPy)) { $comfyPy = "python" }
        $listen = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
        Start-Process -FilePath $comfyPy `
            -ArgumentList @("main.py", "--listen", $listen, "--port", "$comfyPort") `
            -WorkingDirectory $comfyHome -WindowStyle Minimized | Out-Null
        $ready = $false
        for ($i = 1; $i -le 60; $i++) {
            if (Test-Comfy) { $ready = $true; break }
            Start-Sleep -Seconds 2
        }
        if ($ready) {
            Write-Step "준비 완료 ($comfyUrl)"
        } else {
            Write-Step "아직 응답이 없습니다 — 첫 기동은 느릴 수 있습니다. 스튜디오는 그대로 띄웁니다."
            Write-Step "확인: python tools\comfyui_client.py --check --online"
        }
    }
}

# ---------------------------------------------------------------- 2) 로컬 LLM
if ($NoLlm) {
    Write-Output "[2/3] 로컬 LLM: 건너뜀 (-NoLlm)"
} else {
  $llmUrl = Get-LlmUrl
  if (Test-RemoteLlm $llmUrl) {
    # LLM 이 다른 기기(노트북)에 있다. 여기서 serve.ps1 을 부르면 **이 PC 에 두 번째
    # 서버가 뜬다** — 모델 파일도 없고 VRAM 만 먹으며, 정작 스튜디오가 보는 주소는
    # 노트북 쪽이라 아무것도 고쳐지지 않는다. 그래서 켜지 않고 응답만 확인한다.
    Write-Output "[2/3] 로컬 LLM: 다른 기기에 있습니다 ($llmUrl) — 여기서 켜지 않고 응답만 확인합니다"
    $llmOk = $false
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 -Uri "$llmUrl/models"
        if ($r.StatusCode -eq 200) { $llmOk = $true }
    } catch { }
    if ($llmOk) {
        Write-Step "응답 정상 — 스토리·장면 구성·프롬프트·대화 탭을 쓸 수 있습니다."
    } else {
        Write-Step "응답 없음 — 그 기기에서 llama-server 가 떠 있는지, IP 가 바뀌지 않았는지 확인하세요."
        Write-Step "주소를 바꾸는 곳은 두 군데뿐입니다: project\manifest.json 의 talk.base_url ·"
        Write-Step "orchestrator.api.base_url, 또는 그 둘을 덮는 setx LOCAL_LLM_URL \"http://새IP:8080/v1\""
        Write-Step "확인: python tools\doctor.py"
    }
  } else {
    $running = Get-Process llama-server -ErrorAction SilentlyContinue
    if ($running) {
        # serve.ps1 은 기존 프로세스를 죽이고 다시 띄운다 → 이미 떠 있으면 호출하지 않는다.
        Write-Output "[2/3] 로컬 LLM: 이미 실행 중 (PID $($running[0].Id)) — 그대로 사용"
    } elseif (-not (Test-Path $serve)) {
        Write-Output "[2/3] 로컬 LLM: serve.ps1 을 찾을 수 없어 건너뜀 ($serve)"
        Write-Step "스토리·프롬프트·대화 탭은 서버가 켜질 때까지 동작하지 않습니다."
        Write-Step "다른 곳에 설치했다면: -LlmRoot 'D:\llm\local_llm' 또는 setx LOCAL_LLM_HOME \"D:\llm\local_llm\""
        Write-Step "아직 설치 전이면 -NoLlm 으로 스튜디오만 켜세요 — 이미지 생성·감상·검사는 그대로 됩니다."
    } else {
        Write-Output "[2/3] 로컬 LLM 기동 중..."
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
}

# ---------------------------------------------------------------- 3) 웹 스튜디오
$busy = $null
try {
    $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
} catch { }
if ($busy) {
    Write-Output "[3/3] 웹 스튜디오: 포트 $Port 가 이미 사용 중 — 중복 기동하지 않습니다."
    Write-Output ""
    Write-Output "  이미 열려 있는 주소: http://127.0.0.1:$Port/"
    Write-Output "  다른 포트로 띄우려면: -Port 8766"
    exit 0
}

Write-Output "[3/3] 웹 스튜디오 기동 (포트 $Port)"
Write-Step "파이썬: $pyNote"
if ($Lan) {
    Write-Step "LAN 모드 — 같은 와이파이의 다른 기기도 접속할 수 있습니다. 신뢰된 네트워크에서만 쓰세요."
}
Write-Output ""

$argv = New-Object System.Collections.Generic.List[string]
$argv.Add($webapp)
$argv.Add("--port"); $argv.Add("$Port")
if ($Lan) { $argv.Add("--lan") }
foreach ($t in $Trust) {
    if ($t) { $argv.Add("--trust"); $argv.Add($t) }
}
if ($NoBrowser) { $argv.Add("--no-browser") }

Set-Location $repo
# python 이 stderr 로 뭔가 쓸 때 PowerShell 이 이를 종료 오류로 승격시키지 않게 한다.
$ErrorActionPreference = "Continue"
& $studioPy $argv.ToArray()
exit $LASTEXITCODE
