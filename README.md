# Brightspace Automator

> A desktop tool for Okanagan College instructors that automates repetitive Brightspace (D2L) tasks â€” bulk-updating quizzes, assignments, course outlines, and the staging process â€” so you can focus on teaching instead of clicking.

![Version](https://img.shields.io/badge/version-v0.8.0-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

---

## What it does

| Tool | What gets automated |
|---|---|
| **Staging** | Hides blueprint modules, switches course shells, copies content â€” the full Brightspace staging workflow, step by step |
| **Quiz Automator** | Sets every quiz in a course from *Not in Grade Book* â†’ *In Grade Book* and timer expiry â†’ *Auto-submit* |
| **Assignment Automator** | Sets every assignment to *In Grade Book* in one run |
| **Course Outline** | Downloads the course outline, converts it to HTML via CourseBridge, and pastes it into the *Course Syllabus* topic |
| **Timer Fix** | Re-runs only the auto-submit timer fix on quizzes (without touching grade book settings) |

---

## Download

Head to the [**Releases**](https://github.com/Nikkikoksik/brightspace-quiz-automator/releases) page and grab the latest installer for your platform.

| Platform | File |
|---|---|
| Windows | `BrightspaceAutomator-Setup.exe` â€” installs Python, packages, and Chromium automatically |
| macOS | `BrightspaceAutomator-mac.dmg` â€” drag to Applications, double-click `launch.command` |

> **First launch takes ~3â€“5 minutes** â€” Chromium (~180 MB) is downloaded once and cached.

---

## Running from source

```bash
# 1. Clone
git clone https://github.com/Nikkikoksik/brightspace-quiz-automator.git
cd brightspace-quiz-automator

# 2. Set up (creates .venv, installs packages, installs Chromium)
./setup.sh          # macOS / Linux
setup.bat           # Windows

# 3. Launch
./run.sh            # macOS / Linux
run.bat             # Windows
```

Or launch the GUI directly once dependencies are installed:

```bash
python gui_pyqt6.py
```

---

## How to use

1. **Launch** the app â€” the GUI opens to the **Staging** panel.
2. **Log in** once via **Settings â†’ Log in to Brightspace**. Your session is saved locally so you won't be asked again until it expires.
3. **Paste a course page URL** into the URL field of any panel (the main Brightspace course page URL works for all tools).
4. **Click Run** â€” the app opens a visible browser window so you can monitor progress.

### Tips

- You can add **multiple course URLs** to process them all in one run.
- Use **Dry Run** to preview what would change without saving anything.
- The **Resume** prompt lets you skip quizzes/assignments you've already processed if a run was interrupted.

---

## Auto-updates

The app checks for updates automatically on every launch. When a new version is available it downloads, installs, and prompts you to restart â€” no manual steps needed.

---

## Project structure

```
brightspace-quiz-automator/
├── gui_pyqt6.py             # GUI entry point (PyQt6)
├── gui/                     # PyQt6 panels, dialogs, theme, constants
├── archive/                 # Retired legacy GUI code
├── quiz_automator.py        # CLI fallback
├── src/                     # Browser automation modules
├── docs/                    # Internal documentation
├── installer/               # Installer scripts
└── .github/workflows/       # CI builds and releases
```

---

## Requirements

- Python 3.10+
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- [Playwright](https://playwright.dev/python/) (Chromium)
- [pdf2docx](https://github.com/ArtifexSoftware/pdf2docx)
- [watchdog](https://github.com/gorakhargosh/watchdog)

All installed automatically by the setup scripts or the Windows installer.

---

## Built for

Okanagan College instructors and course operations staff. The tool talks directly to `learn.okanagancollege.ca` using your own logged-in browser session â€” no API keys, no third-party access.

---

## License

MIT

