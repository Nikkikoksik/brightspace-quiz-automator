#!/usr/bin/env python3
"""
Gradebook Automator — outline → AI-proposed categories → review → apply.
fetch_gradebook_items / apply_categories are STUBS until the live
Brightspace walkthrough (see design spec 2026-07-02).
"""
import html as _htmllib
from html.parser import HTMLParser
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

_HERE   = Path(__file__).parent.parent
BS_BASE = "https://learn.okanagancollege.ca"


class AIRateLimitError(RuntimeError):
    """Raised when the selected AI provider rejects a request for rate/quota."""


class _EvaluationTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(_clean_space("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(c.strip() for c in self._row):
                self.rows.append(self._row)
            self._row = None


def _clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", _htmllib.unescape(str(text))).strip()


def _weight_number(text: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?", str(text))
    return float(m.group(1)) if m else 0.0


def parse_evaluation_html(html: str) -> list[dict]:
    """Parse CourseBridge's evaluation-only HTML/table output."""
    if "NO EVALUATION SCHEMA FOUND" in html.upper():
        return []

    parser = _EvaluationTableParser()
    parser.feed(html)
    rows = parser.rows
    if not rows and "|" in html:
        rows = [line.split("|") for line in html.splitlines() if "|" in line]

    evaluations = []
    for row in rows:
        if len(row) < 2:
            continue
        component, weight = _clean_space(row[0]), _clean_space(row[1])
        notes = _clean_space(row[2]) if len(row) > 2 else ""
        if not component or component.lower() in ("component", "component name"):
            continue
        if "weight" in weight.lower() and "percent" in weight.lower():
            continue
        weight_num = _weight_number(weight)
        if weight_num <= 0:
            continue
        evaluations.append({"name": component, "weight": weight_num, "notes": notes})
    return evaluations


_STOPWORDS = {
    "a", "an", "and", "as", "based", "before", "course", "final", "for", "grade",
    "in", "of", "on", "or", "percent", "percentage", "the", "to", "with",
}
_IMPORTANT = {
    "activity", "activities", "assignment", "assignments", "exam", "exams",
    "final", "formal", "lab", "labs", "midterm", "participation", "pre",
    "prelab", "project", "quiz", "quizzes", "report", "test", "tests",
}


def _tokenize(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9]+", text.lower().replace("-", " "))
    tokens = []
    for token in raw:
        if token in _STOPWORDS:
            continue
        if token == "quizzes":
            token = "quiz"
        elif token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 3:
            token = token[:-1]
        tokens.append(token)
    return tokens


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:]))


def _match_score(item: str, evaluation: dict) -> int:
    item_tokens = _tokenize(item)
    cat_tokens = _tokenize(evaluation["name"])
    note_tokens = _tokenize(evaluation.get("notes", ""))
    if not item_tokens or not cat_tokens:
        return 0

    item_text = " ".join(item_tokens)
    cat_text = " ".join(cat_tokens)
    score = 0
    if cat_text and (cat_text in item_text or item_text in cat_text):
        score += 8
    for token in set(item_tokens) & set(cat_tokens):
        score += 3 if token in _IMPORTANT else 1
    score += 4 * len(_bigrams(item_tokens) & _bigrams(cat_tokens))
    for token in set(item_tokens) & set(note_tokens):
        score += 1
    return score


def structure_from_evaluation_html(html: str, gradebook_items: list[str]) -> dict:
    """Build a gradebook structure from CourseBridge evaluation output.

    This avoids provider API calls. Ambiguous or low-confidence item matches
    stay uncategorized for review.
    """
    evaluations = parse_evaluation_html(html)
    categories = [
        {"name": e["name"], "weight": e["weight"], "items": []}
        for e in evaluations
    ]
    uncategorized = []
    for item in gradebook_items:
        scored = sorted(
            ((idx, _match_score(item, e)) for idx, e in enumerate(evaluations)),
            key=lambda x: x[1],
            reverse=True,
        )
        if not scored or scored[0][1] < 4:
            uncategorized.append(item)
            continue
        if len(scored) > 1 and scored[0][1] == scored[1][1]:
            uncategorized.append(item)
            continue
        categories[scored[0][0]]["items"].append(item)
    return {"categories": categories, "uncategorized": uncategorized}


