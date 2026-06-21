#define AppVersion "0.1.1"

[Setup]
AppId={{7E55743D-55C1-4E9F-A392-7A3A12B8D05B}
AppName=CIS Probe Placement Scriptor
AppVersion={#AppVersion}
AppPublisher=yunhyok
DefaultDirName={autopf}\CISProbePlacementScriptor
DefaultGroupName=CIS Probe Placement Scriptor
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=CISProbePlacementScriptorSetup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\CISProbePlacementScriptor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\CIS Probe Placement Scriptor"; Filename: "{app}\CISProbePlacementScriptor.exe"
Name: "{commondesktop}\CIS Probe Placement Scriptor"; Filename: "{app}\CISProbePlacementScriptor.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\CISProbePlacementScriptor.exe"; Description: "Launch CIS Probe Placement Scriptor"; Flags: nowait postinstall skipifsilent
