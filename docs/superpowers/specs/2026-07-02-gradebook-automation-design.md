# Gradebook Automation — Design Spec

Date: 2026-07-02

## Problem

Setting up a Brightspace gradebook so its categories/weights match the course
outline is one of the most tedious, judgment-heavy parts of course setup.
Today it's entirely manual: read the outline, figure out categories and
weights, create each category in Brightspace, then move every existing
gradebook item into the right category by hand.

## Goal

A new "Gradebook" tab that:
1. Reads a course's outline (already converted to HTML by the existing
   Course Outline tool, or a local file as fallback)
2. Uses an AI to propose categories, weights, and item→category assignments
3. Lets the user review and freely correct that proposal on a drag-and-drop
   board before anything touches Brightspace
4. Applies the confirmed structure to Brightspace's gradebook, one category
   at a time, pausing between each

This spec does not require the AI (or the tool) to get everything right —
it requires the user to always be able to see and fix what's proposed before
anything is applied.

## Entry point

Standalone **"Gradebook"** tab (not chained off Course Outline). Same
course-input pattern as other tabs (CRN or Brightspace URL).

## Data source for the outline

Primary: scrape the live **Course Syllabus** topic HTML in Brightspace
(reuses the topic-lookup approach already in `course_outline_automator.py`).
This works even if Course Outline was run days/weeks earlier by someone else,
or was never run by this tool at all.

Fallback: a file picker in the Gradebook tab to point directly at a local
`.pdf`/`.docx`, reusing the existing `pdf2docx`/`mammoth` text extraction
already in the codebase.

## Scenario handling

After fetching the outline text, three paths:

1. **No syllabus content found** (empty/placeholder topic) — show a banner
   and a one-click button: *"Create Term Work category (100%)"*. This
   creates a single category worth 100%, puts every existing gradebook item
   in it, and adds the comment: *"Grade items present in gradebook so made
   one category weighted 100% and all items have been placed in this
   category."*

2. **Outline found, looks standard** — run AI extraction (see below), show
   the result on the review board.

3. **"Not a standard outline" (manual override, always available)** — no
   automatic length/page detection. The user decides, any time, that an
   outline is non-standard (e.g. the 20+ page PNSG-style ones) and clicks a
   button that skips gradebook setup and adds the comment: *"Material and
   resources have been successfully migrated. The course syllabus included
   supplementary materials so we did not apply this to the course syllabus
   template. Grade Book also not configured, please reach out for support,
   if desired."*

### AI extraction failure fallback

If AI extraction runs but finds no categories/weights in an outline that
does have content, show a fallback screen: the full outline text in a
selectable, scrollable box with the prompt "AI couldn't find the weighting
table — highlight it below." The user selects the relevant text with the
mouse and clicks **"Extract from Selection"**, which re-sends just that
highlighted chunk to the AI. The "not a standard outline" skip button
remains available here as the final out.

## AI extraction

- `extract_categories(outline_text, gradebook_items, provider) -> structure`
  — one function, provider-agnostic.
- **Typical weighting format** (guidance for the extraction prompt): most
  outlines present a two-column table — "Course Component" / "Percentage of
  Final Grade" — with one row per component (e.g. "File Types / Directory
  Quiz — 10%", "Final Exam (Bootstrap) — 25%", "Project — 30%") and a
  "Total 100%" row at the bottom. The prompt should look for
  percentage-per-component structures summing to ~100%. This is the common
  case, not a guarantee — some professors embed the table as a screenshot
  image or use free-form text, which is what the manual-selection fallback
  and the skip button are for.
- Three supported providers, selected via a new dropdown in **Settings**:
  Claude, GPT, Gemini. Each needs its own API key field (same visual pattern
  as the existing CourseBridge/Sentry credential fields).
- Provider-specific calls (`_call_claude`, `_call_gpt`, `_call_gemini`) sit
  behind `extract_categories()` — nothing else in the codebase touches a
  specific SDK.

## Review board (drag-and-drop)

- Columns = categories, each with an editable weight % field.
- Cards = gradebook items; drag between columns to reassign.
- **"+ Add Category"** button lets the user create a category by hand.
  Items dragged into it just sit there with whatever weight the user types.
- **No auto-rebalancing.** Adding/moving/editing anything never
  auto-recalculates other categories' weights — the user sets weights
  manually. The AI's first pass is a starting suggestion only.

## Apply step

Step-by-step: one category confirmed/created in Brightspace at a time,
pausing between each (mirrors the Staging tab's `prompt_fn` pattern), so
the user can watch and stop partway if something looks wrong.

## Known technical risks (deferred, not solved by this spec)

Two pieces require live Brightspace DOM exploration that hasn't happened
yet — both are new territory, unlike the shadow-DOM patterns already solved
elsewhere in this app:

1. **Reading current gradebook items** from the Brightspace Grades page —
   `fetch_gradebook_items(page, course_id)`
2. **Creating categories and moving items** via the Grades UI —
   `apply_categories(page, structure, step_fn)`

**Resolution method:** rather than guess selectors now, these will be built
from a live walkthrough — the user demonstrates the actual click-path in a
real course, and that gets captured as the real implementation. This
mirrors how `course_outline_automator.py`'s CourseBridge integration was
isolated behind one function (`convert_with_coursebridge`) until the real
API/selectors were confirmed.

Until that walkthrough happens, both functions are stubbed with the
signatures above so the rest of the pipeline (fetch → AI → review board →
Settings) can be built and tested independently.

## Out of scope for this spec

Explicitly deferred, not solved here:

- Merging with pre-existing gradebook categories (design assumes empty
  gradebook categories; if a course already has some, behavior is
  undefined for now)
- Automatic length/page-based non-standard-outline detection (the user
  always decides manually via the skip button)
- Automatic weight rebalancing when categories/items change

## Architecture summary

New files, following existing conventions:

- `gui/panels/gradebook.py` — new tab: course input, fetch button, review
  board, step-by-step Apply button, log panel
- `src/gradebook_automator.py` — `fetch_outline_text`,
  `fetch_gradebook_items` *(stub)*, `extract_categories`,
  `apply_categories` *(stub)*
- Settings tab: + AI provider dropdown, + one API key field per provider
