#define AppName "CKO Modbus Inspector"
#define AppVersion "0.2.6"
#define AppPublisher "CKO Toolbox"
#define AppExeName "CKO-Modbus-Inspector.exe"

[Setup]
AppId={{D13D8DBE-BCFC-4E40-9C2B-0D37DD81B6E9}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\CKO Modbus Inspector
DefaultGroupName=CKO Toolbox
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=CKO-Modbus-Inspector-Setup
SetupIconFile=..\cko_logo.ico
UninstallDisplayIcon={app}\CKO-Modbus-Inspector.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Symbole:"

[Files]
Source: "..\dist\CKO-Modbus-Inspector\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\cko_logo.ico"; DestDir: "{app}"; DestName: "CKO-Modbus-Inspector.ico"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\CKO-Modbus-Inspector.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\CKO-Modbus-Inspector.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{#AppName} starten"; Flags: nowait postinstall skipifsilent
