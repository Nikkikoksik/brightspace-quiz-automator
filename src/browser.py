import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

from navigation import get_quiz_names, open_quiz_edit, get_assignment_names, open_assignment_edit, discover_course_urls, set_per_page_200
from actions import apply_gradebook, apply_auto_submit, save_quiz, apply_assignment_gradebook, save_assignment, verify_quiz_settings, _read_timing_summary, apply_pdf_only_file_type, apply_rename_title

if os.name == "nt":
    _USERDATA_DIR = Path(os.environ["APPDATA"]) / "BrightspaceAutomator"
else:
    _USERDATA_DIR = Path.home() / ".local" / "share" / "BrightspaceAutomator"

SESSION_FILE  = str(_USERDATA_DIR / "session.json")
STATS_FILE    = str(_USERDATA_DIR / "timing_stats.json")
_BS_PROFILE   = str(Path(__file__).parent.parent / "bs_profile")


def _print_run_summary(results: list, kind: str = "item"):
    W = 54
    errors   = [r for r in results if r["failed"]]
    ok_times = [r["elapsed"] for r in results if not r["failed"]]
    print(f"\n{'─' * W}")
    print(f"  SUMMARY  ·  {len(results)} {kind}(s)")
    print(f"{'─' * W}")
    for r in results:
        status = "✗" if r["failed"] else "✓"
        name = r["name"] if len(r["name"]) <= 38 else r["name"][:37] + "…"
        note = "FAILED" if r["failed"] else f"{r['elapsed']:.1f}s"
        print(f"  {status}  {name:<39}{note}")
    print(f"{'─' * W}")
    parts = [f"Avg time : {sum(ok_times)/len(ok_times):.1f}s"] if ok_times else []
    parts.append(f"Errors : {len(errors)}" if errors else "All OK ✓")
    print("  " + "   ·   ".join(parts))
    print(f"{'─' * W}")


def _save_timing(course_url: str, quiz_name: str, elapsed_s: float):
    try:
        try:
            with open(STATS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = []
        data.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "course": course_url,
            "quiz": quiz_name,
            "seconds": round(elapsed_s, 1),
        })
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


async def _wait_for_login(page):
    """Navigate to Brightspace, wait for user login."""
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
    print("✓ Logged in")
    await page.wait_for_load_state("networkidle", timeout=20000)


async def run_bs_login():
    """Standalone: open Brightspace, wait for login. Used by Settings panel."""
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            _BS_PROFILE,
            headless=False,
            slow_mo=80,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = await context.new_page()
        await _wait_for_login(page)
        await context.close()


async def run(urls: list[str], dry_run: bool, settings: dict, limit: int | None = None, ask_fn=None, review_fn=None, rename_fn=None):
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            _BS_PROFILE,
            headless=False,
            slow_mo=80,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page)

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
            start_from, end_at = await loop.run_in_executor(None, ask_fn, total, "quiz") if ask_fn else (1, total)
            names = names[start_from - 1:end_at]
            if start_from > 1 or end_at < total:
                print(f"Processing #{start_from}–#{end_at} of {total} quiz(es)...")
            else:
                print(f"Found {total} quiz(es). Starting...")

            failed_timer = []
            results      = []
            for i, name in enumerate(names, start_from):
                print(f"\n[{i}/{total}]  [{name}]")
                t_start = time.time()
                quiz_failed = False
                try:
                    await page.goto(quiz_url, wait_until="commit")
                except Exception:
                    pass
                await page.wait_for_selector(
                    "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
                )
                await open_quiz_edit(page, name)
                if settings.get("rename_moodle_titles"):
                    await apply_rename_title(page, name, dry_run)
                if settings.get("set_in_gradebook"):
                    await apply_gradebook(page, dry_run)
                if settings.get("set_auto_submit"):
                    ok = await apply_auto_submit(page, dry_run)
                    if ok is False:
                        quiz_failed = True
                        failed_timer.append(f"[{i}/{total}] {name}")
                await save_quiz(page, dry_run)
                elapsed = time.time() - t_start
                results.append({"name": name, "elapsed": elapsed, "failed": quiz_failed})
                if not quiz_failed and not dry_run:
                    _save_timing(quiz_url, name, elapsed)
                    print(f"    Timing    : {elapsed:.1f}s")

            if failed_timer:
                print(f"\n{'─' * 50}")
                print(f"⚠  {len(failed_timer)} quiz(es) need manual timer fix:")
                for q in failed_timer:
                    print(f"   • {q}")

            if results:
                _print_run_summary(results, "quiz")

        print(f"\n{'─' * 50}")
        print("✓  All done!")
        if rename_fn:
            from staging_automator import maybe_rename_staged
            await maybe_rename_staged(page, rename_fn)
        if review_fn:
            review_fn()
        await context.close()


