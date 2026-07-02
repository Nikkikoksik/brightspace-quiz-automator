import os
from pathlib import Path

VERSION      = "v0.8.6"
_ROOT        = Path(__file__).parent.parent
ICON_PATH    = str(_ROOT / "installer" / "assets" / "icon.ico")
USERDATA_DIR = Path(os.environ["APPDATA"]) / "BrightspaceAutomator"
USERDATA_DIR.mkdir(parents=True, exist_ok=True)

_CHECK_SVG = USERDATA_DIR / "check.svg"
_CHECK_SVG.write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">'
    '<polyline points="1.5,6 4.5,9.5 10.5,2.5" stroke="white" stroke-width="1.8"'
    ' fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
CHECK_SVG_PATH = str(_CHECK_SVG).replace("\\", "/")

COURSES_FILE        = str(USERDATA_DIR / "courses.txt")
OUTLINE_CFG         = str(USERDATA_DIR / "outline_config.json")
SESSION_FILE_GUI    = str(USERDATA_DIR / "session.json")
COURSE_HISTORY_FILE  = str(USERDATA_DIR / "course_history.json")
UNDO_SNAPSHOT_FILE   = str(USERDATA_DIR / "undo_snapshot.json")
