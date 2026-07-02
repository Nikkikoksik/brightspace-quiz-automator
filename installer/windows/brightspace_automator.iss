#ifndef MyAppVersion
#define MyAppVersion "0.8.0"
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
; Entry-point scripts at app root
Source: "..\..\gui_pyqt6.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\quiz_automator.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dev.py"; DestDir: "{app}"; Flags: ignoreversion
; PyQt6 GUI package
Source: "..\..\gui\*.py"; DestDir: "{app}\gui"; Flags: ignoreversion recursesubdirs createallsubdirs
; Library modules under src\
Source: "..\..\src\*.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "..\..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
; Production launcher at app root
Source: "launch.bat"; DestDir: "{app}"; Flags: ignoreversion
; Icon — path must match gui/constants.py's ICON_PATH ({app}\installer\assets\icon.ico)
Source: "..\assets\icon.ico"; DestDir: "{app}\installer\assets"; Flags: ignoreversion
; Python installer (runs silently, then deletes itself)
Source: "python-3.12.10-amd64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Run]
; 1. Install Python privately
Filename: "{tmp}\python-3.12.10-amd64.exe"; Parameters: "/quiet InstallAllUsers=0 TargetDir=""{app}\python"" PrependPath=0"; StatusMsg: "Installing Python..."

; 2. pip install all dependencies
Filename: "{app}\python\python.exe"; Parameters: "-m pip install --quiet -r ""{app}\requirements.txt"""; StatusMsg: "Installing packages..."; Flags: runhidden

; 3. Download Chromium (first time only — ~180MB, takes ~2 min)
Filename: "{app}\python\python.exe"; Parameters: "-m playwright install chromium"; StatusMsg: "Installing Chromium browser (one-time, ~3 min)..."

[Icons]
Name: "{userdesktop}\Brightspace Automator"; Filename: "{app}\launch.bat"; IconFilename: "{app}\installer\assets\icon.ico"; WorkingDir: "{app}"
Name: "{group}\Brightspace Automator"; Filename: "{app}\launch.bat"; IconFilename: "{app}\installer\assets\icon.ico"; WorkingDir: "{app}"
Name: "{group}\Uninstall"; Filename: "{uninstallexe}"

[UninstallDelete]
; Only remove code files — preserve all user data
Type: files; Name: "{app}\*.py"
Type: filesandordirs; Name: "{app}\gui"
Type: files; Name: "{app}\src\*.py"
Type: dirifempty; Name: "{app}\src"
Type: files; Name: "{app}\launch.bat"
Type: files; Name: "{app}\requirements.txt"
Type: filesandordirs; Name: "{app}\installer"