def _parse_ai_response(text: str, gradebook_items: list[str]) -> dict:
    """
    Parse the AI's JSON reply into a structure dict.
    Drops items the AI invented; real items the AI missed go to "uncategorized".
    Raises ValueError if no usable JSON or no categories found.
    """
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in AI response")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"AI response is not valid JSON: {e}")

    raw_cats = data.get("categories") or []
    if not raw_cats:
        raise ValueError("AI response contained no categories")

    known = set(gradebook_items)
    seen: set[str] = set()
    categories = []
    for c in raw_cats:
        items = [i for i in c.get("items", []) if i in known]
        seen.update(items)
        categories.append({
            "name":   str(c.get("name", "")).strip() or "Unnamed",
            "weight": float(c.get("weight") or 0),
            "items":  items,
        })
    uncategorized = [i for i in gradebook_items if i not in seen]
    return {"categories": categories, "uncategorized": uncategorized}


def _build_prompt(outline_text: str, gradebook_items: list[str]) -> str:
    items_list = "\n".join(f"- {i}" for i in gradebook_items)
    return f"""You are helping set up a Brightspace gradebook from a course outline.

Most outlines contain a two-column weighting table ("Course Component" /
"Percentage of Final Grade") with one row per component and a Total of ~100%.
Find that structure (it may also be free-form text).

The gradebook currently contains these items (use these EXACT names):
{items_list}

Course outline text:
---
{outline_text}
---

Reply with ONLY a JSON object, no other text:
{{"categories": [{{"name": "<category name>", "weight": <number>, "items": ["<exact item name>", ...]}}]}}

Rules:
- Weights should sum to approximately 100.
- Assign every gradebook item to the best-fitting category.
- Only use item names from the list above. If an item fits nowhere, omit it.
- If you cannot find any weighting information at all, reply: {{"categories": []}}
"""


