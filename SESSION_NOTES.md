# Session Notes

**Branch:** `nick` | **Last updated:** 2026-06-04

---

## Staging Automator — Current State

| Step | Command | Status |
|---|---|---|
| Step 1 — Hide blueprint, find shell | `py staging_automator.py 1 <CRN>` | Done |
| Step 2 — Copy components from source | `py staging_automator.py 2 <CRN>` | Done |
| Step 2g — Link quizzes/assignments to gradebook | `py staging_automator.py 2g <CRN>` | Written, **not tested** |
| Step 3 — Course outline | `py staging_automator.py 3 <CRN>` | Not started |

---

## Immediate Next Step

Test Step 2g:
```
py staging_automator.py 2g 31899
```
Should find the staged shell for CRN 31899, run quiz automator (gradebook + auto-submit), then run assignment automator (gradebook) on it.

---

## After That

1. **Step 3** — Add `run_step3` to `staging_automator.py`, call `course_outline_automator.run()` with the staged course OU
2. **GUI** — Add Step 2g and Step 3 buttons to the Staging tab; add a "Run All" button that chains all steps

---

## Git Workflow
```
git fetch
git checkout dev
git pull
git checkout nick
git pull origin nick --rebase
git rebase dev
git push origin nick --force-with-lease
```

**Repo:** https://github.com/Nikkikoksik/brightspace-quiz-automator
