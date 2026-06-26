# PyQt6 GUI Rebuild — WIP (`nick` branch)

`gui_pyqt6.py` is a full rebuild of `gui.py` using PyQt6 instead of CustomTkinter.
Keep on `nick` branch until ready to ship (it's a surprise for co-workers).

## How to run
```
python gui_pyqt6.py
# Side-by-side comparison (PowerShell):
Start-Process python -ArgumentList "gui.py"; Start-Process python -ArgumentList "gui_pyqt6.py"
```

## Current state (as of 2026-06-15)
- All 9 panels built and wired: Staging, Quizzes, Assignments, Course Outline, Notes, Timer Fix, Queue, History, Settings
- Slate theme: bg `#0d1117`, sidebar `#010409`, accent `#0ea5e9`
- App icon wired from `installer/assets/icon.ico` (shows in taskbar)
- Checkboxes: white checkmark SVG written to `%APPDATA%/BrightspaceAutomator/check.svg` at startup
- Cross-thread UI handled by `_ThreadBridge(QObject)` with `pyqtSignal`
- `run.bat` still points at `gui.py` — production untouched

## What still needs work
- **Collapsible sidebar** — not built yet
- **Visual polish** — 1:1 port of old layout; needs proper redesign
  - Ideas: progress indicators, colored log prefixes (✓/⚠/✗), cards with icons, inline session status, run history badge on nav
- **Functional testing** — panels wired to same backend as `gui.py` but untested end-to-end
- **Timer Fix panel bug** — `_add_url_row` passes `self._tfix_url_rows` instead of `self._tfix_url_container`; fix before testing

## Key architecture differences vs `gui.py`
| Old (CustomTkinter) | New (PyQt6) |
|---|---|
| `root.after()` | `QTimer` |
| Grid show/hide panels | `QStackedWidget` |
| `root.after(0, show)` cross-thread | `_ThreadBridge(QObject)` + `pyqtSignal` |
| `CTkToplevel` ask-range popup | `_RangeDialog(QDialog)` |

All persistence files and paths are identical — same `%APPDATA%/BrightspaceAutomator/` location.
