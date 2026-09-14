@echo off
rem 더블클릭 한 번으로: 이미지 엔진(ComfyUI) -> 로컬 LLM -> 웹 스튜디오 -> 브라우저.
rem 인자는 그대로 start_studio.ps1 로 넘어간다 (예: start_studio.bat -Lan).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_studio.ps1" %*
if errorlevel 1 pause
