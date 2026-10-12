@echo off
REM ClinicERP v2 - server installer for Windows (Docker Desktop).
REM
REM Safe to run again: it keeps existing secrets, certificates and data, rebuilds the
REM containers and only creates an administrator when none exists yet.
REM
REM Usage: install.bat [options]   (run install.bat --help for the list)

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
where docker >nul 2>&1
if errorlevel 1 (
  call :die "Docker is not installed. Install Docker Desktop first: https://docs.docker.com/desktop/install/windows-install/"
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  call :die "Docker is installed but not running. Start Docker Desktop, wait until it is ready, and run this script again."
  exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
  call :die "Docker Compose is not available. Update Docker Desktop."
  exit /b 1
)
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
  call :env_set "%API_ENV%" CLINIC_SECRET_KEY "!SECRET!"
  call :ok "Generated a new session signing key"
)

call :env_get "%API_ENV%" CLINIC_BACKUP_ENCRYPTION_KEY FERNET
if "!FERNET!"=="" (
  for /f "delims=" %%k in ('powershell -NoProfile -Command "$b=New-Object byte[] 32; [Security.Cryptography.RNGCryptoServiceProvider]::new().GetBytes($b); [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_')"') do set "FERNET=%%k"
  call :env_set "%API_ENV%" CLINIC_BACKUP_ENCRYPTION_KEY "!FERNET!"
  call :ok "Generated a backup encryption key"
)
call :env_set "%API_ENV%" CLINIC_COOKIE_SECURE true

REM ports and off-site folder live in the root .env that docker compose reads
if "%HTTP_PORT%"=="" call :env_get "%ROOT_ENV%" HTTP_PORT HTTP_PORT
if "%HTTP_PORT%"=="" set "HTTP_PORT=80"
if "%HTTPS_PORT%"=="" call :env_get "%ROOT_ENV%" HTTPS_PORT HTTPS_PORT
if "%HTTPS_PORT%"=="" set "HTTPS_PORT=443"
if "%OFFSITE%"=="" call :env_get "%ROOT_ENV%" OFFSITE_BACKUP_PATH OFFSITE
if "%OFFSITE%"=="" set "OFFSITE=./offsite-backups"
call :env_set "%ROOT_ENV%" COMPOSE_PROJECT_NAME clinicerp
call :env_set "%ROOT_ENV%" HTTP_PORT "%HTTP_PORT%"
call :env_set "%ROOT_ENV%" HTTPS_PORT "%HTTPS_PORT%"
call :env_set "%ROOT_ENV%" OFFSITE_BACKUP_PATH "%OFFSITE%"
set "OFFSITE_DIR=%OFFSITE:/=\%"
if not exist "%OFFSITE_DIR%" mkdir "%OFFSITE_DIR%"
call :ok "Ports: HTTP %HTTP_PORT%, HTTPS %HTTPS_PORT%. Off-server backups: %OFFSITE%"

REM ------------------------------------------------------------------ TLS certificate
call :info "Preparing the TLS certificate"
if not exist "deploy\certs" mkdir "deploy\certs"
if not "%CERT%%KEY%"=="" (
  if not exist "%CERT%" (
    call :die "--cert file not found: %CERT%"
    exit /b 1
  )
  if not exist "%KEY%" (
    call :die "--key file not found: %KEY%"
    exit /b 1
  )
  copy /y "%CERT%" "deploy\certs\fullchain.pem" >nul
  copy /y "%KEY%" "deploy\certs\privkey.pem" >nul
  call :ok "Installed your certificate"
  goto cert_done
)
if exist "deploy\certs\fullchain.pem" if exist "deploy\certs\privkey.pem" (
  call :ok "Keeping the existing certificate in deploy\certs"
  goto cert_done
)
docker run --rm -v "%ROOT%\deploy\certs:/certs" alpine/openssl req -x509 -nodes -newkey rsa:2048 -days 825 -subj "/CN=%DOMAIN%" -addext "subjectAltName=DNS:%DOMAIN%,DNS:localhost,IP:127.0.0.1" -keyout /certs/privkey.pem -out /certs/fullchain.pem >nul 2>&1
if not exist "deploy\certs\fullchain.pem" (
  call :die "Could not create a TLS certificate."
  exit /b 1
)
call :ok "Created a self-signed certificate for %DOMAIN% (browsers will warn until you install a real one)"
:cert_done

