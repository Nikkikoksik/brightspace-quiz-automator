import os
import subprocess

here = os.path.dirname(os.path.abspath(__file__))
py   = os.path.join(here, "python", "python.exe")
pyw  = os.path.join(here, "python", "pythonw.exe")

# Run updater with no window
subprocess.run(
    [py, os.path.join(here, "auto_update.py")],
    cwd=here,
    creationflags=0x08000000  # CREATE_NO_WINDOW
)

# Launch GUI detached
subprocess.Popen([pyw, os.path.join(here, "gui.py")], cwd=here)
