#!/usr/bin/env python3
"""
Gradebook Automator — outline → AI-proposed categories → review → apply.
fetch_gradebook_items / apply_categories are STUBS until the live
Brightspace walkthrough (see design spec 2026-07-02).
"""
import html as _htmllib
import json
import re
import sys
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

_HERE   = Path(__file__).parent.parent
BS_BASE = "https://learn.okanagancollege.ca"


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
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def extract_categories(outline_text: str, gradebook_items: list[str],
                       provider: str, api_key: str) -> dict:
    """One provider-agnostic entry point — nothing else touches a specific API."""
    names = {"claude": "_call_claude", "gpt": "_call_gpt", "gemini": "_call_gemini"}
    fn_name = names.get(provider)
    if fn_name is None:
        raise ValueError(f"Unknown AI provider: {provider!r}")
    call = globals()[fn_name]
    prompt = _build_prompt(outline_text, gradebook_items)
    reply = call(prompt, api_key)
    return _parse_ai_response(reply, gradebook_items)


def _html_to_text(html: str) -> str:
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    text = _htmllib.unescape(html)
    return re.sub(r'[ \t]+', ' ', text).strip()


def is_placeholder(text: str) -> bool:
    return len(text.strip()) < 100


async def fetch_outline_text(page, course_id: str) -> str:
    """
    Scrape the live Course Syllabus topic HTML via the Brightspace TOC API
    (same lookup course_outline_automator uses) and return plain text.
    Returns "" when the topic doesn't exist or its content is empty.
    """
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
        print("  No 'Course Syllabus' topic found")
        return ""
    topic_url = topic.get("Url", "")
    if not topic_url:
        return ""
    html = await page.evaluate(f"""
        async () => {{
            const r = await fetch('{BS_BASE}{topic_url}');
            return r.ok ? await r.text() : '';
        }}
    """)
    return _html_to_text(html)


def extract_text_from_file(path: Path) -> str:
    """Local-file fallback: .pdf converted via pdf2docx first, then mammoth."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        from pdf2docx import Converter
        docx_path = path.with_suffix(".docx")
        cv = Converter(str(path))
        cv.convert(str(docx_path))
        cv.close()
        path = docx_path
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
        const table = document.querySelector('table#z_b');
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
    manage_url = f"{BS_BASE}/d2l/lms/grades/admin/manage/main.d2l?ou={course_id}"
    print("  Opening Manage Grades...")
    await page.goto(manage_url, wait_until="domcontentloaded")

    async def _find_grades_frame(timeout_ms):
        # The Manage Grades table renders inside a D2L content iframe, so the
        # top-level page never sees table#z_b. Poll every frame for it.
        waited = 0
        while waited < timeout_ms:
            for frame in page.frames:
                try:
                    if await frame.query_selector("table#z_b"):
                        return frame
                except Exception:
                    continue
            await page.wait_for_timeout(300)
            waited += 300
        return None

    frame = await _find_grades_frame(10000)
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
        print("  ✗ Could not find the Manage Grades table (table#z_b) in any frame")
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


# ─── STUB — to be implemented via live Brightspace walkthrough ───────────────
# (spec 2026-07-02: do NOT guess Grades-page selectors; the user demonstrates
# the real click-path and that becomes the implementation.)


async def apply_categories(page, structure: dict, step_fn) -> None:
    """STUB: create categories and move items via the Grades UI, one category
    at a time; step_fn(name) pauses before each category."""
    for cat in structure["categories"]:
        step_fn(cat["name"])
        print(f"  ⚠ STUB apply_categories — would create '{cat['name']}' "
              f"({cat['weight']}%) with {len(cat['items'])} item(s)")
