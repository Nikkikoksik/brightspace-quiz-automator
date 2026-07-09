import asyncio
from pathlib import Path

import course_outline_automator as co


class _FakePage:
    def __init__(self):
        self.gotos = []
        self.waits = []

    async def goto(self, url, **kwargs):
        self.gotos.append((url, kwargs))

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


def test_find_outline_opens_content_before_scanning(monkeypatch):
    page = _FakePage()
    calls = []

    async def fake_fetch(page_arg, course_id):
        calls.append(("fetch", course_id, list(page_arg.gotos)))
        return []

    async def fake_manual(page_arg, download_dir, prompt_fn):
        calls.append(("manual", str(download_dir)))
        return None

    monkeypatch.setattr(co, "_HERE", Path.cwd())
    monkeypatch.setattr(co, "_fetch_matching_topics", fake_fetch)
    monkeypatch.setattr(co, "_manual_download_fallback", fake_manual)

    result = asyncio.run(co.find_and_download_outline(page, course_id="12790"))

    assert result is None
    assert page.gotos[0][0] == f"{co.BRIGHTSPACE_BASE}/d2l/le/lessons/12790"
    assert calls[0][0] == "fetch"
    assert calls[0][2][0][0].endswith("/d2l/le/lessons/12790")
