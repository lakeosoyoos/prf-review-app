; Inno Setup script — wraps the boot-tested .exe into a per-user installer.
; Built by CI (Gate 5) ONLY after the boot self-test (Gate 4) passes, so we never wrap a DOA app.
#define MyAppName "PRF Review"
#define MyAppExe  "PRF Review.exe"
#define MyAppVersion GetEnv('APP_VERSION')
#if MyAppVersion == ""
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=North Valley Insurance
DefaultDirName={autopf}\PRF Review
DefaultGroupName=PRF Review
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_out
OutputBaseFilename=PRF-Review-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\PRF Review.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Dirs]
; where the reviewer drops account folders (each containing account_config.yaml)
Name: "{app}\accounts"

[Icons]
Name: "{group}\PRF Review"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\PRF Review"; Filename: "{app}\{#MyAppExe}"

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch PRF Review now"; Flags: nowait postinstall skipifsilent
