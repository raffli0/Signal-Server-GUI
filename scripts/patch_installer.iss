; Inno Setup Script for Signal-Server GUI Update Patch
; Creates a lightweight 'SignalServerGUI-Update.exe' (~20MB)
; Updates an existing installation automatically without downloading heavy C++ / GDAL binaries.

#define MyAppName "Signal-Server GUI"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "RF Propagation Team"
#define MyAppURL "https://github.com/raffli0/Signal-Server-GUI"
#define MyAppExeName "SignalServerGUI.exe"

[Setup]
; Must match the AppId of the main installer so it updates the same installation folder
AppId={{D82F1B2C-745E-4B02-B831-C6843477F921}
AppName={#MyAppName} Update
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
UsePreviousAppDir=yes
DirExistsWarning=no
EnableDirDoesntExistWarning=no
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist-installer
OutputBaseFilename=SignalServerGUI-Update
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Update Patch
VersionInfoCopyright=Copyright (C) 2026 {#MyAppPublisher}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Only copies the updated GUI executable and _internal files (bin/ is omitted to keep download tiny)
Source: "..\dist-patch\SignalServerGUI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
