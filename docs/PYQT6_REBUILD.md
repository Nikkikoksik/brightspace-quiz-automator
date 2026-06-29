# PyQt6 GUI

`gui_pyqt6.py` is now the production GUI. The old CustomTkinter app has been retired to `archive/gui_customtkinter_legacy.py` for reference only.

## How to run

```bash
python gui_pyqt6.py
```

`run.bat`, `run.sh`, `dev.py`, and installer launchers all point at the PyQt6 entry point.

## Current state

- Active panels: Staging, Quizzes, Assignments, Course Outline, Notes, Timer Fix, Content Cleaner, Queue, History, Settings
- Shared persistence path: `%APPDATA%/BrightspaceAutomator/`
- Worker-thread dialogs are handled by `_ThreadBridge(QObject)` and `pyqtSignal`
- Legacy CustomTkinter dependencies are no longer required for the active app

## Remaining Risk

- Real Brightspace/CourseBridge end-to-end testing is still needed after the migration cleanup.
- The archived GUI should not receive new features.
