# Test Suite Design — Brightspace Quiz Automator
_2026-06-30_

## Goal

Catch import/wiring errors and logic bugs before pushing to main. No browser required.

## Scope

- `src/actions.py`, `src/browser.py`, `src/navigation.py`, `src/config.py`
- Excluded: `gui.py`, `gui_pyqt6.py` (need display + PyQt6, break headless CI)

## File Structure

```
tests/
  conftest.py          # injects src/ into sys.path
  test_smoke.py        # import all src modules, assert public functions exist
  test_summary.py      # _print_run_summary logic
  test_timing.py       # _save_timing file I/O
  test_settings.py     # config.py keys match browser.py settings.get() keys
pytest.ini             # testpaths = tests
.github/
  workflows/
    tests.yml          # Ubuntu, Python 3.11, runs on push + PRs to main
```

## Test Coverage

### Smoke (`test_smoke.py`)
- Imports: `actions`, `browser`, `navigation`, `config` all importable without error
- Function existence: assert each public function exists by name on its module
  - `navigation`: `harvest_quiz_edit_urls`, `get_quiz_names`, `open_quiz_edit`, `discover_course_urls`, `set_per_page_200`, `get_assignment_names`, `open_assignment_edit`
  - `actions`: `apply_gradebook`, `apply_auto_submit`, `save_quiz`, `apply_assignment_gradebook`, `save_assignment`, `verify_quiz_settings`, `apply_pdf_only_file_type`, `apply_rename_title`, `read_quiz_before_state`, `revert_gradebook`, `revert_auto_submit`
  - `browser`: `run`, `run_assignments`, `run_verify`, `run_timer_fix`, `run_undo`, `run_bs_login`
- Duplicate definition check: each function name appears exactly once per module

### Summary logic (`test_summary.py`)
- All passing: avg computed, "All OK ✓" line present
- Mixed results: error count correct, failed names listed
- `wall_time=None`: no "Total" line, no crash
- Empty results list: no crash

### Timing file (`test_timing.py`)
- First write: creates file, valid JSON array with one entry
- Second write: appends (two entries), keys present (`date`, `time`, `course`, `quiz`, `seconds`)
- Corrupt existing file: overwrites cleanly, no crash

### Settings keys (`test_settings.py`)
- `config.SETTINGS` contains exactly: `set_in_gradebook`, `set_auto_submit`, `rename_moodle_titles`
- All keys used in `browser.py` `settings.get(...)` calls exist in `config.SETTINGS`

## CI Workflow

- Trigger: push to any branch + PRs targeting `main`
- Runner: `ubuntu-latest`, Python 3.11
- Install: `pip install pytest playwright` (no PyQt6, no browser download)
- Command: `pytest tests/ -v`
- Fail behavior: blocks merge if any test fails
