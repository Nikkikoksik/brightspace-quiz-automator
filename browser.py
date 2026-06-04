import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

from navigation import get_quiz_names, open_quiz_edit, get_assignment_names, open_assignment_edit, discover_course_urls
from actions import apply_gradebook, apply_auto_submit, save_quiz, apply_assignment_gradebook, save_assignment

SESSION_FILE = str(Path(__file__).parent / "session.json")


async def _wait_for_login(page, context):
    """Navigate to Brightspace, wait for user login, save session."""
    print("Opening Brightspace...")
    await page.goto("https://learn.okanagancollege.ca")
    print("─" * 50)
    print("  Log in with your Okanagan College account.")
    print("  Complete any MFA steps (email code, authenticator, etc.).")
    print("  Script continues automatically once you reach the home page.")
    print("─" * 50)
    for i in range(180):
        await page.wait_for_timeout(3000)
        url = page.url
        if "learn.okanagancollege.ca" in url and "microsoftonline.com" not in url:
            has_login_form = await page.evaluate("() => !!document.querySelector('#userName')")
            if has_login_form:
                continue
            try:
                await page.goto("https://learn.okanagancollege.ca/d2l/home", timeout=15000)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                await page.wait_for_timeout(2000)
            except Exception:
                pass
            if "/d2l/home" in page.url:
                break
        if i % 10 == 0 and i > 0:
            print(f"  Still waiting... ({i * 3}s)  |  {page.url[:80]}")
    else:
        raise RuntimeError("Login timed out after 9 minutes")
    print("✓ Logged in — saving session...")
    await page.wait_for_load_state("networkidle", timeout=20000)
    await context.storage_state(path=SESSION_FILE)
    print("✓ Session saved")


async def run_bs_login():
    """Standalone: open Brightspace, wait for login, save session. Used by Settings panel."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None
        )
        page = await context.new_page()
        await _wait_for_login(page, context)
        await browser.close()


async def run(urls: list[str], dry_run: bool, settings: dict, limit: int | None = None, pause_fn=None, ask_fn=None, review_fn=None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        for raw_url in urls:
            print(f"\n{'─' * 50}")
            print(f"Course: {raw_url}")

            print("  Discovering quiz URL from course page...")
            found = await discover_course_urls(page, raw_url)
            quiz_url = found.get("quizzes")
            if not quiz_url:
                print("✗ Could not find Quizzes link on this course page.")
                continue
            print(f"  Quiz list: {quiz_url}")

            try:
                await page.goto(quiz_url, wait_until="commit")
            except Exception:
                pass
            await page.wait_for_url("**/quizzing/**", timeout=60000)
            await page.wait_for_load_state("networkidle")
            await context.storage_state(path=SESSION_FILE)

            if dry_run:
                print("⚠  DRY RUN MODE — nothing will be saved")

            names = await get_quiz_names(page)
            if not names:
                print("✗ No quizzes found.")
                continue

            total = len(names)
            if limit:
                names = names[:limit]
            loop = asyncio.get_running_loop()
            start_from = await loop.run_in_executor(None, ask_fn, total, "quiz") if ask_fn else 1
            if start_from > 1:
                names = names[start_from - 1:]
                print(f"Resuming from #{start_from} of {total}...")
            else:
                print(f"Found {total} quiz(es). Starting...")

            for i, name in enumerate(names, start_from):
                print(f"\n[{i}/{total}]  [{name}]")
                try:
                    await page.goto(quiz_url, wait_until="commit")
                except Exception:
                    pass
                await page.wait_for_selector(
                    "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
                )
                await open_quiz_edit(page, name)
                if settings.get("set_in_gradebook"):
                    await apply_gradebook(page, dry_run)
                if settings.get("set_auto_submit"):
                    await apply_auto_submit(page, dry_run)
                await save_quiz(page, dry_run)
                if pause_fn:
                    pause_fn()

        print(f"\n{'─' * 50}")
        print("✓  All done!")
        if review_fn:
            review_fn()
        await browser.close()


async def run_timer_fix(urls: list[str], dry_run: bool, ask_fn=None, pause_fn=None):
    """Re-run only the auto-submit timer fix on quizzes (no gradebook)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        for course_url in urls:
            print(f"\n{'─' * 50}")
            print(f"Course: {course_url}")

            try:
                await page.goto(course_url, wait_until="commit")
            except Exception:
                pass
            await page.wait_for_url("**/quizzing/**", timeout=60000)
            await page.wait_for_load_state("networkidle")

            if dry_run:
                print("⚠  DRY RUN MODE — nothing will be saved")

            names = await get_quiz_names(page)
            if not names:
                print("✗ No quizzes found.")
                continue

            total = len(names)
            loop = asyncio.get_running_loop()
            start_from = await loop.run_in_executor(None, ask_fn, total, "quiz") if ask_fn else 1
            if start_from > 1:
                names = names[start_from - 1:]
                print(f"Resuming from #{start_from} of {total}...")
            else:
                print(f"Found {total} quiz(es). Starting timer fix...")

            for i, name in enumerate(names, start_from):
                print(f"\n[{i}/{total}]  [{name}]")
                try:
                    await page.goto(course_url, wait_until="commit")
                except Exception:
                    pass
                await page.wait_for_selector(
                    "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
                )
                await open_quiz_edit(page, name)
                await apply_auto_submit(page, dry_run)
                await save_quiz(page, dry_run)
                if pause_fn:
                    pause_fn()

        print(f"\n{'─' * 50}")
        print("✓  All done!")
        await browser.close()


async def run_assignments(urls: list[str], dry_run: bool, settings: dict, limit: int | None = None, pause_fn=None, ask_fn=None, review_fn=None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False, slow_mo=80,
            args=["--start-maximized"],
        )
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None,
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

        for raw_url in urls:
            print(f"\n{'─' * 50}")
            print(f"Course: {raw_url}")

            print("  Discovering assignment URL from course page...")
            found = await discover_course_urls(page, raw_url)
            asgn_url = found.get("assignments")
            if not asgn_url:
                print("✗ Could not find Assignments link on this course page.")
                continue
            print(f"  Assignment list: {asgn_url}")

            try:
                await page.goto(asgn_url, wait_until="commit")
            except Exception:
                pass
            await page.wait_for_selector(
                "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
            )

            if dry_run:
                print("⚠  DRY RUN MODE — nothing will be saved")

            names = await get_assignment_names(page)
            print(f"  Found names: {names}")
            if not names:
                print("✗ No assignments found.")
                continue

            total = len(names)
            if limit:
                names = names[:limit]
            loop = asyncio.get_running_loop()
            start_from = await loop.run_in_executor(None, ask_fn, total, "assignment") if ask_fn else 1
            if start_from > 1:
                names = names[start_from - 1:]
                print(f"Resuming from #{start_from} of {total}...")
            else:
                print(f"Found {total} assignment(s). Starting...")

            for i, name in enumerate(names, start_from):
                print(f"\n[{i}/{total}]  [{name}]")
                try:
                    await page.goto(asgn_url, wait_until="commit")
                except Exception:
                    pass
                await page.wait_for_selector(
                    "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
                )
                await open_assignment_edit(page, name)
                print(f"  Edit URL : {page.url[:100]}")
                if settings.get("set_in_gradebook"):
                    await apply_assignment_gradebook(page, dry_run)
                await save_assignment(page, dry_run)
                if pause_fn:
                    pause_fn()

        print(f"\n{'─' * 50}")
        print("✓  All done!")
        if review_fn:
            review_fn()
        await browser.close()
