import os
from pathlib import Path
from playwright.async_api import async_playwright

from navigation import get_quiz_names, open_quiz_edit, get_assignment_names, open_assignment_edit
from actions import apply_gradebook, apply_auto_submit, save_quiz, apply_assignment_gradebook, save_assignment

SESSION_FILE = str(Path(__file__).parent / "session.json")


async def run(urls: list[str], dry_run: bool, settings: dict, limit: int | None = None, pause_fn=None, start_from: int = 1):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None
        )
        page = await context.new_page()

        # Pre-login: open Brightspace home and wait for confirmed login
        print("Opening Brightspace...")
        await page.goto("https://learn.okanagancollege.ca")
        print("─" * 50)
        print("  Log in with your Okanagan College account.")
        print("  Complete any MFA steps (email code, authenticator, etc.).")
        print("  The script will continue automatically once you are on")
        print("  the Brightspace home page.")
        print("─" * 50)

        for i in range(180):
            await page.wait_for_timeout(3000)
            url = page.url
            on_bs = "learn.okanagancollege.ca" in url
            on_ms = "microsoftonline.com" in url or "login.microsoft" in url
            if on_bs and not on_ms:
                try:
                    await page.goto("https://learn.okanagancollege.ca/d2l/home", timeout=15000)
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass
                if "learn.okanagancollege.ca" in page.url and "microsoftonline.com" not in page.url:
                    break
            if i % 10 == 0 and i > 0:
                print(f"  Still waiting... ({i * 3}s)  |  {url[:80]}")
        else:
            raise RuntimeError("Login timed out after 9 minutes")

        print(f"✓ Logged in — saving session...")
        await page.wait_for_load_state("networkidle", timeout=20000)
        await context.storage_state(path=SESSION_FILE)
        print("✓ Session saved")

        for course_url in urls:
            print(f"\n{'─' * 50}")
            print(f"Course: {course_url}")

            try:
                await page.goto(course_url, wait_until="commit")
            except Exception:
                pass
            print("Waiting for quizzes page...")
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
            if start_from > 1:
                names = names[start_from - 1:]
                print(f"Found {total} quiz(es). Resuming from #{start_from}...")
            else:
                print(f"Found {total} quiz(es). Starting...")

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
                if settings.get("set_in_gradebook"):
                    await apply_gradebook(page, dry_run)
                if settings.get("set_auto_submit"):
                    await apply_auto_submit(page, dry_run)
                await save_quiz(page, dry_run)
                if pause_fn:
                    pause_fn()

        print(f"\n{'─' * 50}")
        print("✓  All done!")
        await browser.close()


async def run_assignments(urls: list[str], dry_run: bool, settings: dict, limit: int | None = None, pause_fn=None, start_from: int = 1):
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

        print("Opening Brightspace...")
        await page.goto("https://learn.okanagancollege.ca")
        print("─" * 50)
        print("  Log in with your Okanagan College account.")
        print("  Complete any MFA steps (email code, authenticator, etc.).")
        print("  The script will continue automatically once you are on")
        print("  the Brightspace home page.")
        print("─" * 50)

        for i in range(180):
            await page.wait_for_timeout(3000)
            url = page.url
            on_bs = "learn.okanagancollege.ca" in url
            on_ms = "microsoftonline.com" in url or "login.microsoft" in url
            on_login = "/d2l/lp/auth" in url or "/login" in url
            if on_bs and not on_ms and not on_login:
                break
            if i % 10 == 0 and i > 0:
                print(f"  Still waiting... ({i * 3}s)  |  {url[:80]}")
        else:
            raise RuntimeError("Login timed out after 9 minutes")

        print("✓ Logged in — saving session...")
        await page.wait_for_load_state("networkidle", timeout=20000)
        await context.storage_state(path=SESSION_FILE)
        print("✓ Session saved")

        for course_url in urls:
            print(f"\n{'─' * 50}")
            print(f"Course: {course_url}")

            try:
                await page.goto(course_url, wait_until="commit")
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
                print("✗ No assignments found — check the URL points to the Assignments list page.")
                continue

            total = len(names)
            if limit:
                names = names[:limit]
            if start_from > 1:
                names = names[start_from - 1:]
                print(f"Found {total} assignment(s). Resuming from #{start_from}...")
            else:
                print(f"Found {total} assignment(s). Starting...")

            for i, name in enumerate(names, start_from):
                print(f"\n[{i}/{total}]  [{name}]")
                try:
                    await page.goto(course_url, wait_until="commit")
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
        await browser.close()