def _http_json(url: str, headers: dict, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST",
    )
    delays = [5, 20]
    for attempt in range(len(delays) + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            if attempt == len(delays):
                raise AIRateLimitError(
                    "AI provider rate limit/quota hit (HTTP 429). "
                    "Wait a few minutes or switch providers in Settings."
                ) from e
            retry_after = e.headers.get("Retry-After")
            try:
                delay = int(retry_after) if retry_after else delays[attempt]
            except ValueError:
                delay = delays[attempt]
            print(f"  AI provider returned HTTP 429; retrying in {delay}s...")
            time.sleep(delay)
    raise RuntimeError("AI request failed unexpectedly")


def _call_claude(prompt: str, api_key: str) -> str:
    data = _http_json(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        {"model": "claude-sonnet-5", "max_tokens": 4096,
         "messages": [{"role": "user", "content": prompt}]},
    )
    return data["content"][0]["text"]


def _call_gpt(prompt: str, api_key: str) -> str:
    data = _http_json(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": f"Bearer {api_key}"},
        {"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}]},
    )
    return data["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, api_key: str) -> str:
    data = _http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
        {},
        {"contents": [{"parts": [{"text": prompt}]}]},
    )
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _provider_call(provider: str):
    names = {"claude": "_call_claude", "gpt": "_call_gpt", "gemini": "_call_gemini"}
    fn_name = names.get(provider)
    if fn_name is None:
        raise ValueError(f"Unknown AI provider: {provider!r}")
    return globals()[fn_name]


def extract_categories(outline_text: str, gradebook_items: list[str],
                       provider: str, api_key: str) -> dict:
    """One provider-agnostic entry point — nothing else touches a specific API."""
    call = _provider_call(provider)
    prompt = _build_prompt(outline_text, gradebook_items)
    reply = call(prompt, api_key)
    return _parse_ai_response(reply, gradebook_items)


def _build_mapping_prompt(existing_categories: list[dict], items: list[str],
                          outline_text: str = "") -> str:
    cat_lines = []
    for c in existing_categories:
        existing_items = c.get("items") or []
        examples = ", ".join(existing_items) if existing_items else "(none yet)"
        cat_lines.append(
            f"- {c['name']} (weight: {float(c.get('weight') or 0):g}; "
            f"items already in this category: {examples})"
        )
    cats = "\n".join(cat_lines)
    item_list = "\n".join(f"- {i}" for i in items)
    outline_section = ""
    if outline_text and not is_placeholder(outline_text):
        outline_section = f"""

Course outline context:
---
{outline_text}
---"""
    return f"""Assign each gradebook item to the single best-fitting category.

Categories (use these EXACT category names; existing items are examples/context):
{cats}

Gradebook items to assign (use these EXACT names):
{item_list}
{outline_section}

Reply with ONLY a JSON object, no other text:
{{"assignments": [{{"item": "<exact item name>", "category": "<exact category name>"}}, ...]}}

Rules:
- Use only the category names and item names listed above, verbatim.
- Assign every item to exactly one category. If an item fits none, omit it.
"""


def _parse_mapping(text: str, existing_categories: list[dict],
                   items_to_assign: list[str]) -> dict:
    """Distribute items_to_assign into copies of existing_categories (whose
    current items + weights are preserved). Unmatched items → uncategorized."""
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in AI response")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"AI response is not valid JSON: {e}")

    cats = [{"name": c["name"], "weight": float(c.get("weight") or 0),
             "items": list(c.get("items", []))} for c in existing_categories]
    by_name = {c["name"]: c for c in cats}
    to_assign = set(items_to_assign)
    seen: set[str] = set()
    for a in data.get("assignments") or []:
        item, cat = a.get("item"), a.get("category")
        if item in to_assign and item not in seen and cat in by_name:
            by_name[cat]["items"].append(item)
            seen.add(item)
    uncategorized = [i for i in items_to_assign if i not in seen]
    return {"categories": cats, "uncategorized": uncategorized}


def map_items_to_existing(existing_categories: list[dict], items_to_assign: list[str],
                          provider: str, api_key: str,
                          outline_text: str = "") -> dict:
    """Sort loose items into already-existing categories (no new categories,
    weights untouched). Returns the same structure shape as extract_categories."""
    call = _provider_call(provider)
    prompt = _build_mapping_prompt(existing_categories, items_to_assign, outline_text)
    reply = call(prompt, api_key)
    return _parse_mapping(reply, existing_categories, items_to_assign)


def _html_to_text(html: str) -> str:
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    text = _htmllib.unescape(html)
    return re.sub(r'[ \t]+', ' ', text).strip()


def is_placeholder(text: str) -> bool:
    return len(text.strip()) < 100


# In-memory outline cache keyed by course ou. Lives for the app session only —
# a chained run reuses the outline the Course Outline step already fetched;
# a fresh run just fetches. Never applied across courses (key = ou).
_outline_cache: dict[str, str] = {}


async def get_outline_text(page, course_id: str, force: bool = False) -> str:
    """fetch_outline_text with a per-ou session cache."""
    course_id = str(course_id)
    if not force and course_id in _outline_cache:
        print("  Using cached outline text for this course.")
        return _outline_cache[course_id]
    text = await fetch_outline_text(page, course_id)
    if text:
        _outline_cache[course_id] = text
    return text


async def _find_syllabus_topic_url(page, course_id: str) -> str:
    """Return the Brightspace URL for the Course Syllabus topic, or ""."""
    toc_url = f"{BS_BASE}/d2l/api/le/1.4/{course_id}/content/toc"
    toc = await page.evaluate(f"""
        async () => {{
            const r = await fetch('{toc_url}');
            return r.ok ? await r.json() : null;
        }}
    """)
    if not toc:
        return ""

    def find_topic(node):
        for t in node.get("Topics", []):
            if t.get("Title", "").strip() == "Course Syllabus":
                return t
        for m in node.get("Modules", []):
            r = find_topic(m)
            if r:
                return r
        return None

    topic = find_topic(toc)
    if not topic:
        return ""
    topic_url = topic.get("Url", "")
    if not topic_url:
        return ""
    return topic_url if topic_url.startswith("http") else f"{BS_BASE}{topic_url}"


async def _visible_page_text(page) -> str:
    """Scrape readable text from the currently visible browser page."""
    chunks = []
    for frame in page.frames:
        try:
            chunks.append(_html_to_text(await frame.content()))
        except Exception:
            continue
    return "\n\n".join(c for c in chunks if c.strip()).strip()


async def get_confirmed_outline_text(page, course_id: str, confirm_fn) -> str:
    """Preview the detected outline in the browser and let the user confirm.

    If the detected page is wrong or missing, the user can navigate the same
    browser window to the correct outline and press OK; we then scrape the
    visible page instead of the guessed API result.
    """
    topic_url = await _find_syllabus_topic_url(page, course_id)
    if topic_url:
        print("  Opening detected Course Syllabus topic for confirmation...")
        await page.goto(topic_url, wait_until="domcontentloaded")
        answer = confirm_fn(
            "The browser is showing the outline I found. "
            "Is this the correct course outline? (y/n)"
        )
        if str(answer).lower().startswith("y"):
            text = await _visible_page_text(page)
            if text:
                _outline_cache[str(course_id)] = text
            return text

    if not topic_url:
        print("  No 'Course Syllabus' topic found; waiting for manual outline selection.")
    else:
        print("  Detected outline was rejected; waiting for manual outline selection.")
    confirm_fn(
        "Use the browser to open the correct course outline, then click OK here. "
        "I will read the page currently shown in the browser."
    )
    text = await _visible_page_text(page)
    if text:
        _outline_cache[str(course_id)] = text
    return text


async def get_downloaded_outline_text(page, course_id: str, confirm_fn) -> str:
    """Use the Course Outline downloader, then extract raw text for Gemini."""
    from course_outline_automator import find_and_download_outline

    path = await find_and_download_outline(page, course_id=course_id, prompt_fn=confirm_fn)
    if path is None:
        return ""
    text = extract_text_from_file(path)
    if text:
        _outline_cache[str(course_id)] = text
    print(f"  ✓ Extracted outline text from {path.name} ({len(text.strip())} chars)")
    return text


def _term_work(gradebook_items: list[str], reason: str) -> dict:
    """Fallback: a single 'Term Work' category holding every item."""
    return {
        "categories": [{"name": "Term Work", "weight": 100.0,
                        "items": list(gradebook_items)}],
        "uncategorized": [],
        "source": "term_work",
        "reason": reason,
    }


def resolve_categories(outline_text: str, gradebook_items: list[str],
                       provider: str, api_key: str) -> dict:
    """Categories from an outline, or a single 'Term Work' fallback
    when there is no usable outline."""
    if not outline_text or is_placeholder(outline_text):
        return _term_work(gradebook_items, reason="no-outline")
    try:
        result = extract_categories(outline_text, gradebook_items, provider, api_key)
    except ValueError:
        return _term_work(gradebook_items, reason="extract-failed")
    result["source"] = "outline"
    return result


async def fetch_outline_text(page, course_id: str) -> str:
    """
    Scrape the live Course Syllabus topic HTML via the Brightspace TOC API
    (same lookup course_outline_automator uses) and return plain text.
    Returns "" when the topic doesn't exist or its content is empty.
    """
    topic_url = await _find_syllabus_topic_url(page, course_id)
    if not topic_url:
        print("  No 'Course Syllabus' topic found")
        return ""
    html = await page.evaluate(f"""
        async () => {{
            const r = await fetch('{topic_url}');
            return r.ok ? await r.text() : '';
        }}
    """)
    return _html_to_text(html)


def extract_text_from_file(path: Path) -> str:
    """Extract raw text from an outline document for Gemini."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md", ".markdown", ".text", ".csv", ".tsv", ".json"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix in (".html", ".htm"):
        return _html_to_text(path.read_text(encoding="utf-8", errors="ignore"))
    if suffix == ".rtf":
        from course_outline_automator import _convert_rtf_to_docx
        path = _convert_rtf_to_docx(path)
        suffix = path.suffix.lower()
    if suffix == ".pdf":
        import tempfile
        from pdf2docx import Converter
        docx_path = Path(tempfile.mkdtemp(prefix="gb_outline_")) / (path.stem + ".docx")
        cv = Converter(str(path))
        cv.convert(str(docx_path))
        cv.close()
        path = docx_path
        suffix = path.suffix.lower()
    if suffix not in (".docx", ".doc"):
        raise ValueError(f"Unsupported outline file type for text extraction: {path.suffix}")
    import mammoth
    with open(path, "rb") as f:
        return mammoth.extract_raw_text(f).value

# Row classification comes from the edit-link onclick handlers on the Manage
# Grades table (table#z_b): gotoNewEditItemProps = grade item,
# gotoNewEditCatProps = category, gotoNewEditFinalGradeProps = final-grade row
# (skipped). Item rows nested under a category carry padding-left on their
# th.d_ich cell. Selectors confirmed against live HTML provided by the user
# (course ou=11320, 2026-07-03).

_PARSE_GRADES_TABLE_JS = """
    () => {
        // table#z_* ids are render-order counters and shift per course —
        // anchor on the stable grades-grid cell class instead.
        const anchor = document.querySelector('th.d_ich');
        const table = anchor && anchor.closest('table');
        if (!table) return null;
        const rows = [];
        for (const tr of table.querySelectorAll('tr')) {
            const th = tr.querySelector('th.d_ich');
            if (!th) continue;
            const link = th.querySelector('a.d2l-link');
            if (!link) continue;
            const onclick = link.getAttribute('onclick') || '';
            let kind = null;
            if (onclick.includes('gotoNewEditItemProps'))       kind = 'item';
            else if (onclick.includes('gotoNewEditCatProps'))   kind = 'category';
            else if (onclick.includes('gotoNewEditFinalGradeProps')) continue;
            else continue;
            const cells = tr.querySelectorAll('td');
            const weightCell = cells[cells.length - 1];
            rows.push({
                kind,
                name:   link.textContent.trim(),
                nested: (th.getAttribute('style') || '').includes('padding-left'),
                weight: weightCell ? weightCell.textContent.trim() : '',
            });
        }
        return rows;
    }
"""


async def fetch_gradebook_items(page, course_id: str) -> dict:
    """
    Read the Manage Grades table for the course. Returns
    {"items": [all item names], "categories": [{"name", "weight", "items": [...]}],
     "uncategorized": [item names not under any category]}.
    "categories" is empty when the gradebook has no categories yet.
    """
    grades_url = f"{BS_BASE}/d2l/lms/grades/index.d2l?ou={course_id}"
    print("  Opening Grades...")
    await page.goto(grades_url, wait_until="domcontentloaded")

    async def _find_grades_frame(timeout_ms):
        # The Manage Grades table may render inside a D2L content iframe.
        # Poll every frame for the stable grades-grid cell class (the table's
        # own #z_* id is a render-order counter that shifts per course).
        waited = 0
        while waited < timeout_ms:
            for frame in page.frames:
                try:
                    if await frame.query_selector("th.d_ich"):
                        return frame
                except Exception:
                    continue
            await page.wait_for_timeout(300)
            waited += 300
        return None

    frame = await _find_grades_frame(5000)
    if frame is None:
        # Direct URL didn't land on Manage Grades — go via the Grades tab link.
        print("  Direct URL failed — navigating via Grades tab...")
        await page.goto(f"{BS_BASE}/d2l/lms/grades/index.d2l?ou={course_id}",
                        wait_until="domcontentloaded")
        try:
            await page.locator("a.d2l-tool-areas-link:has-text('Manage Grades')").first.click()
        except Exception:
            pass
        frame = await _find_grades_frame(15000)
    if frame is None:
        print("  ✗ Could not find the Manage Grades table (th.d_ich) in any frame")
        print(f"  Current page: {page.url}")
        print(f"  Frames seen: {len(page.frames)}")
        for i, frame_info in enumerate(page.frames, start=1):
            try:
                print(f"    [{i}] {frame_info.url[:160]}")
            except Exception:
                print(f"    [{i}] <frame url unavailable>")
        return {"items": [], "categories": [], "uncategorized": []}

    rows = await frame.evaluate(_PARSE_GRADES_TABLE_JS)
    if not rows:
        print("  No grade items found in Manage Grades table")
        return {"items": [], "categories": [], "uncategorized": []}

    categories, uncategorized, items = [], [], []
    current_cat = None
    for r in rows:
        if r["kind"] == "category":
            try:
                weight = float(r["weight"])
            except (TypeError, ValueError):
                weight = 0.0
            current_cat = {"name": r["name"], "weight": weight, "items": []}
            categories.append(current_cat)
        else:
            items.append(r["name"])
            if r["nested"] and current_cat is not None:
                current_cat["items"].append(r["name"])
            else:
                uncategorized.append(r["name"])

    print(f"  Found {len(items)} item(s), {len(categories)} existing categor(ies)")
    return {"items": items, "categories": categories, "uncategorized": uncategorized}


# ─── Apply — selectors from live walkthrough 2026-07-06/07 (ou=12978) ────────
# Full click-path + gotchas: docs/gradebook_walkthrough_recording.md

# D2L forbids these characters in a category name.
_FORBIDDEN_NAME_CHARS = re.compile(r'[/"*<>+=|,%]')
# Bulk Edit dropdown shows 'Category Name (NN% of final grade)'.
_WEIGHT_SUFFIX = re.compile(r'\s*\(\d+(?:\.\d+)?% of final grade\)\s*$')
_NEW_MENU_SELECTORS = (
    "d2l-dropdown button, button, [role='button'], "
    ".d2l-buttonmenu, .d2l-buttonmenu-content"
)
_CATEGORY_MENU_SELECTORS = (
    "d2l-menu-item[aria-label='Category'], d2l-menu-item, "
    "[role='menuitem'], .d2l-menuitem, .d2l-menu-item, a, button, li"
)


def sanitize_category_name(name: str) -> str:
    """Strip characters D2L rejects in a category name, collapse whitespace."""
    return re.sub(r'\s+', ' ', _FORBIDDEN_NAME_CHARS.sub('', name)).strip()


def _strip_weight_suffix(option_text: str) -> str:
    """'Lab Exams (2) (70% of final grade)' → 'Lab Exams (2)'."""
    return _WEIGHT_SUFFIX.sub('', option_text).strip()


async def _coords_by_text(page, selector: str, text: str):
    """Center coords of first visible `selector` whose text contains `text`,
    searching through nested shadow DOMs (same pattern as actions.py)."""
    return await page.evaluate(
        """
        ([selector, text]) => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const want = norm(text);
            const label = el => norm([
                el.textContent,
                el.getAttribute('aria-label'),
                el.getAttribute('text'),
                el.getAttribute('title'),
                el.getAttribute('data-testid')
            ].filter(Boolean).join(' '));
            function find(root) {
                for (const el of root.querySelectorAll(selector)) {
                    if (label(el).includes(want)) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0)
                            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                    }
                }
                for (const el of root.querySelectorAll('*'))
                    if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
                return null;
            }
            return find(document);
        }
        """,
        [selector, text],
    )


async def _coords_by_text_anywhere(page, selector: str, text: str):
    """Search the page and same-context pages/frames for a visible text match."""
    for candidate_page in [page, *page.context.pages]:
        try:
            coords = await _coords_by_text(candidate_page, selector, text)
            if coords:
                return candidate_page, coords
        except Exception:
            pass
        for frame in candidate_page.frames:
            try:
                handle = await frame.evaluate_handle(
                    """
                    ([selector, text]) => {
                        const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                        const want = norm(text);
                        const label = el => norm([
                            el.textContent,
                            el.getAttribute('aria-label'),
                            el.getAttribute('text'),
                            el.getAttribute('title'),
                            el.getAttribute('data-testid')
                        ].filter(Boolean).join(' '));
                        function find(root) {
                            for (const el of root.querySelectorAll(selector)) {
                                if (label(el).includes(want)) {
                                    const r = el.getBoundingClientRect();
                                    if (r.width > 0 && r.height > 0) return el;
                                }
                            }
                            for (const el of root.querySelectorAll('*')) {
                                if (el.shadowRoot) {
                                    const found = find(el.shadowRoot);
                                    if (found) return found;
                                }
                            }
                            return null;
                        }
                        return find(document);
                    }
                    """,
                    [selector, text],
                )
                element = handle.as_element()
                if element:
                    box = await element.bounding_box()
                    if box:
                        return candidate_page, {
                            "x": box["x"] + box["width"] / 2,
                            "y": box["y"] + box["height"] / 2,
                        }
            except Exception:
                continue
    return None, None


async def _coords_by_attr(page, selector: str):
    """Center coords of first visible `selector`, searching shadow DOMs."""
    return await page.evaluate(
        """
        (selector) => {
            function find(root) {
                for (const el of root.querySelectorAll(selector)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0)
                        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
                for (const el of root.querySelectorAll('*'))
                    if (el.shadowRoot) { const c = find(el.shadowRoot); if (c) return c; }
                return null;
            }
            return find(document);
        }
        """,
        selector,
    )


async def _wait_coords(page, selector: str, text: str | None = None,
                       timeout: int = 10000, interval: int = 100):
    """Poll for an element (optionally by text); coords when visible, else None."""
    waited = 0
    while True:
        c = (await _coords_by_text(page, selector, text) if text
             else await _coords_by_attr(page, selector))
        if c:
            return c
        if waited >= timeout:
            return None
        await page.wait_for_timeout(interval)
        waited += interval


async def _create_one_category(page, name: str, weight: float, last: bool) -> None:
    """Fill the New Category form (already open) and save.
    Selectors: Name #z_g, Weight d2l-input-number #z_u (inner input
    aria-label="Weight"), radio #evenWeight, Save&New #z_b, Save&Close #z_a."""
    print("    · waiting for form (Name field #z_g)...")
    await page.wait_for_selector("#z_g", timeout=15000)
    print(f"    · typing name: {name}")
    await page.fill("#z_g", name)

    # Weight lives inside a d2l-input-number shadow root — click the inner
    # input by coords, select-all, retype (property sets don't sync D2L state).
    print("    · locating Weight input (shadow DOM)...")
    w = await _wait_coords(page, 'input[aria-label="Weight"]', timeout=5000)
    if w is None:
        raise RuntimeError("Weight input not found on New Category form")
    print(f"    · setting weight: {weight:g}")
    await page.mouse.click(w["x"], w["y"])
    await page.keyboard.press("Control+a")
    await page.keyboard.type(f"{weight:g}")
    await page.keyboard.press("Tab")          # commit → syncs hidden input

    print("    · checking 'Distribute weight evenly' radio...")
    await page.check("#evenWeight")           # distribute weight evenly

    btn, btn_name = ("#z_a", "Save and Close") if last else ("#z_b", "Save and New")
    print(f"    · clicking {btn_name} ({btn})...")
    async with page.expect_navigation(wait_until="domcontentloaded"):
        await page.click(btn)
    print("    · saved, page reloaded.")


