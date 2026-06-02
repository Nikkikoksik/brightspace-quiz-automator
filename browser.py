import os
from playwright.async_api import async_playwright

from navigation import get_quiz_names, open_quiz_edit
from actions import apply_gradebook, apply_auto_submit, save_quiz

SESSION_FILE = "session.json"


async def run(urls: list[str], dry_run: bool, settings: dict, limit: int | None = None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None
        )
        page = await context.new_page()

        for course_url in urls:
            print(f"\n{'─' * 50}")
            print(f"Course: {course_url}")

            await page.goto(course_url)
            print("Waiting for quizzes page (log in if prompted)...")
            await page.wait_for_url("**/quizzing/**", timeout=120000)
            await page.wait_for_load_state("networkidle")
            await context.storage_state(path=SESSION_FILE)

            if dry_run:
                print("⚠  DRY RUN MODE — nothing will be saved")

            names = await get_quiz_names(page)
            if not names:
                print("✗ No quizzes found.")
                continue

            if limit:
                names = names[:limit]

            print(f"Found {len(names)} quiz(es). Starting...")

            for i, name in enumerate(names, 1):
                print(f"\n[{i}/{len(names)}]  [{name}]")
                await page.goto(course_url)
                await page.wait_for_load_state("networkidle")
                await open_quiz_edit(page, name)
                if settings.get("set_in_gradebook"):
                    await apply_gradebook(page, dry_run)
                if settings.get("set_auto_submit"):
                    await apply_auto_submit(page, dry_run)
                await save_quiz(page, dry_run)

        print(f"\n{'─' * 50}")
        print("✓  All done!")
        await browser.close()
