# Guardar como: C:\dentfact\regen_bat.ps1
# Ejecutar con: powershell -ExecutionPolicy Bypass -File .\regen_bat.ps1

$contenido = @'
@echo off
setlocal EnableDelayedExpansion

:: ============================================================
::  GIT BATCH - Commit automatico con timestamp
::  Repo destino: https://github.com/alcjr/dentfact.git
::  Formato commit: hh:mm:ss / dd-mm-aaaa
::
::  Uso:
::    dentfact_git.bat          -> interactivo (pausa al final)
::    dentfact_git.bat /auto    -> sin pausa (Task Scheduler / CI)
::
::  v3 - ASCII puro + CRLF para evitar corrupcion de encoding.
:: ============================================================

set "REPO_URL=https://github.com/alcjr/dentfact.git"

set "MODO_AUTO=0"
if /I "%~1"=="/auto" set "MODO_AUTO=1"

echo.
echo ============================================
echo    GIT BATCH - Auto Commit y Push
echo ============================================
echo.

:: -----------------------------------------------------------
:: 1. Verificar que git esta instalado
:: -----------------------------------------------------------
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git no esta instalado o no esta en el PATH.
    echo          Instala Git desde https://git-scm.com/
    goto :FATAL
)
echo [OK] Git detectado correctamente.
echo.

:: -----------------------------------------------------------
:: 2. Verificar que estamos dentro de un repositorio Git
:: -----------------------------------------------------------
git rev-parse --git-dir >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No estas dentro de un repositorio Git.
    echo          Ejecuta este script desde la raiz de tu repo.
    goto :FATAL
)
echo [OK] Repositorio Git detectado.
echo.

:: -----------------------------------------------------------
:: 2.5. Forzar ejecucion desde la raiz del repositorio
:: -----------------------------------------------------------
set "REPO_ROOT="
for /f "delims=" %%r in ('git rev-parse --show-toplevel 2^>nul') do set "REPO_ROOT=%%r"
if "%REPO_ROOT%"=="" (
    echo [ERROR] No se pudo determinar la raiz del repositorio.
    goto :FATAL
)
if /I not "%CD%"=="%REPO_ROOT%" (
    echo [AVISO] Cambiando directorio de trabajo a la raiz del repo:
    echo         %REPO_ROOT%
    pushd "%REPO_ROOT%"
    if errorlevel 1 (
        echo [ERROR] No se pudo acceder a %REPO_ROOT%
        goto :FATAL
    )
) else (
    echo [OK] Ya estamos en la raiz del repositorio.
)
echo.

:: -----------------------------------------------------------
:: 3. Obtener rama actual
:: -----------------------------------------------------------
set "RAMA="
for /f "tokens=*" %%a in ('git rev-parse --abbrev-ref HEAD') do set "RAMA=%%a"
if "%RAMA%"=="" (
    echo [ERROR] No se pudo determinar la rama actual.
    goto :FATAL
)
if /I "%RAMA%"=="HEAD" (
    echo [ERROR] El repositorio esta en estado 'detached HEAD'.
    echo          Cambia a una rama antes de ejecutar este script.
    goto :FATAL
)
echo [INFO] Rama actual: %RAMA%
echo.

:: -----------------------------------------------------------
:: 3.5. Asegurar que 'origin' apunta a %REPO_URL%
:: -----------------------------------------------------------
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo [INFO] No existe el remoto 'origin'. Creandolo...
    git remote add origin %REPO_URL%
    if errorlevel 1 (
        echo [ERROR] No se pudo anadir el remoto 'origin'.
        goto :FATAL
    )
    echo [OK] Remoto 'origin' creado: %REPO_URL%
) else (
    set "ORIGIN_URL="
    for /f "tokens=*" %%u in ('git remote get-url origin') do set "ORIGIN_URL=%%u"
    if /I not "!ORIGIN_URL!"=="%REPO_URL%" (
        echo [AVISO] 'origin' apuntaba a: !ORIGIN_URL!
        echo         Corrigiendo a:      %REPO_URL%
        git remote set-url origin %REPO_URL%
        if errorlevel 1 (
            echo [ERROR] No se pudo actualizar la URL de 'origin'.
            goto :FATAL
        )
        echo [OK] Remoto 'origin' actualizado.
    ) else (
        echo [OK] Remoto 'origin' ya apunta a %REPO_URL%
    )
)
echo.