async def _open_new_category_form(page) -> None:
    """From the grades list, click New -> Category."""
    print("    - locating 'New' menu button...")
    new_btn = await _wait_coords(page, _NEW_MENU_SELECTORS, "New", timeout=10000)
    if new_btn is None:
        raise RuntimeError("'New' menu button not found on grades list")
    print(f"    - clicking 'New' at ({new_btn['x']:.0f},{new_btn['y']:.0f})...")
    await page.mouse.click(new_btn["x"], new_btn["y"])
    await page.wait_for_timeout(500)

    print("    - locating 'Category' menu item...")
    cat_page, cat = await _coords_by_text_anywhere(
        page, _CATEGORY_MENU_SELECTORS, "Category"
    )
    if cat is None:
        labels = await page.evaluate(
            """
            () => [...document.querySelectorAll("d2l-menu-item, [role='menuitem'], .d2l-menuitem, .d2l-menu-item, a, button, li")]
                .map(el => (el.textContent || el.getAttribute('aria-label') || el.getAttribute('text') || '').replace(/\\s+/g, ' ').trim())
                .filter(Boolean)
                .slice(0, 30)
            """
        )
        if labels:
            print(f"    - visible menu candidates: {labels}")
        raise RuntimeError("'Category' item not found in New menu")
    print("    - clicking 'Category'...")
    click_page = cat_page or page
    async with click_page.expect_navigation(wait_until="domcontentloaded"):
        await click_page.mouse.click(cat["x"], cat["y"])
    print("    - New Category form opened.")

