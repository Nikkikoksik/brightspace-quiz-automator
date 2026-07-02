from pathlib import Path

COURSES_FILE = str(Path(__file__).parent.parent / "courses.txt")

# Default settings used by the CLI (the GUI has its own settings menu)
SETTINGS = {
    "set_in_gradebook":     True,   # Not in Grade Book → In Grade Book
    "set_auto_submit":      True,   # Timer expiry → Automatically submit
    "rename_moodle_titles": False,  # Rename quiz titles containing Moodle → Brightspace
}
