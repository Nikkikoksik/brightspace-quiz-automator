# Plan

---

## Current Focus — Staging Automator

Building a pipeline that fully stages a course from scratch using a CRN.

| Step | What it does | Status |
|---|---|---|
| Step 1 | Find `_Staged` shell by CRN, hide blueprint module | Done ✅ |
| Step 2 | Copy all components from source course | Done ✅ |
| Step 3 | Run quiz + assignment automator to link gradebook | Done ✅ |
| Step 4 | Course outline — download, convert, paste into Brightspace | Not started ❌ |
| Step 5 | Set Up Gradebook - Has to be done manually for now | Not started ❌ |
| Step 6 | Re-label shell from `_Staged` → `_Ready` | Not started ❌ |

**Test Step 2g first:**
```
py staging_automator.py 2g 31899
```

**After that:**
- Add `run_step3` to `staging_automator.py` (calls `course_outline_automator.run()`)
- Add Step 2g + Step 3 buttons to GUI Staging tab
- Add "Run All" button that chains all steps

---

## Other Outstanding Items

- [ ] **Quiz automator** — no skip check for timer if it's already set (gradebook already skips)
- [ ] **Course Outline** — confirm the two-save flow actually saves to Brightspace (TinyMCE `setContent()` works but full save untested)

---

## Done

- [x] GUI — Quiz, Assignment, Course Outline tabs
- [x] Quiz automator — gradebook + auto-submit, skips if already set
- [x] Assignment automator — gradebook linking
- [x] Course Outline — find + download outline from Brightspace
- [x] Course Outline — PDF → DOCX conversion
- [x] Course Outline — CourseBridge upload + HTML output
- [x] Course Outline — paste HTML into TinyMCE in Brightspace
- [x] Staging scraper — scrape + filter course list from lms.harshsaw.ca
- [x] Staging Step 1 — hide blueprint module
- [x] Staging Step 2 — copy all components from source course
- [x] Auto-update on launch, session persistence, Pause/Resume buttons
