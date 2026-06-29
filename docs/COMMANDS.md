# Useful Commands

## Running the App

```powershell
# Launch the GUI (normal use)
.\run.bat

# Or directly
py gui_pyqt6.py
```

---

## Git â€” Step 0: Make sure you're in the right folder

```powershell
cd "c:\Users\300353682\OneDrive - Okanagan College\Desktop\Quiz automator\brightspace-quiz-automator"
```
> If you're one level up in `Quiz automator`, git commands will fail or affect the wrong files.

---

## Git â€” Step 0b: Check which branch you're on

```powershell
git branch
```
> The branch with `*` is your current one. You should always be on `nick` when making changes.
> If you're not: `git checkout nick`

---

## Git â€” Ignoring a File
```powershell
#Stop tracking a file git already knows about
git rm --cached filename.txt

# Then add it to .gitignore so git never picks it up again
echo "filename.txt" >> .gitignore

# >> â€” means "take whatever is on my left and append it to the file on my right." Append means add to the end without touching what's already there.

# Commit the .gitignore change
git add .gitignore
git commit -m "Ignore filename.txt"

```

> Use this for personal notes, test files, or    anything that should 
> only live on your computer.

## Git â€” Before Starting Work (run every session)

```powershell
git fetch                               # download latest changes from GitHub (doesn't touch your files yet)
git switch dev                          # move to the dev branch
git pull                                # apply those downloaded changes to your local dev
git switch nick                         # move back to your working branch
git rebase dev                          # bring your changes up to date with dev
git push origin nick --force-with-lease # push your rebased nick to GitHub (--force-with-lease is safe here)
```
> Run this at the start of every session so nick is in sync with dev before you start working.

---

## Git â€” Committing and Pushing to Dev

```powershell
git status                              # It shows you every file that changed. You'll see something like: 
#modified:   gui.py or modified:   src/actions.py

git add -A     # stages ALL changed and NEW files (new folders like gui/ need this)
               # if you only want specific files: git add gui.py src/actions.py

git commit -m "describe what you changed" # save a snapshot with a message

git push origin nick --force-with-lease   # "send my local nick branch up to GitHub"
# origin â€” the name for your GitHub repo (it's just an alias git sets up automatically when you clone)

#nick â€” which branch to push
git switch dev                          # move to the dev branch

git merge nick --no-edit               # merge your changes into dev (--no-edit skips the vim prompt)
git push origin dev                     # upload the updated dev to GitHub
git switch nick                         # move back to your working branch
```
> The `--no-edit` flag stops vim from opening during the merge â€” always include it.

---

## Git â€” Promoting Dev to Main (release)

```powershell
git switch main                         # move to the main branch
git pull                                # refresh from GitHub before writing to it
git merge dev --no-edit                 # merge the latest dev into main
git push origin main                    # upload main to GitHub (safe â€” no force)

git switch dev                          # sync dev back up to main's merge commit
git merge main --no-edit               # (keeps dev and main at the same commit)
git push origin dev

git switch nick                         # move back to your working branch
```
> Run this when dev is stable and you want to publish a release. Always do the "Committing and Pushing to Dev" block first.
> The `git switch dev; git merge main` step prevents dev from showing "X commits behind main" in GitHub.

## Git â€” See Recent Commits

```powershell
git log --oneline -10
```

---

## Installing / Updating Dependencies

```powershell
# Install everything needed
py -m pip install playwright PyQt6 pdf2docx

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

