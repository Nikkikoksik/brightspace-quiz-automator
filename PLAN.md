# Plan

Check off each goal as it's confirmed working.

---

## In Progress

- [ ] **Step 4 — Paste HTML into Brightspace**
  - Found the `Options` button at (1104, 195)
  - Fixed Edit detection to check `text`/`aria-label` on `d2l-menu-item`
  - **Next action:** Run without dry-run and confirm it gets past the Edit click

---

## Up Next

- [ ] **Per-step test buttons in the GUI**
  - Add 4 buttons to the Course Outline tab: Test Step 1 / 2 / 3 / 4
  - Each runs just that step so you don't have to sit through the whole pipeline

- [ ] **Auto-download for "Course Outline" topic**
  - Currently falls back to manual download every time
  - Need to identify what the download button looks like on that topic type

---

## Done

- [x] run.bat fixed
- [x] GUI with two tabs (Quiz + Course Outline)
- [x] Quiz automator — gradebook + auto-submit settings
- [x] Course URLs saved between runs
- [x] CourseBridge credentials saved between runs
- [x] Step 1 — Find course outline via Brightspace API
- [x] Step 1 — CRN lookup working (shadow DOM fix)
- [x] Step 1 — Confirm before downloading, open file in Windows for review
- [x] Step 1 — Downloads saved to `downloads/` folder
- [x] Step 2 — PDF → DOCX conversion
- [x] Step 3 — CourseBridge upload + conversion
- [x] Step 3 — HTML preview opens in Notepad
- [x] Login wait — confirms on /d2l/home before saving session
- [x] Friend's session persistence fixed
- [x] .gitignore covers all sensitive files and generated folders
