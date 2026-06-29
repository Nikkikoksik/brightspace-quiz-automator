# Quiz & Assignment Automation Speed Design

**Date:** 2026-06-29  
**Branch:** nick  
**Goal:** Reduce per-quiz time from ~10s to ~1.2s wall-clock throughput via parallel workers + smart waits

---

## Problem

Current flow processes quizzes sequentially (~10s each). Time breakdown:
- ~6-7s from fixed `wait_for_timeout()` calls (artificial delay)
- ~1-2s from `slow_mo=80` on every Playwright action
- ~1-2s from action menu dance (goto list → click Actions → click Edit) per quiz
- REST API blocked (requires admin access) — UI automation only

---

## Approach: Parallel Worker Pool + Smart Waits

Three phases per run:

### Phase 1 — Harvest (1 tab)

Navigate to quiz list once. Walk shadow DOM to read `href` attributes from `d2l-menu-item[text="Edit"]` elements — zero clicks, zero action menus. Build ordered list of `(name, edit_url)` pairs for all quizzes.

**Fallback:** If hrefs are null (lazy-rendered), fall back to intercepting navigation via `page.route()` during a fast click-through harvest pass.

### Phase 2 — Worker Pool (N=3 tabs)

```
asyncio.Queue  ←  [(idx, name, edit_url), ...]
     │
┌────┴────┐
W1       W2       W3     ← each: own Page, same browser context
page.goto(edit_url)      ← direct navigation, no menu interaction
apply_gradebook(page)
apply_auto_submit(page)
save_quiz(page)
→ pull next from queue
```

- Workers share same `context` (cookies/session), each has own `page` — no state collision
- `queue.get_nowait()` + `asyncio.QueueEmpty` — workers self-terminate when queue drains
- `asyncio.Lock` guards shared `results` list
- Per-worker error isolation — one failed quiz doesn't kill other workers
- Default `WORKER_COUNT = 3` (wire to Settings panel in future)

### Phase 3 — Results

Collect into `results` list → `_print_run_summary()` + timing stats write.

---

## Smart Waits

Remove `slow_mo=80`. Replace every fixed sleep with an actual condition:

| Location | Current | Replacement |
|---|---|---|
| `browser.py` launch | `slow_mo=80` | Remove |
| `open_quiz_edit` after click | `wait_for_timeout(800)` | `wait_for_selector("button.d2l-grade-info")` |
| action menu click | `wait_for_timeout(400)` | `wait_for_selector("d2l-menu-item[text='Edit']")` |
| timing expand | `wait_for_timeout(600)` | `wait_for_selector("text=Timer Settings")` |
| radio click | `wait_for_timeout(600)` | `wait_for_function(() => radio.checked)` |
| after OK click | `wait_for_timeout(1000)` + `wait_for_timeout(800)` | existing `wait_for_function` dialog-closed check only |
| after Save | `wait_for_timeout(1500)` + `wait_for_timeout(800)` | `wait_for_load_state("domcontentloaded")` only |
| `discover_course_urls` | `wait_for_timeout(2000)` | Replaced by `resolve_quiz_url()` direct construction |

Estimated savings from waits alone: **4-5s per quiz**.

---

## Timing Stats Schema

New per-entry structure in `timing_stats.json`:

```json
{
  "date": "2026-06-29",
  "time": "14:32",
  "course": "https://...",
  "quiz": "Quiz 1",
  "phases": {
    "navigate": 1.1,
    "gradebook": 0.4,
    "timer": 1.2,
    "save": 0.9
  },
  "total": 3.6,
  "changed": { "gradebook": true, "timer": false },
  "worker": 2
}
```

`changed` booleans distinguish "slow because D2L had real work to do" from "slow for no reason."

Run summary log gains:
```
  Phase breakdown (avg):  navigate 1.1s  |  gradebook 0.4s  |  timer 1.2s  |  save 0.9s
```

---

## Files Changed

| File | Change |
|---|---|
| `src/browser.py` | Replace `run()` loop with `_quiz_worker()` + `asyncio.gather()`; add `harvest_quiz_edit_urls()`; remove `slow_mo`; update `_save_timing()` for new schema |
| `src/navigation.py` | Add `harvest_quiz_edit_urls()`; remove `discover_course_urls` wait; fix action menu waits |
| `src/actions.py` | Replace all fixed `wait_for_timeout` with condition-based waits |
| `src/browser.py` (assignments) | Apply same worker pool pattern to `run_assignments()` |

---

## Expected Performance

| Stage | Per-quiz time |
|---|---|
| Baseline | ~10s |
| After smart waits | ~5s |
| After direct URL (no menu dance) | ~3.5s |
| With 3 parallel workers | ~1.2s wall-clock throughput |

---

## Risk & Mitigation

| Risk | Mitigation |
|---|---|
| D2L lazy-renders edit hrefs (harvest 2a fails) | Fall back to route-intercept harvest (2b) |
| D2L throttles 3 concurrent saves | Reduce `WORKER_COUNT` to 2; add configurable setting |
| Worker crashes mid-queue | Per-worker try/except; failed quiz logged, other workers continue |
| `networkidle` waits removed too aggressively | Keep `domcontentloaded` as floor; add specific element waits as safety |