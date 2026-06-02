import os
from playwright.async_api import async_playwright

from config import QUIZZES_URL, SETTINGS
from navigation import get_quiz_names, open_quiz_edit
from actions import apply_gradebook, apply_auto_submit, save_quiz

SESSION_FILE = "session.json"


async def run(dry_run: bool, limit: int | None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=80)
        context = await browser.new_context(
            storage_state=SESSION_FILE if os.path.exists(SESSION_FILE) else None
        )
        page = await context.new_page()

        await page.goto(QUIZZES_URL)
        print("\n🔐  Log into Brightspace if prompted — script will continue automatically...\n")
        await page.wait_for_url("**/quizzing/**", timeout=120000)
        await page.wait_for_load_state("networkidle")
        print("✓ Quizzes page ready, taking over...")
        await context.storage_state(path=SESSION_FILE)

        if dry_run:
            print("\n⚠️  DRY RUN MODE — nothing will be saved\n")

        input("Press Enter to start scanning quizzes...")
        names = await get_quiz_names(page)

        if not names:
            print("\n✗ No quizzes found.")
            await browser.close()
            return

        if limit:
            names = names[:limit]

        print(f"\nFound {len(names)} quiz(es). Starting...\n{'─' * 50}")

        for i, name in enumerate(names, 1):
            print(f"\n[{i}/{len(names)}]  [{name}]")
            await page.goto(QUIZZES_URL)
            await page.wait_for_load_state("networkidle")
            await open_quiz_edit(page, name)
            if SETTINGS["set_in_gradebook"]:
                await apply_gradebook(page, dry_run)
            if SETTINGS["set_auto_submit"]:
                await apply_auto_submit(page, dry_run)
            await save_quiz(page, dry_run)

        print(f"\n{'─' * 50}")
        print(f"✓  Done. Processed {len(names)} quiz(es).")
        print("\n👉 Browser will stay open. Press Enter in the terminal to close it...")
        input()
        await browser.close()