async def run_verify(urls: list[str]):
    """Read-only pass: open every quiz and report current gradebook + timer settings."""
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            _BS_PROFILE,
            headless=False,
            slow_mo=80,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page)

        for raw_url in urls:
            print(f"\n{'─' * 50}")
            print(f"Course: {raw_url}")

            found = await discover_course_urls(page, raw_url)
            quiz_url = found.get("quizzes")
            if not quiz_url:
                print("✗ Could not find Quizzes link on this course page.")
                continue

            try:
                await page.goto(quiz_url, wait_until="commit")
            except Exception:
                pass
            await page.wait_for_url("**/quizzing/**", timeout=60000)
            await page.wait_for_load_state("networkidle")

            names = await get_quiz_names(page)
            if not names:
                print("✗ No quizzes found.")
                continue

            total = len(names)
            print(f"  Found {total} quiz(es) — verifying settings (no changes will be made)...\n")

            all_ok = True
            for i, name in enumerate(names, 1):
                try:
                    await page.goto(quiz_url, wait_until="commit")
                except Exception:
                    pass
                await page.wait_for_selector(
                    "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
                )
                await open_quiz_edit(page, name)
                status = await verify_quiz_settings(page)

                gb  = "✓" if status["gradebook"]  else ("✗ NOT SET" if status["gradebook"]  is False else "—")
                tmr = "✓" if status["auto_submit"] else ("✗ NOT SET" if status["auto_submit"] is False else "— no timer")
                ok  = status["gradebook"] is not False and status["auto_submit"] is not False
                if not ok:
                    all_ok = False
                flag = "" if ok else "  ← needs attention"
                print(f"  [{i}/{total}]  {name}")
                print(f"           Gradebook: {gb}   Timer auto-submit: {tmr}{flag}")

            print(f"\n{'─' * 50}")
            print("✓ Verify complete —", "all settings OK" if all_ok else "some quizzes need attention (see above)")

        await context.close()


async def run_timer_fix(urls: list[str], dry_run: bool, ask_fn=None, limit: int | None = None):
    """Re-run only the auto-submit timer fix on quizzes (no gradebook)."""
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            _BS_PROFILE,
            headless=False,
            slow_mo=80,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page)

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
            if limit:
                names = names[:limit]
            loop = asyncio.get_running_loop()
            start_from, end_at = await loop.run_in_executor(None, ask_fn, total, "quiz") if ask_fn else (1, total)
            names = names[start_from - 1:end_at]
            if start_from > 1 or end_at < total:
                print(f"Processing #{start_from}–#{end_at} of {total} quiz(es)...")
            else:
                print(f"Found {total} quiz(es). Starting timer fix...")

            failed_timer = []
            for i, name in enumerate(names, start_from):
                print(f"\n[{i}/{total}]  [{name}]")
                t_start = time.time()
                quiz_failed = False
                try:
                    await page.goto(course_url, wait_until="commit")
                except Exception:
                    pass
                await page.wait_for_selector(
                    "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
                )
                await open_quiz_edit(page, name)
                ok = await apply_auto_submit(page, dry_run)
                if ok is False:
                    quiz_failed = True
                    failed_timer.append(f"[{i}/{total}] {name}")
                await save_quiz(page, dry_run)
                elapsed = time.time() - t_start
                if not quiz_failed and not dry_run:
                    _save_timing(course_url, name, elapsed)
                    print(f"    Timing    : {elapsed:.1f}s")

            if failed_timer:
                print(f"\n{'─' * 50}")
                print(f"⚠  {len(failed_timer)} quiz(es) need manual timer fix:")
                for q in failed_timer:
                    print(f"   • {q}")

        print(f"\n{'─' * 50}")
        print("✓  All done!")
        await context.close()


async def run_assignments(urls: list[str], dry_run: bool, settings: dict, limit: int | None = None, ask_fn=None, review_fn=None, rename_fn=None):
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            _BS_PROFILE,
            headless=False,
            slow_mo=80,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page)

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
            try:
                await page.wait_for_selector(
                    "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=8000
                )
            except Exception:
                print("  Course has no assignments — skipping.")
                continue

            if dry_run:
                print("⚠  DRY RUN MODE — nothing will be saved")

            await set_per_page_200(page)
            names = await get_assignment_names(page)
            if not names:
                print("  Course has no assignments — skipping.")
                continue

            total = len(names)
            if limit:
                names = names[:limit]
            loop = asyncio.get_running_loop()
            start_from, end_at = await loop.run_in_executor(None, ask_fn, total, "assignment") if ask_fn else (1, total)
            names = names[start_from - 1:end_at]
            if start_from > 1 or end_at < total:
                print(f"Processing #{start_from}–#{end_at} of {total} assignment(s)...")
            else:
                print(f"Found {total} assignment(s). Starting...")

            results = []
            for i, name in enumerate(names, start_from):
                print(f"\n[{i}/{total}]  [{name}]")
                t_start = time.time()
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
                await apply_pdf_only_file_type(page, dry_run)
                await save_assignment(page, dry_run)
                elapsed = time.time() - t_start
                results.append({"name": name, "elapsed": elapsed, "failed": False})
                print(f"    Timing    : {elapsed:.1f}s")

            if results:
                _print_run_summary(results, "assignment")

        print(f"\n{'─' * 50}")
        print("✓  All done!")
        if rename_fn:
            from staging_automator import maybe_rename_staged
            await maybe_rename_staged(page, rename_fn)
        if review_fn:
            review_fn()
        await context.close()
