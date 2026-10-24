[Setup]
AppId={{67E840A9-69D6-45A4-A880-123456789001}
AppName=Dipesh Medical Hall
AppVersion=0.1.0
AppPublisher=Dipesh Medical Hall
DefaultDirName={autopf}\Dipesh Medical Hall
DefaultGroupName=Dipesh Medical Hall
OutputDir=installer-output
OutputBaseFilename=DipeshMedicalHall-Setup
ArchitecturesInstallIn64BitMode=x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\DipeshMedicalHall\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Dipesh Medical Hall"; Filename: "{app}\DipeshMedicalHall.exe"
Name: "{autodesktop}\Dipesh Medical Hall"; Filename: "{app}\DipeshMedicalHall.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\DipeshMedicalHall.exe"; Description: "Launch Dipesh Medical Hall"; Flags: postinstall nowait skipifsilent
