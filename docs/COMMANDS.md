# Useful Commands

## Running the App

```powershell
# Launch the GUI (normal use)
.\run.bat

# Or directly
py gui.py
```

---

## Git — Step 0: Make sure you're in the right folder

```powershell
cd "c:\Users\300353682\OneDrive - Okanagan College\Desktop\Quiz automator\brightspace-quiz-automator"
```
> If you're one level up in `Quiz automator`, git commands will fail or affect the wrong files.

---

## Git — Step 0b: Check which branch you're on

```powershell
git branch
```
> The branch with `*` is your current one. You should always be on `nick` when making changes.
> If you're not: `git checkout nick`

---

## Git — Before Starting Work (run every session)

```powershell
git fetch
```
> Downloads latest changes from GitHub. Nothing changes locally yet — safe to run anytime.

```powershell
git checkout dev
git pull
```
> Switches to `dev` and pulls your teammates' latest changes.

```powershell
git checkout nick
git pull origin nick --rebase
```
> Switches back to your branch and pulls any changes you pushed from another machine.

```powershell
git rebase dev
```
> Replays your `nick` commits on top of the latest `dev`. Keeps you current without touching anyone else's branch.

```powershell
git push origin nick --force-with-lease
```
> Pushes your updated `nick` branch to GitHub. `--force-with-lease` is required after a rebase and is safe on your personal branch.

---

## Git — Committing and Pushing to Dev

```powershell
git add .
git commit -m "describe what you changed"
```
> Stage and commit all changed files.

```powershell
git switch dev
git push origin dev
git switch nick
```
> Switch to dev, push, then go back to your working branch.

---

## Git — See Recent Commits

```powershell
git log --oneline -10
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
