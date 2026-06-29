# Project Progress

## Quiz Automator

| Feature | Status |
|---|---|
| `run.bat` launches correctly (`py` instead of `python`) | âœ… |
| GUI with dark theme (PyQt6) | âœ… |
| Multiple course URLs in GUI | âœ… |
| Course URLs saved between runs | âœ… |
| "Add to Grade Book" setting | âœ… |
| "Auto-submit on timer expiry" setting | âœ… |
| Dry run mode (preview only) | âœ… |
| Brightspace session remembered between runs | âœ… |
| Login wait â€” polls until confirmed on home page | âœ… |

---

## Course Outline Automator

### Step 1 â€” Find & Download Course Outline

| Feature | Status |
|---|---|
| Scan course content via Brightspace API (149 topics) | âœ… |
| Accept CRN number (e.g. 80147) instead of full URL | âœ… |
| CRN lookup via shadow DOM JS traversal | âœ… |
| Show multiple candidates, ask confirmation before downloading | âœ… |
| Download file to `downloads/` folder (visible, not temp) | âœ… |
| Open downloaded file in Windows default app for review | âœ… |
| Auto-detect file type from magic bytes (PDF vs DOCX) | âœ… |
| Auto-download button for "Course Outline" topic type | âŒ Falls back to manual download every time |

### Step 2 â€” PDF Conversion

| Feature | Status |
|---|---|
| Detect if file is PDF and convert to DOCX via pdf2docx | âœ… |

### Step 3 â€” CourseBridge Conversion

| Feature | Status |
|---|---|
| Log into CourseBridge (lms.harshsaw.ca/content-converter) | âœ… |
| CourseBridge session remembered between runs | âœ… |
| Upload DOCX file | âœ… |
| Wait for "Copy HTML" button to appear (completion signal) | âœ… |
| Click "Copy HTML" and read from clipboard | âœ… |
| Save HTML preview to `coursebridge_preview.html` | âœ… |
| Open HTML preview in Notepad for review | âœ… |

### Step 4 â€” Paste into Brightspace

| Feature | Status |
|---|---|
| Look up Course Syllabus TopicId via API | âœ… |
| Navigate to correct D2L viewer page | âœ… |
| Find and click "Options" button (3-dots) | âŒ Button found at correct coords but untested after latest fix |
| Find and click "Edit" in dropdown menu | âŒ Not reached yet â€” blocked by above |
| Click "Source Code" button in editor | âŒ Not reached yet |
| Replace HTML in Source Code dialog | âŒ Not reached yet |
| Save topic | âŒ Not reached yet |

---

## GUI â€” Course Outline Tab

| Feature | Status |
|---|---|
| Two-tab layout (Quiz Automator + Course Outline) | âœ… |
| CRN / URL input field | âœ… |
| CourseBridge email + password fields | âœ… |
| Fields remembered between runs (outline_config.json) | âœ… |
| Dry run mode (download + convert only, no paste) | âœ… |
| Per-tab log output | âœ… |

---

## Login & Session

| Feature | Status |
|---|---|
| Brightspace session saved after login | âœ… |
| Clear login instructions printed while waiting | âœ… |
| Polls up to 9 minutes, confirms on `/d2l/home` before saving | âœ… |
| Session remembered on subsequent runs (own machine) | âœ… |
| Friend's session not being remembered | âŒ Still unreliable on other machines |

---

## Other

| Feature | Status |
|---|---|
| `.gitignore` for sessions, credentials, downloads | âœ… |
| `CLAUDE.md` with project documentation | âœ… |
| `downloads/` folder for downloaded outlines | âœ… |

