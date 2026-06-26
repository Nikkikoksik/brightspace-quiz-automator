# Staging Tab — Browser Unification Design
**Date:** 2026-06-26  
**Status:** Approved by user

---

## Problem

The staging tab currently opens multiple Chromium processes:
- Headless browser for CRN extraction (from URL)
- Visible browser for Steps 1+2
- New visible browser for Quiz automator
- New visible browser for Assignment automator
- New visible browser for Course Outline automator (Brightspace)
- Separate Chromium process for CourseBridge

Additionally: 5 sequential dialogs appear after Step 2, and the course outline confirmation triggers a download that opens in the user's system browser (Edge).

## Goal

One Chromium process, one browser context, from start to finish. Browser stays open at the end for user review. User closes it manually.

---

## Architecture

### Single browser, single context, multiple pages (tabs)

```
Browser (one process)
  context (one, loaded with Brightspace session)
    page_bs  — Brightspace (open from start)
    page_cb  — CourseBridge (new_page() when outline step begins)
```

Cookies are domain-scoped inside a context, so `learn.okanagancollege.ca` and `coursebridge.okanagancollege.app` auth do not interfere. No separate context needed for CourseBridge.

### `course_outline_automator.run()` signature change

Add optional `context` parameter:
```python
async def run(dry_run=False, course_url=None, prompt_fn=None, context=None, page=None):
```
- If `context` is passed (called from staging): use it, open `page_cb` as new tab inside it
- If `context` is None (standalone run): create own browser + context as before

Backwards compatible — standalone invocation still works.

---

## Full Flow (staging tab, full run)

```
Browser opens once
  page_bs → _wait_for_login (auto-login or session)
  page_bs → Step 1: navigate to content page, toggle blueprint switch off
  page_bs → Step 2: navigate to Import/Export/Copy Components
            GUI: "Continue →" button (replaces wait_for_event("close"))
            User selects source course, copies components, clicks Continue in GUI

  page_bs → Course outline: search content tab for syllabus/outline/guideline
            GUI dialog: "Found: <filename> — is this the right file?" Yes / No
            If No: stop, log "User declined — check content tab manually"
            If Yes: Playwright download intercept → save to temp path (no Edge)

  page_cb = context.new_page()  → CourseBridge tab opens
            Login, upload file, set template, click Convert
            Poll status log for "Done!"
            GUI: "Conversion complete — review the CourseBridge tab, then click Continue"
            User reviews at own pace, clicks Continue in GUI

  page_bs.bring_to_front()
            Grab HTML from pre.font-mono
            Navigate to Course Syllabus topic
            Open TinyMCE → replace HTML → save

Both tabs remain open. Browser stays open.
User reviews, closes manually when satisfied.
```

---

## GUI Changes

### Step 2 "Continue" button
- After Step 2 instructions appear in the staging log, GUI shows a **"Continue →"** button
- Worker thread waits on a `threading.Event`
- Button click sets the event, worker proceeds
- Button disappears after clicked

### Outline filename confirmation
- GUI dialog: `"Found: <filename> — download this?"` with Yes / No
- Replaces the Edge-opens-download pattern entirely
- If No: automation stops gracefully

### CourseBridge review pause
- GUI shows: `"CourseBridge conversion complete. Review the tab, then click Continue."`
- Same `threading.Event` pattern as Step 2
- After Continue: page switches back to Brightspace tab

---

## Deletions

| What | Where | Why |
|---|---|---|
| `coursebridge_preview.html` write + `os.startfile()` | `course_outline_automator.py` | Replaced by in-browser tab review |
| Log messages referencing preview file | `course_outline_automator.py` | No longer relevant |
| "Was course outline found?" dialog | `staging_automator.py` | Remove post-outline dialogs |
| "Were there grade categories?" dialog | `staging_automator.py` | Remove post-outline dialogs |
| Separate CourseBridge browser/context creation | `course_outline_automator.py` | Replaced by `context.new_page()` |

---

## Files Changed

| File | Change |
|---|---|
| `src/course_outline_automator.py` | Accept `context`/`page` params; open CB as tab; remove preview.html; add review pause; intercept download |
| `src/staging_automator.py` | Pass `context` + `page_bs` to `run_outline`; remove post-outline dialogs; replace `wait_for_event("close")` with threading.Event |
| `gui_pyqt6.py` | Add "Continue →" button for Step 2; filename confirmation dialog; CB review pause dialog |

---

## Out of Scope

- Quiz automator and Assignment automator browser unification (separate effort)
- Collapsible sidebar
- Speed optimizations (slow_mo, fixed timeouts)