:: -----------------------------------------------------------
:: 3.7. Verificar identidad Git (user.name / user.email)
:: -----------------------------------------------------------
set "GIT_USER_NAME="
for /f "tokens=*" %%n in ('git config user.name 2^>nul') do set "GIT_USER_NAME=%%n"
set "GIT_USER_EMAIL="
for /f "tokens=*" %%e in ('git config user.email 2^>nul') do set "GIT_USER_EMAIL=%%e"

if "%GIT_USER_NAME%"=="" (
    echo [ERROR] Falta 'user.name' en la configuracion de Git.
    echo          Configura con:
    echo              git config --global user.name "Tu Nombre"
    goto :FATAL
)
if "%GIT_USER_EMAIL%"=="" (
    echo [ERROR] Falta 'user.email' en la configuracion de Git.
    echo          Configura con:
    echo              git config --global user.email "tu@correo.com"
    goto :FATAL
)
echo [OK] Identidad Git: %GIT_USER_NAME% ^<%GIT_USER_EMAIL%^>
echo.

:: -----------------------------------------------------------
:: 4. Obtener fecha y hora actual (robusto ante locale)
:: -----------------------------------------------------------
set "TIMESTAMP="
for /f "usebackq tokens=*" %%a in (`powershell -NoProfile -Command "Get-Date -Format 'HH:mm:ss / dd-MM-yyyy'"`) do set "TIMESTAMP=%%a"

if "%TIMESTAMP%"=="" (
    echo [AVISO] PowerShell no disponible. Usando fallback WMIC...
    set "DT="
    for /f "skip=1 tokens=2 delims==" %%a in ('wmic os get localdatetime /value 2^>nul') do (
        if not "%%a"=="" set "DT=%%a"
    )
    if not "!DT!"=="" (
        set "TIMESTAMP=!DT:~8,2!:!DT:~10,2!:!DT:~12,2! / !DT:~6,2!-!DT:~4,2!-!DT:~0,4!"
    )
)

if "%TIMESTAMP%"=="" (
    echo [ERROR] No se pudo obtener la fecha/hora del sistema.
    goto :FATAL
)
echo [INFO] Timestamp del commit: %TIMESTAMP%
echo.

:: -----------------------------------------------------------
:: 5. Verificar si hay cambios
:: -----------------------------------------------------------
set "HAY_CAMBIOS=0"
for /f %%a in ('git status --porcelain') do set "HAY_CAMBIOS=1"

if "%HAY_CAMBIOS%"=="0" (
    echo [AVISO] No hay cambios locales para commitear.
    echo         Se omite 'git add' y 'git commit'.
    echo.
    goto SYNC_AND_PUSH
)

:: -----------------------------------------------------------
:: 6. git add -A
:: -----------------------------------------------------------
echo [PASO 1/4] Ejecutando: git add -A
git add -A
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo al ejecutar 'git add -A'
    goto :FATAL
)
echo [OK] Archivos anadidos al staging area.
echo.

:: -----------------------------------------------------------
:: 7. git commit
:: -----------------------------------------------------------
echo [PASO 2/4] Ejecutando: git commit -m "%TIMESTAMP%"
git commit -m "%TIMESTAMP%"
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo al ejecutar 'git commit'.
    echo          Posibles causas:
    echo          - No hay cambios reales para commitear
    echo          - Un hook pre-commit rechazo el commit
    goto :FATAL
)
echo [OK] Commit realizado con exito.
echo.

:: -----------------------------------------------------------
:: 8. Sincronizar con el remoto: fetch + rebase condicional
::    NO se usa 'git pull --rebase' porque algunas versiones de
::    Git devuelven exit code 1 cuando la rama ya esta al dia,
::    provocando un falso error.
:: -----------------------------------------------------------
:SYNC_AND_PUSH

set "RAMA_REMOTA_EXISTE=0"
git ls-remote --exit-code --heads origin %RAMA% >nul 2>&1
if not errorlevel 1 set "RAMA_REMOTA_EXISTE=1"

