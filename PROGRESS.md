# Project Progress

## Quiz Automator

| Feature | Status |
|---|---|
| `run.bat` launches correctly (`py` instead of `python`) | ✅ |
| GUI with dark theme (CustomTkinter) | ✅ |
| Multiple course URLs in GUI | ✅ |
| Course URLs saved between runs | ✅ |
| "Add to Grade Book" setting | ✅ |
| "Auto-submit on timer expiry" setting | ✅ |
| Dry run mode (preview only) | ✅ |
| Brightspace session remembered between runs | ✅ |
| Login wait — polls until confirmed on home page | ✅ |

---

## Course Outline Automator

### Step 1 — Find & Download Course Outline

| Feature | Status |
|---|---|
| Scan course content via Brightspace API (149 topics) | ✅ |
| Accept CRN number (e.g. 80147) instead of full URL | ✅ |
| CRN lookup via shadow DOM JS traversal | ✅ |
| Show multiple candidates, ask confirmation before downloading | ✅ |
| Download file to `downloads/` folder (visible, not temp) | ✅ |
| Open downloaded file in Windows default app for review | ✅ |
| Auto-detect file type from magic bytes (PDF vs DOCX) | ✅ |
| Auto-download button for "Course Outline" topic type | ❌ Falls back to manual download every time |

### Step 2 — PDF Conversion

| Feature | Status |
|---|---|
| Detect if file is PDF and convert to DOCX via pdf2docx | ✅ |

### Step 3 — CourseBridge Conversion

| Feature | Status |
|---|---|
| Log into CourseBridge (lms.harshsaw.ca/content-converter) | ✅ |
| CourseBridge session remembered between runs | ✅ |
| Upload DOCX file | ✅ |
| Wait for "Copy HTML" button to appear (completion signal) | ✅ |
| Click "Copy HTML" and read from clipboard | ✅ |
| Save HTML preview to `coursebridge_preview.html` | ✅ |
| Open HTML preview in Notepad for review | ✅ |

### Step 4 — Paste into Brightspace

| Feature | Status |
|---|---|
| Look up Course Syllabus TopicId via API | ✅ |
| Navigate to correct D2L viewer page | ✅ |
| Find and click "Options" button (3-dots) | ❌ Button found at correct coords but untested after latest fix |
| Find and click "Edit" in dropdown menu | ❌ Not reached yet — blocked by above |
| Click "Source Code" button in editor | ❌ Not reached yet |
| Replace HTML in Source Code dialog | ❌ Not reached yet |
| Save topic | ❌ Not reached yet |

---

## GUI — Course Outline Tab

| Feature | Status |
|---|---|
| Two-tab layout (Quiz Automator + Course Outline) | ✅ |
| CRN / URL input field | ✅ |
| CourseBridge email + password fields | ✅ |
| Fields remembered between runs (outline_config.json) | ✅ |
| Dry run mode (download + convert only, no paste) | ✅ |
| Per-tab log output | ✅ |

---

## Login & Session

| Feature | Status |
|---|---|
| Brightspace session saved after login | ✅ |
| Clear login instructions printed while waiting | ✅ |
| Polls up to 9 minutes, confirms on `/d2l/home` before saving | ✅ |
| Session remembered on subsequent runs (own machine) | ✅ |
| Friend's session not being remembered | ❌ Still unreliable on other machines |

---

## Other

| Feature | Status |
|---|---|
| `.gitignore` for sessions, credentials, downloads | ✅ |
| `CLAUDE.md` with project documentation | ✅ |
| `downloads/` folder for downloaded outlines | ✅ |
