@echo off
setlocal enabledelayedexpansion

:: =============================================================================
:: Paladino Quickstart Script (Windows)
:: Automates first-time setup: Docker, Neo4j, schema initialization, sample data
:: Usage: scripts\quickstart.bat
:: =============================================================================

:: --- Color helpers (Windows 10+ ANSI) ---
call :enable_ansi

set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "CYAN=[96m"
set "BOLD=[1m"
set "RESET=[0m"

set "PROJECT_DIR=%~dp0.."
pushd "%PROJECT_DIR%"

echo.
echo %BOLD%%CYAN%=============================================%RESET%
echo %BOLD%%CYAN%  Paladino Quickstart - Windows%RESET%
echo %BOLD%%CYAN%  Italian Public Funds Knowledge Graph%RESET%
echo %BOLD%%CYAN%=============================================%RESET%
echo.

:: =============================================================================
:: Step 1: Check Docker
:: =============================================================================
echo %CYAN%[1/5] Checking Docker...%RESET%

docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo %RED%ERROR: Docker is not running.%RESET%
    echo.
    echo Please start Docker Desktop and try again.
    echo   - Open Docker Desktop from the Start menu
    echo   - Wait for the whale icon to appear in the system tray
    echo   - Then re-run this script: scripts\quickstart.bat
    echo.
    popd
    exit /b 1
)
echo %GREEN%  Docker is running.%RESET%

:: =============================================================================
:: Step 2: Start Neo4j
:: =============================================================================
echo %CYAN%[2/5] Starting Neo4j...%RESET%

:: Check if Neo4j container is already running
docker ps --format "{{.Names}}" 2>nul | findstr /i "paladino-neo4j" >nul 2>&1
if %errorlevel% equ 0 (
    echo %YELLOW%  Neo4j is already running. Skipping start.%RESET%
) else (
    :: Check if container exists but is stopped
    docker ps -a --format "{{.Names}}" 2>nul | findstr /i "paladino-neo4j" >nul 2>&1
    if %errorlevel% equ 0 (
        echo %YELLOW%  Neo4j container exists but is stopped. Starting...%RESET%
        docker-compose up -d
        if %errorlevel% neq 0 (
            echo %RED%ERROR: Failed to start Neo4j.%RESET%
            echo Please check docker-compose.yml and your Docker installation.
            popd
            exit /b 1
        )
    ) else (
        echo   Pulling images and starting Neo4j...
        docker-compose up -d
        if %errorlevel% neq 0 (
            echo %RED%ERROR: Failed to start Neo4j.%RESET%
            echo Please check docker-compose.yml and your Docker installation.
            popd
            exit /b 1
        )
    )
    echo %GREEN%  Neo4j container started.%RESET%
)

:: =============================================================================
:: Step 3: Wait for Neo4j to be ready
:: =============================================================================
echo %CYAN%[3/5] Waiting for Neo4j to be ready...%RESET%

set "MAX_WAIT=60"
set "WAITED=0"
set "READY=0"

:wait_loop
if %WAITED% geq %MAX_WAIT% (
    echo %RED%ERROR: Neo4j did not become ready within %MAX_WAIT% seconds.%RESET%
    echo.
    echo Check container logs for details:
    echo   docker logs paladino-neo4j
    echo.
    echo Common issues:
    echo   - Not enough RAM (Neo4j requires at least 4GB available)
    echo   - Password not set correctly in .env (NEO4J_PASSWORD)
    echo   - Port 7687 already in use by another process
    echo.
    popd
    exit /b 1
)

:: Check if port 7687 is accepting connections
docker exec paladino-neo4j cypher-shell -u neo4j -p %NEO4J_PASSWORD% "RETURN 1" >nul 2>&1
if %errorlevel% equ 0 (
    set "READY=1"
    goto :neo4j_ready
)

:: Fallback: check if the port is open using PowerShell
powershell -Command "(New-Object System.Net.Sockets.TcpClient).ConnectAsync('localhost', 7687).Wait(1000)" >nul 2>&1
if %errorlevel% equ 0 (
    set "READY=1"
    goto :neo4j_ready
)

timeout /t 2 /nobreak >nul
set /a WAITED+=2

:: Show a dot progress indicator
echo   .
goto :wait_loop

:neo4j_ready
echo %GREEN%  Neo4j is ready (%WAITED%s).%RESET%

:: =============================================================================
:: Step 4: Initialize schema
:: =============================================================================
echo %CYAN%[4/5] Initializing database schema...%RESET%

python scripts\etl\init_schema.py
if %errorlevel% neq 0 (
    echo %RED%ERROR: Schema initialization failed.%RESET%
    echo.
    echo Check the output above for details.
    echo Common issues:
    echo   - Neo4j credentials in .env do not match NEO4J_AUTH in docker-compose.yml
    echo   - Neo4j is still starting up (wait a few more seconds and retry)
    echo   - Python dependencies not installed (run: pip install -e .)
    echo.
    popd
    exit /b 1
)
echo %GREEN%  Schema initialized successfully.%RESET%

:: =============================================================================
:: Step 5: Load sample data
:: =============================================================================
echo %CYAN%[5/5] Loading sample data...%RESET%

paladino load-samples
if %errorlevel% neq 0 (
    echo %YELLOW%WARNING: Sample data loading encountered issues.%RESET%
    echo This is non-critical. You can load data later via the CLI.
) else (
    echo %GREEN%  Sample data loaded successfully.%RESET%
)

:: =============================================================================
:: Success message
:: =============================================================================
echo.
echo %BOLD%%GREEN%=============================================%RESET%
echo %BOLD%%GREEN%  Setup Complete!%RESET%
echo %BOLD%%GREEN%=============================================%RESET%
echo.
echo %BOLD%Next steps:%RESET%
echo.
echo  1. Start the API server:
echo     %CYAN%paladino work --port 8000%RESET%
echo.
echo  2. Open interactive docs in your browser:
echo     %CYAN%http://localhost:8000/docs%RESET%
echo.
echo  3. Launch the Investigator shell:
echo     %CYAN%paladino investigate%RESET%
echo.

:: Show API key from .env
set "API_KEY="
for /f "tokens=1,* delims==" %%a in ('findstr /i "^API_KEYS=" .env 2^>nul') do (
    set "API_KEY=%%b"
)

if not "!API_KEY!"=="" (
    echo %BOLD%Your API Key:%RESET%
    echo     %CYAN%!API_KEY!%RESET%
    echo.
    echo   Use it in the X-API-Key header for API requests.
    echo.
) else (
    echo %YELLOW%NOTE: No API key found in .env. Set API_KEYS=your_key in .env to enable API authentication.%RESET%
    echo.
)

echo %BOLD%This script is idempotent -- safe to re-run at any time.%RESET%
echo.
popd
endlocal
exit /b 0

:: =============================================================================
:: Subroutine: Enable ANSI color codes on Windows
:: =============================================================================
:enable_ansi
for /f "tokens=2 delims=." %%a in ('ver') do set "WINVER=%%a"
set "WINVER=%WINVER: =%"
if %WINVER% geq 10 (
    reg add "HKCU\Console" /v VirtualTerminalLevel /t REG_DWORD /d 1 /f >nul 2>&1
)
goto :eof
