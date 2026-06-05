# Commands & How To Use The App

---

## Running the App
Double-click `run.bat` — done.

---

## Get Into the Right Folder First
Always run this before any Git commands:
```powershell
cd "c:\Users\300353682\OneDrive - Okanagan College\Desktop\Quiz automator\brightspace-quiz-automator"
```

---

## Check You're on the Right Branch
```powershell
git branch
```
You should see `* nick`. If not, run:
```powershell
git checkout nick
```

---

## Start of Every Work Session
Run this before doing anything — catches you up with what everyone else did:
```powershell
git fetch
git checkout dev
git pull
git checkout nick
git rebase dev
git push origin nick --force-with-lease
```

---

## After Making a Change — Save and Upload It
```powershell
git add filename.py
git commit -m "describe what you changed"
git push origin nick --force-with-lease
```

---

## When a Change is Confirmed Working — Share With the Team
Only do this when it actually works:
```powershell
git checkout dev
git merge nick
git push origin dev
git checkout nick
```

---

## Fix Login Problems
Deletes saved login, forces a fresh login next run:
```powershell
del session.json
```
For CourseBridge login:
```powershell
del cb_session.json
```

---

## Install Everything From Scratch
```powershell
py -m pip install playwright customtkinter pdf2docx
py -m playwright install chromium
```

---

## GitHub Repo
https://github.com/Nikkikoksik/brightspace-quiz-automator
