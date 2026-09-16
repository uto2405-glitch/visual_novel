#  그림 PC 를 깨운다 — Wake-on-LAN 매직 패킷 + 준비될 때까지 기다리기.
#
#  왜 필요한가: 3060 이 데스크탑에 있어서 그림은 그 기계에서만 구워진다. 글만 쓸 때는
#  노트북 하나로 되지만, 그림을 뽑으려면 데스크탑이 켜져 있어야 한다. 그걸 켜러 방을
#  건너가지 않아도 되게 한다.
#
#  사용:
#    powershell -ExecutionPolicy Bypass -File wake_desktop.ps1
#    powershell -ExecutionPolicy Bypass -File wake_desktop.ps1 -Wait 180
#
#  **이것이 항상 되는 것은 아니다.** 매직 패킷은 랜카드가 전원을 받고 있을 때만 닿는다.
#  절전(S3)에서는 거의 언제나 되고, 완전 종료(S5)에서는 메인보드 설정에 달렸다:
#    · BIOS/UEFI 에서 "Wake on LAN" / "Power On by PCI-E" 를 켜야 한다
#    · 같은 곳의 "ErP Ready" / "Deep Sleep" 은 **꺼야** 한다 (켜면 전원을 완전히 끊는다)
#    · 윈도의 '빠른 시작' 도 꺼야 한다 (종료가 사실은 최대절전이라 랜카드가 무장 해제된다)
#  무선 랜으로는 사실상 안 된다 — 다행히 이 데스크탑은 유선(Intel I211)이다.
#
#  안 되면 이 스크립트가 그렇다고 말한다. 조용히 실패하지 않는다.

param(
    [string]$Mac  = "0C-9D-92-80-8A-DB",        # 그림 PC 의 유선 랜카드 주소
    [string]$Target = "DESKTOP-06ACMT6",        # 준비됐는지 물어볼 이름
    [int]$Port = 8188,                          # ComfyUI 포트 — 이게 답하면 진짜 준비된 것이다
    [int]$Wait = 150,                           # 최대 대기 초
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Say($t) { if (-not $Quiet) { Write-Output $t } }

function Test-Ready {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "http://${Target}:$Port/system_stats"
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

# 이미 켜져 있으면 아무것도 하지 않는다. 깨우기는 공짜가 아니다 — 자고 있던 기계를
# 쓸데없이 깨우면 전기와 팬 소리를 사람이 부담한다.
if (Test-Ready) {
    Say "그림 PC 는 이미 켜져 있습니다 (http://${Target}:$Port)"
    exit 0
}

# ---------------------------------------------------------------- 매직 패킷
# 규격: FF 6개 + 대상 MAC 16번 반복 = 102바이트. 포트는 관례상 9(또는 7)이고,
# 랜카드가 전원 대기 상태에서 직접 읽으므로 운영체제가 꺼져 있어도 닿는다.
$hex = ($Mac -replace '[:\-\.]', '')
if ($hex.Length -ne 12) {
    Write-Output "[중단] MAC 주소 형식이 아닙니다: $Mac  (예: 0C-9D-92-80-8A-DB)"
    exit 1
}
# 변수 이름을 $mac 으로 쓰면 안 된다 — 파워셸은 대소문자를 구분하지 않아서
# 위의 [string]$Mac 파라미터와 **같은 변수**가 되고, 그 형식 제약 때문에 바이트
# 배열이 "12 157 146 ..." 같은 문자열로 조용히 변한다(실제로 그렇게 한 번 터졌다).
$macBytes = for ($i = 0; $i -lt 12; $i += 2) { [Convert]::ToByte($hex.Substring($i, 2), 16) }
$packet = [byte[]]@(0xFF) * 6 + ([byte[]]$macBytes * 16)
if ($packet.Length -ne 102) {
    Write-Output "[중단] 매직 패킷 크기가 $($packet.Length) 바이트입니다(102 여야 함) — 보내지 않았습니다."
    exit 1
}

# 브로드캐스트 주소를 **여러 개** 쓴다. 255.255.255.255 는 공유기가 버리는 일이 있고,
# 서브넷 브로드캐스트(192.168.219.255)는 대개 통한다 — 둘 다 쏘면 한쪽이 막혀도 닿는다.
$targets = @("255.255.255.255")
foreach ($cfg in (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                  Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixLength -ge 8 -and
                                 $_.PrefixLength -le 32 })) {
    try {
        $ipBytes = ([System.Net.IPAddress]::Parse($cfg.IPAddress)).GetAddressBytes()
        $bc = New-Object byte[] 4
        for ($i = 0; $i -lt 4; $i++) {
            # 이 옥텛에 네트워크 비트가 몇 개 걸리는가 (0~8)
            $bits = [Math]::Max(0, [Math]::Min(8, $cfg.PrefixLength - ($i * 8)))
            $mask = [byte](256 - [Math]::Pow(2, 8 - $bits)) 
            if ($bits -eq 0) { $mask = [byte]0 }
            $bc[$i] = [byte](($ipBytes[$i] -bor (255 - $mask)) -band 0xFF)
        }
        $targets += ([System.Net.IPAddress]::new($bc)).IPAddressToString
    } catch { }
}
$targets = $targets | Select-Object -Unique

$sent = 0
foreach ($t in $targets) {
    foreach ($p in 9, 7) {
        try {
            $udp = New-Object System.Net.Sockets.UdpClient
            $udp.EnableBroadcast = $true
            [void]$udp.Send($packet, $packet.Length, $t, $p)
            $udp.Close()
            $sent++
        } catch { }
    }
}
if ($sent -eq 0) {
    Write-Output "[중단] 매직 패킷을 한 번도 보내지 못했습니다 — 네트워크 어댑터를 확인하세요."
    exit 1
}
Say "깨우기 신호를 보냈습니다 ($Mac · 브로드캐스트 $($targets -join ', ') · $sent 회)"

# ---------------------------------------------------------------- 기다리기
Say "그림 PC 가 준비될 때까지 기다립니다 (최대 $Wait 초)…"
$deadline = (Get-Date).AddSeconds($Wait)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Test-Ready) {
        $left = [int]($Wait - ($deadline - (Get-Date)).TotalSeconds)
        Say "준비 완료 — 그림을 뽑을 수 있습니다 (약 $left 초)"
        exit 0
    }
}

# 실패는 실패라고 말한다. 무엇을 확인해야 하는지까지.
Write-Output ""
Write-Output "그림 PC 가 $Wait 초 안에 응답하지 않았습니다."
Write-Output "  · 완전히 꺼진 상태(종료)라면 메인보드 설정이 필요합니다:"
Write-Output "      BIOS/UEFI 에서 'Wake on LAN' 또는 'Power On by PCI-E' 를 켜고,"
Write-Output "      같은 화면의 'ErP Ready' / 'Deep Sleep' 은 끄세요."
Write-Output "      윈도에서도 '빠른 시작' 을 꺼야 합니다(종료가 사실은 최대절전이라 랜카드가 풀립니다)."
Write-Output "  · 절전(잠자기) 상태에서는 대개 그냥 됩니다 — 종료 대신 잠자기를 써 보세요."
Write-Output "  · 깨어났는데 ComfyUI 가 안 떴을 수도 있습니다: 그 PC 에서 run_comfyui.bat"
Write-Output "  · 글 작업(대화·스토리·장면 구성)은 그림 PC 없이도 그대로 됩니다."
exit 2
