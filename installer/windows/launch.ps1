$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir

$bundled = Join-Path $dir "python\pythonw.exe"
if (Test-Path $bundled) { $py = $bundled } else { $py = "pythonw" }

Start-Process $py -ArgumentList "src\auto_update.py" -Wait -WindowStyle Hidden
Start-Process $py -ArgumentList "gui.py" -WindowStyle Hidden
