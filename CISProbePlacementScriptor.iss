#define AppVersion "0.3.2"

[Setup]
AppId={{7E55743D-55C1-4E9F-A392-7A3A12B8D05B}
AppName=CIS Probe Placement Scriptor
AppVersion={#AppVersion}
AppPublisher=yunhyok
DefaultDirName={autopf}\CISProbePlacementScriptor
DisableDirPage=no
DefaultGroupName=CIS Probe Placement Scriptor
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=CISProbePlacementScriptorSetup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=cisprobeplace\assets\app.ico
UninstallDisplayIcon={app}\CISProbePlacementScriptor.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Setup only adds and replaces files, so anything an earlier version shipped
; and this one does not would stay in the folder. A leftover package folder is
; then picked up by the new version and can keep it from starting. Remove the
; previous program files first; files kept elsewhere in the folder are untouched.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\CISProbePlacementScriptor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\CIS Probe Placement Scriptor"; Filename: "{app}\CISProbePlacementScriptor.exe"; AppUserModelID: "yunhyok.CISProbePlacementScriptor"
Name: "{commondesktop}\CIS Probe Placement Scriptor"; Filename: "{app}\CISProbePlacementScriptor.exe"; AppUserModelID: "yunhyok.CISProbePlacementScriptor"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\CISProbePlacementScriptor.exe"; Description: "Launch CIS Probe Placement Scriptor"; Flags: nowait postinstall skipifsilent
