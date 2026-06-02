# Issues & Improvements

---

## Bugs

### `expect_page()` race condition in `paste_html_to_syllabus`
**File:** `course_outline_automator.py:288-290`
The Edit click fires *before* entering `expect_page()`. If Brightspace opens the edit tab before the listener is registered the await times out. The click must move inside the `async with` block.

---

### `expect_download()` dead wait in manual fallback
**File:** `course_outline_automator.py:132-135`
`expect_download()` is entered after `prompt_fn()` returns, with no action inside the block to trigger a download. Nothing is ever captured.

---

### Per-quiz crash — no error recovery
**File:** `browser.py:46`
If `open_quiz_edit` throws on any quiz (timeout, renamed quiz, DOM change) the entire course loop aborts. Each quiz iteration needs a try/except that logs the failure and continues to the next quiz.

---

## Reliability

### `apply_gradebook` skips shadow DOM walk
**File:** `actions.py:4-34`
Uses standard `page.locator()` instead of the recursive shadow DOM walk used everywhere else. Will silently report "not found" if D2L moves that button into a shadow root.

---

## UX

### Notepad preview fires prompt immediately
**File:** `course_outline_automator.py:415-419`
`subprocess.Popen(notepad)` is non-blocking — the "click OK to continue" prompt appears before the user has had time to read the HTML. Should either block on Notepad closing or give a longer heads-up message.

---

### No Stop / Cancel button
**Files:** `gui.py` (both tabs)
Once a run starts there is no way to abort it short of closing the window. A Stop button should set a cancellation flag and terminate the worker thread cleanly.

---

### CourseBridge password stored plaintext
**File:** `gui.py` → saved to `outline_config.json`
Credentials are written unencrypted to disk. At minimum add a warning in the UI; ideally store via `keyring`.

---

### Fixed window size
**File:** `gui.py:49`
`resizable(False, False)` at 700×800 is cramped on smaller laptop screens. Should allow vertical resizing at minimum.

---

## Features

### Outline automator: multi-course support
The quiz tab accepts multiple URLs; the outline tab only handles one course at a time. Should support a list of CRNs / URLs the same way.

---

### Stop after N quizzes (debug / test mode)
**File:** `browser.py`
A `--limit N` CLI flag exists but there is no GUI control for it. Useful for testing without processing an entire course.

---
