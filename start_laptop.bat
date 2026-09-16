@echo off
rem ============================================================
rem  ONE-CLICK LAUNCHER -- LAPTOP (main host)
rem ============================================================
rem  This machine holds the language model AND the data, so it
rem  starts both the model server and the web studio.
rem
rem  The picture engine (ComfyUI) needs the 3060, which lives in
rem  the desktop. We only point at it -- we cannot start it from
rem  here. Turn the desktop on when you want pictures; writing
rem  works with the desktop off.
rem
rem  Why -Llm http://127.0.0.1:8080/v1 :
rem    project\manifest.json is shared through git, so it cannot
rem    hold a different address for each machine. On THIS machine
rem    the model is local, so we override it for this run only.
rem    Calling yourself by your LAN address breaks every time DHCP
rem    hands out a new one.
rem
rem  Why a name (DESKTOP-06ACMT6) instead of an IP :
rem    Windows machines find each other by name on the same LAN,
rem    so this keeps working after the router changes addresses.
rem    Note the .local suffix: measured from the laptop, the bare
rem    name does NOT resolve (NetBIOS/LLMNR is off), but the mDNS
rem    form does -> DESKTOP-06ACMT6.local = 192.168.219.113.
rem    Name resolution is asymmetric here, so do not "simplify"
rem    this: desktop->laptop works with the bare name and fails
rem    with .local; laptop->desktop is the other way round.
rem    Measured http://DESKTOP-06ACMT6.local:8188 -> 200 in 0.25s.
rem
rem  -Trust <ip> lets ONE device in without the PIN (the phone).
rem    If the phone stops being let in, its address changed --
rem    open the studio on this machine, read the phone address it
rem    prints, and put it below. Reserving the address in the
rem    router settings makes this permanent.
rem ============================================================

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_studio.ps1" ^
  -Lan ^
  -Llm   "http://127.0.0.1:8080/v1" ^
  -Comfy "http://DESKTOP-06ACMT6.local:8188" ^
  -Trust "192.168.219.103" ^
  %*

if errorlevel 1 pause
