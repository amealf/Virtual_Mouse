[Setup]
AppId=MediaPipeGestureController
AppName=MediaPipe Gesture Controller
AppVersion=0.2.1
AppPublisher=amealf
DefaultDirName={localappdata}\Programs\MediaPipeGestureController
DefaultGroupName=MediaPipe Gesture Controller
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=GestureController-Setup-0.2.1-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\GestureController.exe
LicenseFile=LICENSE

[Files]
Source: "dist-v0.2.1\GestureController\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MediaPipe Gesture Controller"; Filename: "{app}\GestureController.exe"
Name: "{autodesktop}\MediaPipe Gesture Controller"; Filename: "{app}\GestureController.exe"

[Run]
Filename: "{app}\GestureController.exe"; Description: "Launch MediaPipe Gesture Controller"; Flags: nowait postinstall skipifsilent unchecked
