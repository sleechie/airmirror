; Per-user installer: no admin rights, installs to %LOCALAPPDATA%\Programs\AirMirror.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{0F64D728-CA7D-44BD-B838-09FC40148AA2}
AppName=AirMirror
AppVersion={#AppVersion}
AppPublisher=AirMirror contributors
AppPublisherURL=https://github.com/sleechie/airmirror
DefaultDirName={localappdata}\Programs\AirMirror
DefaultGroupName=AirMirror
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AirMirrorSetup
SetupIconFile=..\build\airmirror.ico
UninstallDisplayIcon={app}\AirMirror.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Tasks]
Name: "startup"; Description: "Start AirMirror when I sign in (recommended)"; GroupDescription: "Options:"

[Files]
Source: "..\dist\AirMirror\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\AirMirror"; Filename: "{app}\AirMirror.exe"; Comment: "Mirror your screen to an AirPlay TV"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AirMirror"; ValueData: """{app}\AirMirror.exe"""; Tasks: startup; Flags: uninsdeletevalue
; The tray menu's "Start with Windows" toggle writes the same value; always remove it on uninstall.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "AirMirror"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\AirMirror.exe"; Description: "Start AirMirror now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im AirMirror.exe"; Flags: runhidden; RunOnceId: "StopAirMirror"
