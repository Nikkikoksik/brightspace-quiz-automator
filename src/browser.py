import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

from navigation import get_quiz_names, open_quiz_edit, get_assignment_names, open_assignment_edit, discover_course_urls, set_per_page_200, harvest_quiz_edit_urls
from actions import apply_gradebook, apply_auto_submit, save_quiz, apply_assignment_gradebook, save_assignment, verify_quiz_settings, _read_timing_summary, apply_pdf_only_file_type, apply_rename_title, read_quiz_before_state, revert_gradebook, revert_auto_submit

if os.name == "nt":
    _USERDATA_DIR = Path(os.environ["APPDATA"]) / "BrightspaceAutomator"
else:
    _USERDATA_DIR = Path.home() / ".local" / "share" / "BrightspaceAutomator"
_USERDATA_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE       = str(_USERDATA_DIR / "session.json")
STATS_FILE         = str(_USERDATA_DIR / "timing_stats.json")
UNDO_SNAPSHOT_FILE = str(_USERDATA_DIR / "undo_snapshot.json")
_BS_PROFILE  = str(Path(__file__).parent.parent / "bs_profile")
_OUTLINE_CFG = _USERDATA_DIR / "outline_config.json"
WORKER_COUNT = 1


def _load_bs_credentials():
    try:
        with open(_OUTLINE_CFG) as f:
            cfg = json.load(f)
        return cfg.get("bs_username", ""), cfg.get("bs_password", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return "", ""


def _print_run_summary(results: list, kind: str = "item", wall_time: float | None = None):
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
    parts = []
    if ok_times:
        parts.append(f"Avg : {sum(ok_times)/len(ok_times):.1f}s")
    if wall_time is not None:
        parts.append(f"Total : {wall_time:.0f}s")
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


async def _quiz_worker(context, queue, results, failed_timer, snapshot, lock, settings, dry_run, quiz_url, worker_id):
    page = await context.new_page()
    try:
        while True:
            try:
                idx, name, edit_url = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            print(f"\n  [{idx}] {name}")
            t_start = time.time()
            quiz_failed = False
            try:
                if edit_url:
                    # Fast path: direct navigation to edit page
                    await page.goto(edit_url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_selector(
                            "button.d2l-grade-info, button.d2l-collapsible-panel-opener",
                            timeout=15000,
                        )
                    except Exception:
                        pass
                else:
                    # Fallback: navigate to quiz list and use action menu
                    try:
                        await page.goto(quiz_url, wait_until="commit")
                    except Exception:
                        pass
                    await page.wait_for_selector(
                        "button[aria-haspopup='true'][aria-label*='Actions for']", timeout=30000
                    )
                    await open_quiz_edit(page, name)

                before = await read_quiz_before_state(page)
                timer_out: dict = {}
                gb_changed = None
                timer_changed = None
                if settings.get("rename_moodle_titles"):
                    await apply_rename_title(page, name, dry_run)
                if settings.get("set_in_gradebook"):
                    gb_changed = await apply_gradebook(page, dry_run)
                if settings.get("set_auto_submit"):
                    ok = await apply_auto_submit(page, dry_run, out=timer_out)
                    timer_changed = ok
                    if ok is False:
                        quiz_failed = True
                        async with lock:
                            failed_timer.append(f"[{idx}] {name}")
                if not dry_run and (gb_changed is True or timer_changed is True):
                    async with lock:
                        snapshot.append({
                            "name": name,
                            "edit_url": edit_url or "",
                            "before_gradebook": before["gradebook"],
                            "before_timer_value": timer_out.get("timer_value"),
                        })
                await save_quiz(page, dry_run)
            except Exception as e:
                quiz_failed = True
                print(f"    ✗ worker {worker_id} failed on '{name}': {e}")
                async with lock:
                    failed_timer.append(f"[{idx}] {name}")
            elapsed = time.time() - t_start
            async with lock:
                results.append({"name": name, "elapsed": elapsed, "failed": quiz_failed})
            if not quiz_failed and not dry_run:
                _save_timing(quiz_url, name, elapsed)
            print(f"  [{idx}] {'✓' if not quiz_failed else '✗'}  {elapsed:.1f}s")
    finally:
        await page.close()


async def _wait_for_login(page, context):
    """Navigate to Brightspace, auto-login if credentials saved, then save session."""
    print("Opening Brightspace...")
    await page.goto("https://learn.okanagancollege.ca")
    await page.wait_for_load_state("domcontentloaded", timeout=15000)

    bs_user, bs_pass = _load_bs_credentials()
    has_login_form = bool(await page.locator("input[name='userName']").count() or await page.locator("text=Manual Login").count())
    if bs_user and bs_pass and has_login_form:
        try:
            print("  Auto-login: expanding Manual Login form...")
            await page.locator("text=Manual Login").click()
            await page.wait_for_timeout(800)
            await page.locator("input[name='userName']").fill(bs_user)
            await page.locator("input[name='password']").fill(bs_pass)
            await page.locator("button:has-text('Log In')").click()
            print("  Credentials submitted — waiting for redirect...")
        except Exception as e:
            print(f"  Auto-login failed ({e}) — please log in manually in the browser")
    else:
        if not bs_user:
            print("─" * 50)
            print("  No credentials saved. Log in manually in the browser.")
            print("  Save credentials in Settings to enable auto-login.")
            print("─" * 50)

    for i in range(180):
        await page.wait_for_timeout(3000)
        url = page.url
        if "learn.okanagancollege.ca" in url and "/d2l/login" not in url and "microsoftonline.com" not in url:
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

            args=["--start-maximized"],
            no_viewport=True,
        )
        page = await context.new_page()
        await _wait_for_login(page, context)
        await context.close()


async def run(urls: list[str], dry_run: bool, settings: dict, limit: int | None = None, ask_fn=None, review_fn=None, rename_fn=None):
    snapshot: list = []
    if not dry_run:
        try:
            with open(UNDO_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            _BS_PROFILE,
            headless=False,

            args=["--start-maximized"],
            no_viewport=True,
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
            await page.wait_for_load_state("domcontentloaded")

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

            worker_count = max(1, min(3, int(settings.get("worker_count", 1))))
            pairs = await harvest_quiz_edit_urls(page, quiz_url)
            if pairs:
                print(f"  Harvest: {len(pairs)} edit URLs — using {worker_count} worker(s)")
                pairs = pairs[start_from - 1:end_at]
            else:
                print(f"  Harvest: no direct URLs found — {worker_count} worker(s) will use action menu")
                pairs = [(n, None) for n in names]

            queue: asyncio.Queue = asyncio.Queue()
            for idx, (qname, edit_url) in enumerate(pairs, start_from):
                await queue.put((idx, qname, edit_url))
            lock = asyncio.Lock()
            t_wall = time.time()
            await asyncio.gather(*[
                _quiz_worker(context, queue, results, failed_timer, snapshot, lock,
                             settings, dry_run, quiz_url, w)
                for w in range(1, worker_count + 1)
            ])
            wall_time = time.time() - t_wall

            if failed_timer:
                print(f"\n{'─' * 50}")
                print(f"⚠  {len(failed_timer)} quiz(es) need manual timer fix:")
                for q in failed_timer:
                    print(f"   • {q}")

            if results:
                _print_run_summary(results, "quiz", wall_time)

        if snapshot and not dry_run:
            try:
                with open(UNDO_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, indent=2)
                print(f"  Undo snapshot: {len(snapshot)} quiz change(s) saved to undo_snapshot.json")
            except Exception:
                pass
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

            args=["--start-maximized"],
            no_viewport=True,
        )
        page = await context.new_page()

        await _wait_for_login(page, context)

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
            await page.wait_for_load_state("domcontentloaded")

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

            args=["--start-maximized"],
            no_viewport=True,
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
            await page.wait_for_load_state("domcontentloaded")

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

            args=["--start-maximized"],
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


async def run_undo(snapshot_path: str):
    """Revert all quiz changes recorded in the undo snapshot."""
    try:
        with open(snapshot_path, encoding="utf-8") as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("✗ No undo snapshot found or file is invalid.")
        return

    if not entries:
        print("✓ Snapshot is empty — nothing to undo.")
        return

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            _BS_PROFILE,
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
        )
        page = await context.new_page()
        await _wait_for_login(page, context)

        print(f"\n{'─' * 50}")
        print(f"Undoing {len(entries)} quiz change(s)...")

        for i, entry in enumerate(entries, 1):
            name              = entry.get("name", f"Quiz {i}")
            edit_url          = entry.get("edit_url", "")
            before_gradebook  = entry.get("before_gradebook")
            before_timer      = entry.get("before_timer_value")

            print(f"\n[{i}/{len(entries)}]  [{name}]")
            if not edit_url:
                print("    ⚠ no edit_url in snapshot — skipping")
                continue
            try:
                await page.goto(edit_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_selector(
                        "button.d2l-grade-info, button.d2l-collapsible-panel-opener",
                        timeout=15000,
                    )
                except Exception:
                    pass
                if before_gradebook is False:
                    await revert_gradebook(page)
                if before_timer is not None:
                    await revert_auto_submit(page, before_timer)
                await save_quiz(page, dry_run=False)
            except Exception as e:
                print(f"    ✗ {e}")

        print(f"\n{'─' * 50}")
        print("✓ Undo complete!")
        await context.close()
