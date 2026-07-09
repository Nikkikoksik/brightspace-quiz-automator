# Gradebook Live Walkthrough — Recording (Task 10)

Recorded 2026-07-06/07 in course **BIOL-121-L01** (`ou=12978`) by driving the user's
real Chrome with a capture-phase click recorder + direct DOM inspection.
Raw material for building real `fetch_gradebook_items` / `apply_categories`.

**Status: full click-path CAPTURED** (create categories + assort items + verify total).
Open: syllabus source-doc download path (deferred).

---

## Product philosophy (user's words)
> Monotone/repetitive work done by computer; the most important steps are looked
> over by a human.

Every phase = **AI/automation proposes → interactive board preview → human confirms → apply.**

---

## Full flow

### Phase A — Create categories
1. **Content** → open **Course Syllabus** → read evaluation schema (category names + %).
   Section name varies per course ("Evaluation", "Assessment Scheme", "Grading", ...).
2. **Manage Grades** → **New** → **Category**.
3. Fill **Name**, set % in **Weight** box, click **Distribute weight evenly**,
   click **Save and New** (or **Save and Close** on last).

### Phase B — Assort (put grade items under categories)
1. Grades list → click **top select-all** checkbox → click **Bulk Edit**.
2. Bulk Edit page: each grade-item row has a **Category `<select>`**. Set each
   item's category, click **Save**.

### Phase C — Verify total = 100%
- Every course has a **Final Calculated Grade** row. After assorting, its total
  weight must be **100%**. If not, surface to user to verify.
- Why 170%→100%: category weights sum to 100; ungrouped items add their own weight
  at top level. Moving items INTO categories drops the extra → 100.
- Also capture any warning banner, e.g.
  `"'Final Calculated Grade' sums to 170%, not 100%. Verify the total weight..."`

### Phase D — Handoff
- Program does NOT rename the course. At the end, **remind the user to rename the
  course `_Staged` → `_Review`** (manual step). Course title example:
  `BIOL-121-L01-10054.202610_Staged`.

### Idempotency (future concern)
- User re-runs the same course repeatedly (continuous refinement). Re-running must
  NOT duplicate categories — check existing categories before creating. Handle later.

### Branch logic (in code)
- Outline present + categories extracted → one category per row w/ its weight.
- **No outline** → single `Term Work` @ 100%, all items under it, distribute evenly.
- Outline present but extraction fails / weights ≠ ~100 → fall back to `Term Work`, flag.
- Category-creation click-path identical for every branch.

### Category source (decided)
- Feed AI the **downloaded source doc** (reuse Course Outline `find_and_download_outline`
  → `extract_text_from_file`), NOT scraped page text (syllabus is in a lazy
  smart-curriculum iframe, unreliable).
- AI → strict JSON `[{category, weight}]`; validate sum ≈ 100.
- **Cache** downloaded outline in-memory keyed by `ou`.

### Item→category mapping (decided)
- AI maps each grade item to a category (item names + category names as input).
- Show in **interactive board** (`gui/gradebook_board.py`): categories = drop-zones,
  items = draggable cards, AI pre-places, user drags to fix, then **Apply**.

---

## Navigation (only `ou` varies — D2L software routes, same every course)
- Grades list: `/d2l/lms/grades/admin/manage/gradeslist.d2l?ou={ou}`
- New Category form: `/d2l/lms/grades/admin/manage/category_props_newedit.d2l?objectType=9&ou={ou}`
- Bulk Edit page: `/d2l/lms/grades/admin/manage/multiedit.d2l?ou={ou}`

**Reach the New Category form by clicking New → Category from the grades list, NOT
deep-link** (form carries per-session tokens `d2l_hitCode`/control map/referrer;
deep-GET fine for reading, unproven for saving). Deep-link used today only for read-only inspection.
- New menu: `d2l-menu[aria-label="New"]` → item `d2l-menu-item[aria-label="Category"]`

---

## Selectors

### New Category form (all STATIC ids)
| Field | Selector | Notes |
|---|---|---|
| Name | `input#z_g` (name=`Name0`) | plain text |
| ~~Short Name~~ | `input#z_l` | **SKIP** — not needed, D2L auto-fills |
| **Weight** | `d2l-input-number#z_u` (label "Weight", default 10) | real % weight; shadow-DOM wrapping native `input[aria-label="Weight"]`; fill via coordinate-click + select-all + type, NOT property set |
| Distribute weight evenly | `input#evenWeight` (name=`WeightDistributionType`, value=`1`) | |
| (by points) | `input#weightedByPoints` (value=`2`) | not used |
| (manual) | `input#z_be` (value=`0`) | not used |
| **Save and Close** | `button#z_a` (primary) | last category |
| **Save and New** | `button#z_b` | between categories |
| Save | `button#z_c` | |
| Cancel | `button#z_d` | |

**Name sanitization (REQUIRED before typing into `#z_g`):** D2L forbids
`/ " * < > + = | , %`. Deterministic strip (not AI):
`name.replace(/[\/"*<>+=|,%]/g,'').replace(/\s+/g,' ').trim()`  (`&`, `()` allowed).

### Grades list (assort entry)
| Element | Selector |
|---|---|
| Select-all checkbox | `input[name="z_c_cb_sa"]` (aria "Select all rows"), inside `table#z_c` |
| Per-item checkbox | `input[name="GradesList_cb"]` (aria "Select <item>") |
| Bulk Edit button | `d2l-button-subtle#z_d > button` (text "Bulk Edit"; inner id `d2l-uid-*` is DYNAMIC — select by text/`#z_d`) |

### Bulk Edit page (`multiedit.d2l`)
| Element | Selector | Notes |
|---|---|---|
| Category dropdown (per item) | plain `<select>` whose options contain `"of final grade"` | NO shadow DOM → use `select_option`. Options: `None`, `<Category> (NN% of final grade)`. |

**GOTCHA — dropdown option text ≠ category name.** D2L appends ` (NN% of final grade)`
to each category in the dropdown. Match by stripping that suffix, not exact:
`option.text.replace(/\s*\(\d+% of final grade\)\s*$/,'').trim() === categoryName`
Compare against the *sanitized* name (the one we typed into `#z_g`).
| (Grade Scheme dropdown) | `<select name="GradeSchemeId*">` (3 opts) | IGNORE — not the category |
| **Save** | `button#z_a` (primary) | |
| Cancel | `button#z_b` | |
- Only grade *items* have a category select; categories & Final Calculated/Adjusted
  Grade rows don't. (7 selects here = 7 items.)

### Verification (Phase C, on grades list)
- Warning banner detect: regex on page text, e.g. `/sums to \d+%, not 100%/i`.
- Final Calculated Grade total: find row containing "Final Calculated Grade",
  read trailing weight number; must equal 100.

---

## Recorder (persists to sessionStorage key `__gradebook_rec`, survives reloads)
Capture-phase click listener using `composedPath()[0]`, walks shadow DOM for a
selector path, stores `{n,tag,type,text,aria,name,id,x,y,path}`. Re-inject after
EVERY full page load. **Inject into the SAME tab the user clicks in** — watch the
MCP-tab vs user's-own-tab mismatch (bit us twice).

## Next build steps
1. (optional) record syllabus source-doc download path.
2. Build `apply_categories(page, categories)` — New→Category click-through, fill
   Name (sanitized) + Weight (coord-click), evenWeight radio, Save-and-New loop, Save-and-Close last.
3. Build assort: select-all → Bulk Edit → per-item `select_option` by category → Save.
4. Verify FCG == 100%, capture warnings, report to user.
5. Wire AI extraction + AI item→category mapping + interactive board preview.
