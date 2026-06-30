# Useful Commands

## Running the App

```powershell
# DEV — test your local edits (no GitHub pull, safe with uncommitted changes)
.\dev.bat

# PRODUCTION — what coworkers actually run (pulls latest from GitHub FIRST)
.\run.bat
```
> **`run.bat` overwrites uncommitted local changes** with whatever is on GitHub `main`.
> Never run it while you have edits in VS Code you haven't committed yet — it WILL wipe them.
> Use `dev.bat` for all day-to-day testing. Only use `run.bat` to confirm what coworkers will get
> (and only after you've pushed your changes to `main`).

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

## Git — Am I Synced to GitHub?

```powershell
git status -sb
```
> Top line looks like `## nick...origin/nick`. No `[ahead N]` or `[behind M]` after it = your branch
> matches GitHub exactly. Any line below starting with `M` (modified) or `??` (new/untracked) means
> you have uncommitted changes — those are NOT on GitHub yet, and `run.bat` would wipe them.

```powershell
# Confirm main, dev, and nick are all the same commit (fully promoted + synced)
git log --oneline -1 nick
git log --oneline -1 dev
git log --oneline -1 main
```
> Same commit hash on all three = everything is synced top to bottom.

---

## Git — Ignoring a File
```powershell
#Stop tracking a file git already knows about
git rm --cached filename.txt

# Then add it to .gitignore so git never picks it up again
echo "filename.txt" >> .gitignore

# >> — means "take whatever is on my left and append it to the file on my right." Append means add to the end without touching what's already there.

# Commit the .gitignore change
git add .gitignore
git commit -m "Ignore filename.txt"

```

> Use this for personal notes, test files, or    anything that should 
> only live on your computer.

## Git — Before Starting Work (run every session)

```powershell
git fetch origin                        # download latest changes from GitHub (doesn't touch your files yet)
git status -sb                          # check you're synced and have no uncommitted changes (see below)
```
> If `nick` is behind `origin/nick`, someone (or another session) pushed since you last worked here —
> `git pull` to catch up before making changes. If you have uncommitted changes, commit or discuss
> them first; don't pull on top of dirty local edits.

---

## Git — Save Your Work and Sync All Branches

This is the full recipe: commit your changes, push nick, then promote nick → dev → main.
Only promote to main once you've actually tested the change (run it via `dev.bat` and confirm it works).

```powershell
# 1. Save your work to nick
git add -A                                # stage all changed/new files
                                           # or specific files: git add gui.py src/actions.py
git commit -m "describe what you changed"
git push origin nick

# 2. Promote nick -> dev
git checkout dev
git merge --ff-only nick
git push origin dev

# 3. Promote dev -> main (coworkers get this on their next run.bat)
git checkout main
git merge --ff-only dev
git push origin main

# 4. Go back to your working branch
git checkout nick
```

> **`--ff-only`** means "only merge if it's a clean fast-forward — refuse if histories diverged."
> If a merge step FAILS with "not possible to fast-forward," STOP and ask for help instead of
> forcing it — it means dev or main has commits that nick doesn't (e.g. someone else pushed, or a
> branch fell behind). Resolving that safely needs a look at what's different first.

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