_COLLECT_MULTIEDIT_ROWS_JS = """
    () => {
        // A row is a grade ITEM iff it has a category <select> (options
        // mention 'of final grade'). Categories/final-grade rows don't.
        const rows = [];
        for (const sel of document.querySelectorAll('select')) {
            const opts = [...sel.options];
            if (!opts.some(o => /of final grade/i.test(o.text))) continue;
            const tr = sel.closest('tr');
            const nameInput = tr && tr.querySelector('input[type="text"]');
            if (!nameInput || !sel.id) continue;
            rows.push({
                name: nameInput.value.trim(),
                selectId: sel.id,
                options: opts.map(o => ({ value: o.value, text: o.text.trim() })),
            });
        }
        return rows;
    }
"""

_VERIFY_GRADES_JS = """
    () => {
        const body = (document.querySelector('#d_content') || document.body).innerText;
        const warn = body.match(/[^\\n]*sums to \\d+(?:\\.\\d+)?%, not 100%[^\\n]*/i);
        let fcg = null;
        for (const tr of document.querySelectorAll('tr')) {
            if (/Final Calculated Grade/i.test(tr.textContent)) {
                const m = tr.innerText.trim().match(/(\\d+(?:\\.\\d+)?)\\s*$/);
                if (m) fcg = parseFloat(m[1]);
            }
        }
        return { fcg, warning: warn ? warn[0].trim() : null };
    }
"""


