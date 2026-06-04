from pathlib import Path

COURSES_FILE = str(Path(__file__).parent / "courses.txt")

# Default settings used by the CLI (gui.py has its own checkboxes)
SETTINGS = {
    "set_in_gradebook": True,   # Not in Grade Book → In Grade Book
    "set_auto_submit":  True,   # Timer expiry → Automatically submit
}
