# Useful Commands

## Running the App

```powershell
# Launch the GUI (normal use)
.\run.bat

# Or directly
py gui.py
```

---

## Git — Daily Use

```powershell
# See what's changed locally
git status

# Pull latest changes from GitHub (e.g. after your friend pushes)
git pull

# Push your changes to GitHub
git add -A
git commit -m "describe what you changed"
git push

# See recent commits
git log --oneline -10
```

---

## Git — If Push Is Rejected (friend pushed first)

```powershell
git pull
git push
```

---

## Installing / Updating Dependencies

```powershell
# Install everything needed
py -m pip install playwright customtkinter pdf2docx

# Install Playwright browsers (only needed once, or after reinstall)
py -m playwright install chromium
```

---

## Clearing Saved Sessions (force re-login)

```powershell
# Delete Brightspace session (will ask to log in again next run)
del session.json

# Delete CourseBridge session
del cb_session.json

# Delete both
del session.json, cb_session.json
```

---

## Clearing Saved GUI Config (credentials / course URL)

```powershell
del outline_config.json
```

---

## GitHub Repo

https://github.com/Nikkikoksik/brightspace-quiz-automator
