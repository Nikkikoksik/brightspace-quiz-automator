# Plan

Check off each goal as it's confirmed working.

---

## In Progress

- [ ] **Full Staging Automation — building step by step**
  - [x] Scrape Ready to Send list from lms.harshsaw.ca → staging_queue.txt
  - [x] Filter for semester codes ending in 10/20/30
  - [x] `find_staging_shell(page, crn)` — searches Brightspace, returns _Staged URL
  - [ ] Test `find_staging_shell` against a real CRN
  - [ ] Step 1: Hide "How to Use This Blueprint" module
  - [ ] Step 2: Copy Components (leave for later)
  - [ ] Step 3: Course Outline (already built)
  - [ ] Step 4: Gradebook (leave for later)
  - [ ] Step 5: Re-label to "Ready"

- [ ] **Assignment Automator — Gradebook not saving**
  - Popup dialog appears after "Add to Grade Book" is clicked
  - Need to confirm what button the dialog shows (OK / Add / Create?)
  - Pause button added to help debug

---

## Up Next

- [ ] **Course Outline — Step 4 full test with real HTML**
  - TinyMCE `setContent()` works ✅
  - Need to confirm the two-save flow actually saves to Brightspace

- [ ] **Quiz Automator — Skip timer if already set**
  - Gradebook: already skips ✅
  - Timer auto-submit: no skip check yet

- [ ] **Per-step test buttons (Steps 1–3)**
  - Step 4 test button done ✅
  - Steps 1, 2, 3 test buttons not built yet

---

## Done

- [x] run.bat — auto-installs dependencies on first run
- [x] run.bat — checks for updates from GitHub on every launch
- [x] Playwright browser installed once, not every launch
- [x] GUI with three tabs (Quiz / Assignment / Course Outline)
- [x] Quiz automator — gradebook + auto-submit settings
- [x] Quiz automator — skip if already in gradebook
- [x] Quiz automator — timer wait increased to 30s (was 6s)
- [x] Assignment automator — tab + run button wired up
- [x] Pause / Resume button — Quiz tab
- [x] Pause / Resume button — Assignment tab
- [x] Course URLs saved between runs
- [x] CourseBridge credentials saved between runs
- [x] Step 1 — Find course outline via Brightspace API
- [x] Step 1 — CRN lookup (shadow DOM fix)
- [x] Step 1 — Confirm before downloading, open file in Windows for review
- [x] Step 1 — Downloads saved to `downloads/` folder
- [x] Step 1 — Search only for "outline"
- [x] Step 2 — PDF → DOCX conversion
- [x] Step 3 — CourseBridge upload + conversion
- [x] Step 3 — HTML preview opens in Notepad
- [x] Step 4 — Navigate to Course Syllabus topic via API
- [x] Step 4 — Click Options → Edit via shadow DOM
- [x] Step 4 — Set content via TinyMCE API
- [x] Step 4 — Test Step 4 button in GUI
- [x] Login wait — confirms on /d2l/home before saving session
- [x] Friend's session persistence fixed
- [x] staging_scraper.py — scrape + filter course list
- [x] STAGING_PROCESS.md documented
