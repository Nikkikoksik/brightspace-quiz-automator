"""Tests for src/gradebook_automator.py — AI parsing, prompt, outline text helpers."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from io import BytesIO
from pathlib import Path
import urllib.error

import pytest
import gradebook_automator as ga


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


ITEMS = ["Quiz 1", "Quiz 2", "Final Exam", "Project"]

GOOD_JSON = '''
{"categories": [
  {"name": "Quizzes", "weight": 20, "items": ["Quiz 1", "Quiz 2"]},
  {"name": "Final Exam", "weight": 50, "items": ["Final Exam"]},
  {"name": "Project", "weight": 30, "items": ["Project"]}
]}
'''


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


def test_parse_plain_json():
    s = ga._parse_ai_response(GOOD_JSON, ITEMS)
    assert [c["name"] for c in s["categories"]] == ["Quizzes", "Final Exam", "Project"]
    assert s["categories"][0]["weight"] == 20.0
    assert s["uncategorized"] == []


def test_parse_markdown_fenced_json():
    fenced = "Here you go:\n```json\n" + GOOD_JSON + "\n```\nDone."
    s = ga._parse_ai_response(fenced, ITEMS)
    assert len(s["categories"]) == 3


def test_hallucinated_item_dropped():
    bad = '{"categories": [{"name": "Quizzes", "weight": 100, "items": ["Quiz 1", "Ghost Quiz"]}]}'
    s = ga._parse_ai_response(bad, ["Quiz 1"])
    assert s["categories"][0]["items"] == ["Quiz 1"]


def test_missed_item_goes_uncategorized():
    partial = '{"categories": [{"name": "Quizzes", "weight": 100, "items": ["Quiz 1"]}]}'
    s = ga._parse_ai_response(partial, ["Quiz 1", "Forgotten"])
    assert s["uncategorized"] == ["Forgotten"]


def test_unparseable_raises():
    with pytest.raises(ValueError):
        ga._parse_ai_response("no json here at all", ITEMS)


def test_no_categories_raises():
    with pytest.raises(ValueError):
        ga._parse_ai_response('{"categories": []}', ITEMS)


def test_http_json_retries_429_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(req, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests", {}, BytesIO()
            )
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(ga.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ga.time, "sleep", lambda seconds: None)

    assert ga._http_json("https://example.test", {}, {}) == {"ok": True}
    assert calls["count"] == 2


def test_http_json_raises_clear_rate_limit_after_retries(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 429, "Too Many Requests", {}, BytesIO()
        )

    monkeypatch.setattr(ga.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ga.time, "sleep", lambda seconds: None)

    with pytest.raises(ga.AIRateLimitError, match="HTTP 429"):
        ga._http_json("https://example.test", {}, {})


# ─── map_items_to_existing — sort loose items into existing categories ────────

EXISTING = [
    {"name": "Pre-lab Quizzes", "weight": 10.0, "items": []},
    {"name": "Lab Exams (2)", "weight": 70.0, "items": ["Midterm Lab Exam"]},
]


def test_parse_mapping_distributes_and_preserves():
    reply = ('{"assignments": ['
             '{"item": "Pre-lab quiz 1", "category": "Pre-lab Quizzes"},'
             '{"item": "Final Lab Exam", "category": "Lab Exams (2)"}]}')
    out = ga._parse_mapping(reply, EXISTING, ["Pre-lab quiz 1", "Final Lab Exam"])
    quizzes = next(c for c in out["categories"] if c["name"] == "Pre-lab Quizzes")
    exams = next(c for c in out["categories"] if c["name"] == "Lab Exams (2)")
    assert quizzes["items"] == ["Pre-lab quiz 1"]
    assert quizzes["weight"] == 10.0                       # weight preserved
    assert exams["items"] == ["Midterm Lab Exam", "Final Lab Exam"]  # existing kept
    assert out["uncategorized"] == []


def test_parse_mapping_unmatched_goes_uncategorized():
    reply = '{"assignments": [{"item": "Ghost", "category": "Nowhere"}]}'
    out = ga._parse_mapping(reply, EXISTING, ["Real Item"])
    assert out["uncategorized"] == ["Real Item"]           # invented ones dropped


def test_parse_mapping_ignores_items_not_in_assign_set():
    reply = '{"assignments": [{"item": "Not asked", "category": "Pre-lab Quizzes"}]}'
    out = ga._parse_mapping(reply, EXISTING, ["Asked Item"])
    quizzes = next(c for c in out["categories"] if c["name"] == "Pre-lab Quizzes")
    assert "Not asked" not in quizzes["items"]
    assert out["uncategorized"] == ["Asked Item"]


# ─── resolve_categories — Term Work fallback ─────────────────────────────────

def test_mapping_prompt_includes_existing_items_and_outline_context():
    prompt = ga._build_mapping_prompt(
        EXISTING,
        ["Pre-lab quiz 1"],
        "Pre-lab quizzes are worth 10% of the final grade. "
        "Students complete one quiz before each lab session. " * 3,
    )
    assert "Pre-lab Quizzes" in prompt
    assert "Midterm Lab Exam" in prompt
    assert "Pre-lab quiz 1" in prompt
    assert "Course outline context" in prompt


def test_extract_text_from_plain_text_file():
    path = Path(__file__).parent / "fixtures" / "outline.txt"
    assert "Evaluation Schema" in ga.extract_text_from_file(path)


def test_extract_text_from_html_file():
    path = Path(__file__).parent / "fixtures" / "outline.html"
    text = ga.extract_text_from_file(path)
    assert "Evaluation Schema" in text
    assert "<p>" not in text


def test_parse_evaluation_html_table():
    html = (Path(__file__).parent / "fixtures" / "evaluations.html").read_text(
        encoding="utf-8"
    )
    rows = ga.parse_evaluation_html(html)
    assert [r["name"] for r in rows] == [
        "Pre-lab Quizzes",
        "Lab Activities and Assignments",
        "Formal Lab Report",
        "Lab Exams (2)",
    ]
    assert [r["weight"] for r in rows] == [10.0, 15.0, 5.0, 70.0]


def test_structure_from_evaluation_html_sorts_items_without_ai():
    html = (Path(__file__).parent / "fixtures" / "evaluations.html").read_text(
        encoding="utf-8"
    )
    items = [
        "Pre-lab quiz 1",
        "Pre-lab quiz 2",
        "Formal Lab Report",
        "Midterm Lab Exam I",
        "Midterm Lab Exam II",
        "Lab Activity A",
        "Mystery Bonus",
    ]
    out = ga.structure_from_evaluation_html(html, items)
    by_name = {c["name"]: c for c in out["categories"]}
    assert by_name["Pre-lab Quizzes"]["items"] == ["Pre-lab quiz 1", "Pre-lab quiz 2"]
    assert by_name["Formal Lab Report"]["items"] == ["Formal Lab Report"]
    assert by_name["Lab Exams (2)"]["items"] == ["Midterm Lab Exam I", "Midterm Lab Exam II"]
    assert by_name["Lab Activities and Assignments"]["items"] == ["Lab Activity A"]
    assert out["uncategorized"] == ["Mystery Bonus"]


def test_resolve_no_outline_falls_back_to_term_work():
    r = ga.resolve_categories("", ITEMS, "claude", "FAKE")
    assert r["source"] == "term_work"
    assert r["reason"] == "no-outline"
    assert r["categories"] == [
        {"name": "Term Work", "weight": 100.0, "items": ITEMS}
    ]
    assert r["uncategorized"] == []


def test_resolve_placeholder_outline_falls_back(monkeypatch):
    # placeholder text (<100 chars) must never reach the AI
    def boom(*a, **k):
        raise AssertionError("extract_categories should not be called")
    monkeypatch.setattr(ga, "extract_categories", boom)
    r = ga.resolve_categories("too short to be an outline", ITEMS, "claude", "FAKE")
    assert r["reason"] == "no-outline"


def test_resolve_extract_failure_falls_back(monkeypatch):
    def fail(*a, **k):
        raise ValueError("AI response contained no categories")
    monkeypatch.setattr(ga, "extract_categories", fail)
    r = ga.resolve_categories("x" * 200, ITEMS, "claude", "FAKE")
    assert r["source"] == "term_work"
    assert r["reason"] == "extract-failed"
    assert r["categories"][0]["items"] == ITEMS


def test_resolve_success_passes_through(monkeypatch):
    structure = {
        "categories": [{"name": "Quizzes", "weight": 40.0,
                        "items": ["Quiz 1", "Quiz 2"]}],
        "uncategorized": ["Final Exam", "Project"],
    }
    monkeypatch.setattr(ga, "extract_categories", lambda *a, **k: dict(structure))
    r = ga.resolve_categories("x" * 200, ITEMS, "claude", "FAKE")
    assert r["source"] == "outline"
    assert r["categories"] == structure["categories"]
    assert r["uncategorized"] == structure["uncategorized"]


# ─── apply_categories helpers — name sanitizing, dropdown matching ────────────

def test_sanitize_strips_forbidden_chars():
    # D2L forbids: / " * < > + = | , %
    assert ga.sanitize_category_name('Labs + Quizzes = 40%') == 'Labs Quizzes 40'
    assert ga.sanitize_category_name('A/B "test" <cat>, 50%|*') == 'AB test cat 50'


def test_sanitize_keeps_allowed_chars():
    assert ga.sanitize_category_name('Lab Exams (2)') == 'Lab Exams (2)'
    assert ga.sanitize_category_name('Labs & Quizzes') == 'Labs & Quizzes'


def test_sanitize_collapses_whitespace():
    assert ga.sanitize_category_name('  Term   Work  ') == 'Term Work'


def test_strip_weight_suffix():
    assert ga._strip_weight_suffix('Pre-lab Quizzes (10% of final grade)') == 'Pre-lab Quizzes'
    assert ga._strip_weight_suffix('Lab Exams (2) (70% of final grade)') == 'Lab Exams (2)'
    assert ga._strip_weight_suffix('Report (12.5% of final grade)') == 'Report'
    assert ga._strip_weight_suffix('None') == 'None'   # no suffix → unchanged


def test_new_menu_selectors_cover_legacy_buttonmenu():
    assert ".d2l-buttonmenu-content" in ga._NEW_MENU_SELECTORS
    assert "d2l-dropdown button" in ga._NEW_MENU_SELECTORS
    assert "[role='menuitem']" in ga._CATEGORY_MENU_SELECTORS


# ─── skip-existing (idempotent re-runs) ───────────────────────────────────────

def test_split_existing_skips_matches():
    cats = [{"name": "Quizzes", "weight": 40.0, "items": []},
            {"name": "Labs", "weight": 60.0, "items": []}]
    to_create, skipped = ga._split_existing(cats, {"Quizzes"})
    assert [c["name"] for c in to_create] == ["Labs"]
    assert [c["name"] for c in skipped] == ["Quizzes"]


def test_split_existing_compares_sanitized():
    # Board name has forbidden chars; gradebook holds the sanitized version.
    cats = [{"name": "Labs + Quizzes = 40%", "weight": 40.0, "items": []}]
    to_create, skipped = ga._split_existing(cats, {"Labs Quizzes 40"})
    assert to_create == []
    assert len(skipped) == 1


def test_split_existing_all_new():
    cats = [{"name": "Term Work", "weight": 100.0, "items": []}]
    to_create, skipped = ga._split_existing(cats, set())
    assert len(to_create) == 1 and skipped == []


# ─── outline cache ────────────────────────────────────────────────────────────

def test_get_outline_text_caches_by_ou(monkeypatch):
    import asyncio
    calls = []

    async def fake_fetch(page, ou):
        calls.append(ou)
        return f"outline for {ou}"

    monkeypatch.setattr(ga, "fetch_outline_text", fake_fetch)
    ga._outline_cache.clear()
    assert asyncio.run(ga.get_outline_text(None, "111")) == "outline for 111"
    assert asyncio.run(ga.get_outline_text(None, "111")) == "outline for 111"
    assert asyncio.run(ga.get_outline_text(None, "222")) == "outline for 222"
    assert calls == ["111", "222"]      # second 111 hit the cache
    ga._outline_cache.clear()


def test_get_outline_text_empty_result_not_cached(monkeypatch):
    import asyncio
    calls = []

    async def fake_fetch(page, ou):
        calls.append(ou)
        return ""

    monkeypatch.setattr(ga, "fetch_outline_text", fake_fetch)
    ga._outline_cache.clear()
    asyncio.run(ga.get_outline_text(None, "333"))
    asyncio.run(ga.get_outline_text(None, "333"))
    assert calls == ["333", "333"]      # empty result → retried, not cached
    ga._outline_cache.clear()


def test_build_prompt_mentions_items_and_table_hint():
    p = ga._build_prompt("outline text", ["Quiz 1"])
    assert "Quiz 1" in p
    assert "100" in p          # sums-to-~100% guidance
    assert "JSON" in p


def test_extract_categories_dispatch(monkeypatch):
    calls = {}
    def fake_claude(prompt, api_key):
        calls["key"] = api_key
        return GOOD_JSON
    monkeypatch.setattr(ga, "_call_claude", fake_claude)
    s = ga.extract_categories("outline", ITEMS, "claude", "sk-test")
    assert calls["key"] == "sk-test"
    assert len(s["categories"]) == 3


def test_extract_categories_unknown_provider():
    with pytest.raises(ValueError):
        ga.extract_categories("outline", ITEMS, "grok", "k")


def test_html_to_text_strips_tags_and_scripts():
    html = "<html><head><style>x{}</style></head><body><h1>Weights</h1><script>bad()</script><p>Quiz 10%</p></body></html>"
    text = ga._html_to_text(html)
    assert "Weights" in text and "Quiz 10%" in text
    assert "bad()" not in text and "x{}" not in text


def test_null_weight_becomes_zero():
    s = ga._parse_ai_response(
        '{"categories": [{"name": "Quizzes", "weight": null, "items": ["Quiz 1"]}]}',
        ["Quiz 1"])
    assert s["categories"][0]["weight"] == 0.0


def test_is_placeholder():
    assert ga.is_placeholder("")
    assert ga.is_placeholder("   \n  short  ")
    assert not ga.is_placeholder("x" * 200)
