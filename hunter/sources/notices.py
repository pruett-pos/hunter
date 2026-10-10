"""Newspaper public-notice sites (mopublicnotices.com, arkansaspublicnotices.com).

Both run the same search software: keyword box, county checkboxes, a
"in the last N days" range and a Search button. Results link to a detail
page per notice. We search each keyword with our counties ticked, then
open each notice so Claude can read the full text.
"""
from __future__ import annotations

import logging
import re

from .browser import Page, snapshot

log = logging.getLogger(__name__)

DETAIL_RE = re.compile(r"Details\.aspx\?", re.I)


def search(ctx, url: str, keyword: str, counties: list[str], days: int) -> list[str]:
    """Run one search; return detail-page URLs."""
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        _fill_keyword(page, keyword)
        _tick_counties(page, counties)
        _set_days(page, days)
        _submit(page)
        found: list[str] = []
        for _ in range(10):  # result pages
            snap = snapshot(page)
            found += [h for _, h in snap.links if DETAIL_RE.search(h)]
            if not _next_page(page):
                break
        return list(dict.fromkeys(found))
    finally:
        page.close()


def read_notice(ctx, url: str) -> Page:
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        return snapshot(page, url)
    finally:
        page.close()


def _fill_keyword(page, keyword: str) -> None:
    box = page.locator("input[type=text][id*='txtSearch'], input[type=text][id*='Keyword'], input[type=search]").first
    if not box.count():
        box = page.locator("input[type=text]").first
    box.fill(keyword)
    exact = page.get_by_label(re.compile("Exact Phrase", re.I))
    if exact.count():
        exact.first.check()


def _tick_counties(page, counties: list[str]) -> None:
    # Filter panels are often collapsed; open the County one if there is a toggle.
    toggle = page.get_by_text(re.compile(r"^\s*County\s*$", re.I))
    if toggle.count():
        try:
            toggle.first.click()
            page.wait_for_timeout(500)
        except Exception:
            pass
    ticked = 0
    for county in counties:
        box = page.get_by_label(re.compile(rf"^\s*{re.escape(county)}\s*$", re.I))
        if box.count():
            try:
                box.first.check()
                ticked += 1
            except Exception as e:  # hidden or detached
                log.debug("could not tick %s: %s", county, e)
    log.info("ticked %d/%d counties", ticked, len(counties))
    if ticked == 0:
        raise RuntimeError("no county checkboxes found; search form changed?")


def _set_days(page, days: int) -> None:
    radio = page.get_by_label(re.compile("In the last", re.I))
    if radio.count():
        radio.first.check()
    num = page.locator("input[type=text][id*='Days'], input[type=text][id*='LastNum']")
    if num.count():
        num.first.fill(str(days))


def _submit(page) -> None:
    btn = page.locator("input[type=submit][value*='Search' i], button:has-text('Search')").first
    btn.click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2500)


def _next_page(page) -> bool:
    nxt = page.get_by_role("link", name=re.compile(r"^(Next|>|»)", re.I))
    if not nxt.count():
        return False
    try:
        nxt.first.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)
        return True
    except Exception:
        return False
