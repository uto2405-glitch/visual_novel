#  로그인하면 스튜디오가 저절로 뜨게 한다 (한 번만 실행하면 된다).
#
#  왜 필요한가 — 실제로 당했다. 2026-09-16 12:42, **윈도 업데이트가 노트북을 재부팅했다.**
#  사람이 끈 것이 아니고 예고도 없었다. 그때 llama-server 와 웹 스튜디오가 같이 사라졌고,
#  둘 다 손으로 띄운 것이라 **다시 뜨지 않았다.** 폰에서 열어 본 사람은 이유를 알 수 없다.
#  자동 시작이 없으면 이 일은 윈도 업데이트가 있을 때마다 되풀이된다.
#
#  방식은 '시작 프로그램 폴더의 바로가기' 하나다. 작업 스케줄러가 아닌 이유:
#    · 이 기계는 자동 로그인이 아니다 → '시스템 시작 시' 로 두면 로그인 전에 뜨는데,
#      그건 GUI 없는 세션이라 브라우저 자동 열기가 동작하지 않는다.
#    · 바로가기는 사람이 **눈으로 보고 지울 수 있다.** 스케줄러 항목은 숨어 있다.
#
#  사용:
#    powershell -ExecutionPolicy Bypass -File install_autostart.ps1            # 설치
#    powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove    # 해제
#    powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Target "F:\...\start_studio.bat"
#
#  관리자 권한이 필요 없다(내 계정의 시작 폴더에만 쓴다).

param(
    [string]$Target = "",          # 기본값: 같은 폴더의 start_laptop.bat
    [string]$Label  = "비주얼 노벨 스튜디오",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$repo = $PSScriptRoot
if (-not $Target) { $Target = Join-Path $repo "start_laptop.bat" }
$startup = [Environment]::GetFolderPath("Startup")
$link = Join-Path $startup ($Label + ".lnk")

Write-Output "============================================================"
Write-Output " 로그인 자동 시작"
Write-Output "============================================================"
Write-Output "  시작 폴더: $startup"

if ($Remove) {
    if (Test-Path $link) {
        # 지우기 전에 **어디를 가리키고 있었는지** 읽어 둔다. 그래야 나중에 손으로
        # 켜려는 사람에게 정확한 파일을 말해 줄 수 있다 — $Target 기본값이 아니라.
        $gone = ""
        try { $gone = (New-Object -ComObject WScript.Shell).CreateShortcut($link).TargetPath } catch { }
        Remove-Item $link -Force
        Write-Output "  해제했습니다: $link"
        Write-Output "  이제 로그인해도 저절로 뜨지 않습니다."
        if ($gone) { Write-Output "  직접 켜실 때는 이것을 누르세요: $gone" }
    } else {
        Write-Output "  걸려 있지 않았습니다 — 지울 것이 없습니다."
    }
    exit 0
}

if (-not (Test-Path $Target)) {
    Write-Output "[중단] 실행할 파일이 없습니다: $Target"
    Write-Output "  -Target 으로 직접 지정할 수 있습니다."
    exit 1
}

# 이미 걸려 있고 같은 곳을 가리키면 손대지 않는다 — 두 번 눌러도 안전해야 한다.
$w = New-Object -ComObject WScript.Shell
if (Test-Path $link) {
    $old = $w.CreateShortcut($link)
    if ($old.TargetPath -eq $Target) {
        Write-Output "  이미 걸려 있습니다 (같은 대상) — 그대로 둡니다."
        Write-Output "  대상: $Target"
        exit 0
    }
    Write-Output "  다른 대상이 걸려 있어 바꿉니다: $($old.TargetPath)"
}

$s = $w.CreateShortcut($link)
$s.TargetPath       = $Target
$s.WorkingDirectory = $repo
$s.WindowStyle      = 7          # 최소화 상태로 시작 — 창이 앞을 가리지 않게
$s.Description      = "로그인하면 글 엔진과 웹 스튜디오를 띄운다. 이 바로가기를 지우면 자동 시작만 멈춘다."
$s.Save()

if (Test-Path $link) {
    Write-Output "  걸었습니다: $link"
    Write-Output "  대상: $Target"
    Write-Output ""
    Write-Output "  이제 로그인하면 저절로 뜹니다. 지금 한 번 확인하려면 그 파일을 직접 눌러 보세요 —"
    Write-Output "  이미 떠 있는 것은 다시 띄우지 않으므로 두 번 눌러도 안전합니다."
    Write-Output "  끄려면:  powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove"
    Write-Output "  또는 실행 창에 shell:startup 을 치고 이 바로가기 하나를 지우면 됩니다."
} else {
    Write-Output "[중단] 바로가기를 만들지 못했습니다."
    exit 1
}
