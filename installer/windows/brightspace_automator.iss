#ifndef MyAppVersion
#define MyAppVersion "0.6.0"
#endif

[Setup]
AppName=Brightspace Automator
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\BrightspaceAutomator
PrivilegesRequired=lowest
SetupIconFile=..\assets\icon.ico
OutputBaseFilename=BrightspaceAutomator-Setup
OutputDir=Output

[Files]
; App source files (all .py to app root)
Source: "..\..\*.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; Production launchers at app root
Source: "launch.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.pyw"; DestDir: "{app}"; Flags: ignoreversion
; Icon
Source: "..\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
; Python installer (runs silently, then deletes itself)
Source: "python-3.12.10-amd64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Run]
; 1. Install Python privately
Filename: "{tmp}\python-3.12.10-amd64.exe"; Parameters: "/quiet InstallAllUsers=0 TargetDir=""{app}\python"" PrependPath=0"; StatusMsg: "Installing Python..."

; 2. pip install all dependencies
Filename: "{app}\python\python.exe"; Parameters: "-m pip install --quiet customtkinter playwright pdf2docx watchdog"; StatusMsg: "Installing packages..."; Flags: runhidden

; 3. Download Chromium (first time only — ~180MB, takes ~2 min)
Filename: "{app}\python\python.exe"; Parameters: "-m playwright install chromium"; StatusMsg: "Installing Chromium browser (one-time, ~3 min)..."

[Icons]
Name: "{userdesktop}\Brightspace Automator"; Filename: "{app}\launch.bat"; IconFilename: "{app}\icon.ico"; WorkingDir: "{app}"
Name: "{group}\Brightspace Automator"; Filename: "{app}\launch.bat"; IconFilename: "{app}\icon.ico"; WorkingDir: "{app}"
Name: "{group}\Uninstall"; Filename: "{uninstallexe}"

[UninstallDelete]
; Only remove code files — preserve all user data
Type: files; Name: "{app}\*.py"
Type: files; Name: "{app}\launch.bat"
Type: files; Name: "{app}\requirements.txt"
Type: files; Name: "{app}\icon.ico"