if "%RAMA_REMOTA_EXISTE%"=="0" (
    echo [INFO] La rama remota 'origin/%RAMA%' no existe aun.
    echo        El push la creara con -u.
    echo.
    goto HACER_PUSH
)

echo [PASO 3/4] Sincronizando: git fetch origin %RAMA%
git fetch origin %RAMA%
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo 'git fetch origin %RAMA%'.
    echo          Posibles causas:
    echo          - No hay conexion a internet
    echo          - El remoto 'origin' no es accesible
    echo          - Problemas de autenticacion
    goto :FATAL
)

set "BEHIND=0"
for /f %%c in ('git rev-list --count HEAD..origin/%RAMA% 2^>nul') do set "BEHIND=%%c"

if "%BEHIND%"=="0" (
    echo [OK] Ya estamos al dia con origin/%RAMA%. Nada que rebasar.
) else (
    echo [INFO] Estamos %BEHIND% commit^(s^) detras del remoto. Ejecutando rebase...
    git rebase origin/%RAMA%
    if errorlevel 1 (
        echo.
        echo [ERROR] Fallo 'git rebase origin/%RAMA%'.
        echo          Resuelve los conflictos manualmente y ejecuta:
        echo              git rebase --continue
        echo              git push origin %RAMA%
        goto :FATAL
    )
    echo [OK] Rebase completado.
)
echo.

:HACER_PUSH
echo [PASO 4/4] Ejecutando: git push origin %RAMA%
git push origin %RAMA%
if errorlevel 1 (
    echo.
    echo [AVISO] 'git push origin %RAMA%' fallo. Reintentando con --set-upstream...
    git push -u origin %RAMA%
    if errorlevel 1 (
        echo.
        echo [ERROR] Fallo definitivo en 'git push'.
        echo          Posibles causas:
        echo          - No tienes permisos en el repositorio remoto
        echo          - Hay conflictos pendientes
        echo          - No tienes conexion a internet
        echo          - El remoto tiene commits que tu no tienes
        goto :FATAL
    )
)
echo [OK] Push realizado con exito a la rama '%RAMA%'.
echo.

:: -----------------------------------------------------------
:: 9. Resumen final
:: -----------------------------------------------------------
echo ============================================
echo              RESUMEN DE OPERACIONES
echo ============================================
echo  Repo:      %REPO_URL%
echo  Rama:      %RAMA%
echo  Commit:    %TIMESTAMP%
echo  Estado:    COMPLETADO CON EXITO
echo ============================================
echo.

if defined REPO_ROOT (
    popd 2>nul
)

endlocal
if "%MODO_AUTO%"=="1" exit /b 0
pause
exit /b 0

:: -----------------------------------------------------------
:: Salida controlada ante error
:: -----------------------------------------------------------
:FATAL
echo.
echo ============================================
echo    OPERACION ABORTADA POR ERROR
echo ============================================
if defined REPO_ROOT (
    popd 2>nul
)
endlocal
if "%MODO_AUTO%"=="1" exit /b 1
pause
exit /b 1
'@

# Escribir con codificacion ANSI (Windows-1252) y CRLF
$destino = 'C:\dentfact\dentfact_git.bat'

# Normalizar a CRLF
$contenido = $contenido -replace "`r`n", "`n" -replace "`n", "`r`n"

# Guardar como ANSI (Default de Windows en es-ES / cp1252)
[System.IO.File]::WriteAllText($destino, $contenido, [System.Text.Encoding]::Default)

Write-Host "[OK] Archivo escrito: $destino" -ForegroundColor Green
Write-Host "[OK] Codificacion: ANSI (Windows-1252)" -ForegroundColor Green
Write-Host "[OK] Terminaciones: CRLF" -ForegroundColor Green
Write-Host ""
Write-Host "Verificando primeros bytes..." -ForegroundColor Yellow
$bytes = [System.IO.File]::ReadAllBytes($destino)[0..15]
$hex = ($bytes | ForEach-Object { $_.ToString("X2") }) -join ' '
Write-Host "  Hex: $hex"
Write-Host "  (debe empezar con 40 65 63 68 6F 20 6F 66 66 0D 0A = '@echo off\r\n')"