async def verify_gradebook(page, course_id: str) -> dict:
    """Read the grades list: Final Calculated Grade total + warning banner.
    Returns {"fcg": float|None, "warning": str|None, "ok": bool}."""
    await page.goto(f"{BS_BASE}/d2l/lms/grades/admin/manage/gradeslist.d2l?ou={course_id}",
                    wait_until="domcontentloaded")
    await page.wait_for_selector("th.d_ich", timeout=15000)
    r = await page.evaluate(_VERIFY_GRADES_JS)
    r["ok"] = (r["fcg"] == 100) and not r["warning"]
    return r


def _split_existing(cats: list[dict], existing_names: set[str]) -> tuple[list, list]:
    """Split board categories into (to_create, skipped) against what already
    exists in the gradebook — re-running a course must never duplicate."""
    to_create, skipped = [], []
    for cat in cats:
        if sanitize_category_name(cat["name"]) in existing_names:
            skipped.append(cat)
        else:
            to_create.append(cat)
    return to_create, skipped


async def apply_categories(page, course_id: str, structure: dict, step_fn) -> None:
    """Create missing categories, bulk-assign items, verify the total.
    Categories that already exist are skipped (idempotent re-runs).
    step_fn(label) pauses for user confirmation before each phase step."""
    grades_url = f"{BS_BASE}/d2l/lms/grades/admin/manage/gradeslist.d2l?ou={course_id}"
    cats = structure["categories"]

    # ── Phase A: create only categories that don't already exist ──
    existing = {c["name"] for c in (await fetch_gradebook_items(page, course_id))["categories"]}
    to_create, skipped = _split_existing(cats, existing)
    for cat in skipped:
        print(f"  ↷ Category '{sanitize_category_name(cat['name'])}' already exists — skipped "
              "(weight left as-is).")
    if to_create:
        print(f"  Creating {len(to_create)} categor(ies)...")
        await page.goto(grades_url, wait_until="domcontentloaded")
        for i, cat in enumerate(to_create):
            name = sanitize_category_name(cat["name"])
            step_fn(f"create category '{name}' ({cat['weight']:g}%)")
            if i == 0:
                await _open_new_category_form(page)
            # after Save&New the fresh blank form is already open
            await _create_one_category(page, name, float(cat["weight"]),
                                       last=(i == len(to_create) - 1))
            print(f"  ✓ Category '{name}' ({cat['weight']:g}%)")

    # ── Phase B: assort items via Bulk Edit ──
    mapping = {}
    for cat in cats:
        for item in cat["items"]:
            mapping[item] = sanitize_category_name(cat["name"])
    if mapping:
        step_fn("assign items to categories (Bulk Edit)")
        print("  Opening grades list for Bulk Edit...")
        await page.goto(grades_url, wait_until="domcontentloaded")
        # name="z_*_cb_sa" derives from the table's render-order id — use the
        # stable aria-label instead.
        print("    · checking 'Select all rows'...")
        await page.check('input[aria-label="Select all rows"]')
        print("    · locating 'Bulk Edit' button...")
        bulk = await _wait_coords(page, "button", "Bulk Edit", timeout=10000)
        if bulk is None:
            raise RuntimeError("'Bulk Edit' button not found")
        print("    · clicking 'Bulk Edit'...")
        async with page.expect_navigation(wait_until="domcontentloaded"):
            await page.mouse.click(bulk["x"], bulk["y"])

        rows = await page.evaluate(_COLLECT_MULTIEDIT_ROWS_JS)
        print(f"  Bulk Edit: {len(rows)} item row(s) found")
        for row in rows:
            print(f"    · row: '{row['name']}' → planned: "
                  f"{mapping.get(row['name'], '(no change)')}")
        assigned = 0
        for row in rows:
            target = mapping.get(row["name"])
            if not target:
                continue
            value = next((o["value"] for o in row["options"]
                          if _strip_weight_suffix(o["text"]) == target), None)
            if value is None:
                opts = [o["text"] for o in row["options"]]
                print(f"  ⚠ No dropdown option matches '{target}' for item "
                      f"'{row['name']}'. Options were: {opts}")
                continue
            print(f"    · assigning '{row['name']}' → '{target}'")
            await page.select_option(f'#{row["selectId"]}', value)
            assigned += 1
        print(f"  ✓ Assigned {assigned}/{len(mapping)} item(s)")
        print("    · clicking Save (#z_a)...")
        async with page.expect_navigation(wait_until="domcontentloaded"):
            await page.click("#z_a")                          # Save
        print("    · Bulk Edit saved.")

    # ── Phase C: verify Final Calculated Grade == 100% ──
    result = await verify_gradebook(page, course_id)
    if result["ok"]:
        print("  ✓ Final Calculated Grade sums to 100% — gradebook looks correct.")
    else:
        if result["warning"]:
            print(f"  ⚠ Brightspace warning: {result['warning']}")
        print(f"  ⚠ Final Calculated Grade total is {result['fcg']} (expected 100) "
              "— please verify the gradebook manually.")
    print("  ℹ Reminder: rename the course from '_Staged' to '_Review' when done.")
