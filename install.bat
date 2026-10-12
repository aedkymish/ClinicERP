@echo off
REM ClinicERP v2 - server installer for Windows (Docker Desktop).
REM
REM Safe to run again: it keeps existing secrets, certificates and data, rebuilds the
REM containers and only creates an administrator when none exists yet.
REM
REM Usage: install.bat [options]
REM   --domain NAME        Host name for the self-signed certificate (default: this computer's name)
REM   --admin NAME         Username of the first administrator (default: admin)
REM   --http-port N        HTTP port, redirects to HTTPS (default: 80)
REM   --https-port N       HTTPS port (default: 443)
REM   --offsite PATH       Folder for off-server backup copies, e.g. a mapped NAS share (default: .\offsite-backups)
REM   --cert FILE --key FILE   Use your own TLS certificate instead of a self-signed one
REM   --help               Show this help

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%CD%"

set "DOMAIN=%COMPUTERNAME%"
set "ADMIN=admin"
set "HTTP_PORT="
set "HTTPS_PORT="
set "OFFSITE="
set "CERT="
set "KEY="

:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--domain"     (set "DOMAIN=%~2" & shift & shift & goto parse)
if /i "%~1"=="--admin"      (set "ADMIN=%~2" & shift & shift & goto parse)
if /i "%~1"=="--http-port"  (set "HTTP_PORT=%~2" & shift & shift & goto parse)
if /i "%~1"=="--https-port" (set "HTTPS_PORT=%~2" & shift & shift & goto parse)
if /i "%~1"=="--offsite"    (set "OFFSITE=%~2" & shift & shift & goto parse)
if /i "%~1"=="--cert"       (set "CERT=%~2" & shift & shift & goto parse)
if /i "%~1"=="--key"        (set "KEY=%~2" & shift & shift & goto parse)
if /i "%~1"=="--help"       goto usage
if /i "%~1"=="-h"           goto usage
call :die "Unknown option: %~1 (see --help)"
exit /b 1
:parsed

REM ------------------------------------------------------------------ prerequisites
call :info "Checking Docker"
where docker >nul 2>&1 || (call :die "Docker is not installed. Install Docker Desktop first: https://docs.docker.com/desktop/install/windows-install/" & exit /b 1)
docker info >nul 2>&1 || (call :die "Docker is installed but not running. Start Docker Desktop, wait until it is ready, and run this script again." & exit /b 1)
docker compose version >nul 2>&1 || (call :die "Docker Compose is not available. Update Docker Desktop." & exit /b 1)
for /f "delims=" %%v in ('docker --version') do call :ok "%%v"

REM ------------------------------------------------------------------ settings
call :info "Preparing configuration"
set "API_ENV=backend\.env"
set "ROOT_ENV=.env"
if not exist "%API_ENV%" (
  copy /y "backend\.env.example" "%API_ENV%" >nul
  call :ok "Created %API_ENV%"
)

call :env_get "%API_ENV%" CLINIC_SECRET_KEY SECRET
if "!SECRET!"=="" set "SECRET=generate"
if /i "!SECRET:~0,8!"=="generate" (
  for /f "delims=" %%k in ('powershell -NoProfile -Command "$b=New-Object byte[] 48; [Security.Cryptography.RNGCryptoServiceProvider]::new().GetBytes($b); ([Convert]::ToBase64String($b) -replace '[+/=]','').Substring(0,60)"') do set "SECRET=%%k"
  call :env_set
REM env_set FILE KEY VALUE - replace or append KEY=VALUE (UTF-8 without BOM, as docker compose expects)
powershell -NoProfile -Command ^
  "$f = Join-Path (Get-Location) '%~1'; $k = '%~2'; $v = '%~3';" ^
  "$lines = @(); if (Test-Path $f) { $lines = @(Get-Content $f | Where-Object { -not $_.StartsWith($k + '=') }) };" ^
  "$lines += ($k + '=' + $v);" ^
  "[IO.File]::WriteAllLines($f, [string[]]$lines)"
exit /b 0
