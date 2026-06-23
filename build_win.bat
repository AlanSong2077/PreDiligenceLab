@echo off
chcp 65001 >nul
REM ============================================================
REM build_win.bat  —  Windows 一键打包脚本
REM 输出：dist\PreDiligenceLab\PreDiligenceLab.exe（文件夹模式）
REM       dist\PreDiligenceLab_Setup.exe（可选，需 Inno Setup 6）
REM
REM 使用方法：
REM   1. 在 Windows 上双击运行，或在 cmd 中执行
REM   2. 需要 Python 3.10+（建议 3.11）
REM   3. 可选：安装 Inno Setup 6 生成安装包
REM      https://jrsoftware.org/isdl.php
REM ============================================================

echo.
echo  ╔══════════════════════════════════════╗
echo  ║     PreDiligenceLab Windows 打包工具    ║
echo  ╚══════════════════════════════════════╝
echo.

REM ── 检查 Python ──────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.10+
    echo         下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python 已找到

REM ── 1. 安装依赖 ───────────────────────────────────────────────
echo.
echo [1/4] 安装依赖...
pip install pyinstaller -q
if errorlevel 1 (
    echo [ERROR] pyinstaller 安装失败
    pause
    exit /b 1
)
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] 依赖安装失败，请检查 requirements.txt
    pause
    exit /b 1
)
echo [OK] 依赖安装完成

REM ── 2. 清理旧构建 ─────────────────────────────────────────────
echo.
echo [2/4] 清理旧构建...
if exist "build" rmdir /s /q "build"
if exist "dist\PreDiligenceLab" rmdir /s /q "dist\PreDiligenceLab"
echo [OK] 清理完成

REM ── 3. PyInstaller 打包（使用 .spec 文件）────────────────────
echo.
echo [3/4] PyInstaller 打包中（可能需要 2-5 分钟）...
pyinstaller PreDiligenceLab.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller 打包失败！
    echo         请检查上方错误信息
    pause
    exit /b 1
)
echo [OK] 打包完成 → dist\PreDiligenceLab\PreDiligenceLab.exe

REM ── 4. 生成 Inno Setup 安装包（可选）─────────────────────────
echo.
echo [4/4] 尝试生成安装包...

REM 写入 installer.iss
(
echo #define MyAppName "Pre-Diligence Lab"
echo #define MyAppVersion "1.0.0"
echo #define MyAppPublisher "PreDiligenceLab"
echo #define MyAppExeName "PreDiligenceLab.exe"
echo.
echo [Setup]
echo AppId={{59F79FCE-ECBD-4C84-AA49-1092217EA03D}
echo AppName={#MyAppName}
echo AppVersion={#MyAppVersion}
echo AppPublisher={#MyAppPublisher}
echo DefaultDirName={autopf}\{#MyAppName}
echo DefaultGroupName={#MyAppName}
echo AllowNoIcons=yes
echo OutputDir=dist
echo OutputBaseFilename=PreDiligenceLab_Setup
echo Compression=lzma
echo SolidCompression=yes
echo WizardStyle=modern
echo PrivilegesRequired=lowest
echo.
echo [Languages]
echo Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
echo.
echo [Tasks]
echo Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce
echo.
echo [Files]
echo Source: "dist\PreDiligenceLab\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
echo.
echo [Icons]
echo Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
echo Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
echo Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
echo.
echo [Run]
echo Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
) > installer.iss

REM 尝试调用 iscc
where iscc >nul 2>&1
if errorlevel 1 (
    echo [SKIP] 未找到 Inno Setup，跳过安装包生成
    echo        如需生成安装包，请安装 Inno Setup 6：
    echo        https://jrsoftware.org/isdl.php
    echo        安装后运行：iscc installer.iss
) else (
    iscc installer.iss
    if errorlevel 1 (
        echo [WARN] 安装包生成失败
    ) else (
        echo [OK] 安装包 → dist\PreDiligenceLab_Setup.exe
    )
)

REM ── 完成 ──────────────────────────────────────────────────────
echo.
echo  ============================================================
echo   打包完成！
echo.
echo   直接运行：dist\PreDiligenceLab\PreDiligenceLab.exe
if exist "dist\PreDiligenceLab_Setup.exe" (
    echo   安装包：  dist\PreDiligenceLab_Setup.exe
)
echo.
echo   把整个 dist\PreDiligenceLab\ 文件夹发给别人即可使用
echo   （或发送安装包 PreDiligenceLab_Setup.exe）
echo  ============================================================
echo.
pause
