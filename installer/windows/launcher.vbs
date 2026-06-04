Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir     = fso.GetParentFolderName(WScript.ScriptFullName)

sh.CurrentDirectory = dir
sh.Run """" & dir & "\python\python.exe"" auto_update.py", 1, True
sh.Run """" & dir & "\python\pythonw.exe"" gui.py", 1, False
