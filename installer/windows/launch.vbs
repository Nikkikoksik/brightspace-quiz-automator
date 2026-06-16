Set oFSO   = CreateObject("Scripting.FileSystemObject")
Set oShell = CreateObject("WScript.Shell")

scriptDir = oFSO.GetParentFolderName(WScript.ScriptFullName)
oShell.CurrentDirectory = scriptDir

bundled = scriptDir & "\python\pythonw.exe"
If oFSO.FileExists(bundled) Then
    pyW = Chr(34) & bundled & Chr(34)
Else
    pyW = "pythonw"
End If

oShell.Run pyW & " src\auto_update.py", 0, True
oShell.Run pyW & " gui.py", 0, False
