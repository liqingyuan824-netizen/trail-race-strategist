"""Headed-browser operator. It only navigates the normal public UI."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

from .selection import select_by_runner_id

FIND_URL = "https://itra.run/Runners/FindARunner"


async def acquire(name: str, runner_id: str, evidence_dir: Path) -> dict:
    """Search by name, expose candidates, select only an exact Runner ID, and capture profile.

    Stops on access controls. There are no retries, direct internal API calls,
    fingerprint changes, CAPTCHA handling, or guessed profile URLs.
    """
    evidence_dir.mkdir(parents=True, exist_ok=False)
    trace = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "query": {"runner_name": name, "runner_id": runner_id}, "candidates": []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge", headless=False)
        context = await browser.new_context(locale="en-US")
        page = await context.new_page()
        response = await page.goto(FIND_URL, wait_until="networkidle", timeout=60_000)
        if response and response.status in {401, 403, 429}:
            trace.update(status="blocked", blocker=f"http_{response.status}")
            await browser.close()
            return trace
        if await page.locator("text=/captcha|verify you are human|robot/i").count():
            trace.update(status="blocked", blocker="human_verification")
            await browser.close()
            return trace
        accept = page.locator("#cookie-banner button", has_text="Accept")
        if await accept.is_visible():
            await accept.click()
        box = page.locator("#runnername")
        await box.click()
        await box.press_sequentially(name, delay=120)
        await page.wait_for_timeout(8_000)
        cards = page.locator("article.runner-card")
        for index in range(await cards.count()):
            trace["candidates"].append(await cards.nth(index).evaluate("""el => {
              const d = window.ko && ko.dataFor(el); if (!d) return null;
              const out = {}; for (const k of ['RunnerId','FirstName','LastName','Nationality','Gender','AgeGroup','Pi','PiIndex']) {
                let v=d[k]; if (window.ko && ko.isObservable(v)) v=v(); if (v!==undefined) out[k]=v;
              } return out;
            }"""))
        selection_status, selected = select_by_runner_id(trace["candidates"], runner_id)
        matches = [(i, c) for i, c in enumerate(trace["candidates"]) if c is selected]
        if not trace["candidates"]:
            zero_results = await page.locator("text=/0 Runners Found/i").count()
            trace["status"] = "not_found" if zero_results else "page_changed"
            if not zero_results:
                trace["blocker"] = "candidate_dom_not_recognized"
        elif selection_status != "matched":
            trace["status"] = "needs_user_selection"
        else:
            old_pages = len(context.pages)
            await cards.nth(matches[0][0]).locator(".runner-header").click()
            await page.wait_for_timeout(3_000)
            profile = context.pages[-1] if len(context.pages) > old_pages else page
            nav = await profile.wait_for_load_state("networkidle", timeout=60_000)
            if await profile.locator("text=/captcha|verify you are human|robot/i").count():
                trace.update(status="blocked", blocker="human_verification")
            else:
                await profile.wait_for_timeout(4_000)
                (evidence_dir / "profile.html").write_text(await profile.content(), encoding="utf-8")
                (evidence_dir / "profile.txt").write_text(await profile.locator("body").inner_text(), encoding="utf-8")
                await profile.screenshot(path=evidence_dir / "profile.png", full_page=True)
                trace.update(status="profile_captured", profile_url=profile.url)
        (evidence_dir / "browser_trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        await browser.close()
    return trace


def run_acquire(name: str, runner_id: str, evidence_dir: Path) -> dict:
    return asyncio.run(acquire(name, runner_id, evidence_dir))