REM ------------------------------------------------------------------ build and start
call :info "Building and starting the containers (the first build can take several minutes)"
docker compose up -d --build
if errorlevel 1 (
  call :warn "Build failed - retrying once (slow networks often time out on the first try)"
  docker compose up -d --build
  if errorlevel 1 (
    call :die "docker compose failed. See the messages above."
    exit /b 1
  )
)

call :info "Waiting for the API to become ready"
set /a TRIES=0
:wait_api
docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" >nul 2>&1
if not errorlevel 1 goto api_up
set /a TRIES+=1
if !TRIES! geq 60 (
  docker compose logs --tail 50 api
  call :die "The API did not start. See the log above."
  exit /b 1
)
timeout /t 2 /nobreak >nul
goto wait_api
:api_up
call :ok "API is up"

REM ------------------------------------------------------------------ first administrator
set "ADMINS=0"
for /f "delims=" %%a in ('docker compose exec -T api python -m app.cli admin-count 2^>nul') do set "ADMINS=%%a"
if "!ADMINS!"=="0" (
  call :info "Creating the first administrator '%ADMIN%'"
  docker compose exec -T api python -m app.cli create-admin "%ADMIN%"
  call :warn "Write the one-time password down now; it is shown only once."
) else (
  call :ok "An administrator already exists; no account was created"
)

REM ------------------------------------------------------------------ done
set "PORT_SUFFIX="
if not "%HTTPS_PORT%"=="443" set "PORT_SUFFIX=:%HTTPS_PORT%"
echo.
call :ok "ClinicERP is running: https://%DOMAIN%%PORT_SUFFIX%"
echo.
echo   Useful commands (run in %ROOT%):
echo     docker compose ps                  - container status
echo     docker compose logs -f             - follow logs
echo     docker compose exec api python -m app.cli backup   - backup now
echo     docker compose down                - stop (data is kept in the 'clinic-data' volume)
echo     install.bat                        - update after pulling new code
echo.
echo   Keep a copy of backend\.env somewhere safe: without CLINIC_BACKUP_ENCRYPTION_KEY
echo   the encrypted backups cannot be restored.
endlocal
exit /b 0

REM ================================================================== helpers
:info
echo ==^> %~1
exit /b 0

:ok
echo  OK %~1
exit /b 0

:warn
echo  WARNING: %~1
exit /b 0

:die
echo ERROR: %~1 1>&2
exit /b 1

:usage
echo ClinicERP v2 - server installer for Windows (Docker Desktop).
echo.
echo Usage: install.bat [options]
echo   --domain NAME        Host name for the self-signed certificate (default: this computer's name)
echo   --admin NAME         Username of the first administrator (default: admin)
echo   --http-port N        HTTP port, redirects to HTTPS (default: 80)
echo   --https-port N       HTTPS port (default: 443)
echo   --offsite PATH       Folder for off-server backup copies (default: .\offsite-backups)
echo   --cert FILE --key FILE   Use your own TLS certificate instead of a self-signed one
echo   --help               Show this help
exit /b 0

:env_get
REM env_get FILE KEY OUTVAR - value of KEY= in FILE (empty if missing)
set "%~3="
if not exist "%~1" exit /b 0
for /f "usebackq tokens=1,* delims==" %%a in ("%~1") do (
  if /i "%%a"=="%~2" set "%~3=%%b"
)
exit /b 0

:env_set
REM env_set FILE KEY VALUE - replace or append KEY=VALUE (UTF-8 without BOM, as docker compose expects)
powershell -NoProfile -Command "$f = Join-Path (Get-Location) '%~1'; $k = '%~2'; $v = '%~3'; $lines = @(); if (Test-Path $f) { $lines = @(Get-Content $f | Where-Object { -not $_.StartsWith($k + '=') }) }; $lines += ($k + '=' + $v); [IO.File]::WriteAllLines($f, [string[]]$lines)"
exit /b 0
