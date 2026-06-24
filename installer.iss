; ============================================================
; installer.iss  —  Inno Setup 安装脚本
; 用于生成 Windows 安装包 PreDiligenceLab_Setup.exe
; ============================================================

#define MyAppName "Pre-Diligence Lab"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "PreDiligenceLab"
#define MyAppExeName "PreDiligenceLab.exe"

[Setup]
AppId={{59F79FCE-ECBD-4C84-AA49-1092217EA03D}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=PreDiligenceLab_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
; 如有图标取消注释：
; SetupIconFile=assets\icon.ico
; UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce

[Files]
; PyInstaller 实际产出 dist\PreDiligenceLab\ (目录)
; └─ PreDiligenceLab.exe
; └─ _internal\   (PyQt6/.pyd/.dll 等)
; 所以 Source 要指向整个目录
Source: "dist\PreDiligenceLab\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";          Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}";     Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";    Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
