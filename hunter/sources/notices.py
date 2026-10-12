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
OPTIONAL_MS = 5_000


def _try(fn) -> None:
    """Run an optional form step; skip it if the control is missing or hidden."""
    try:
        fn()
    except Exception as e:
        log.info("optional step skipped: %s", str(e).splitlines()[0])


def describe_form(page) -> str:
    """Short list of the page's form controls, for the run log when a search fails."""
    return page.eval_on_selector_all(
        "input, select, button, label",
        "els => els.filter(e => e.type !== 'hidden').slice(0, 80).map(e => `${e.tagName}#${e.id || ''}[${e.type || ''}]` + "
        "`'${(e.innerText || e.value || '').replace(/\\s+/g, ' ').trim().slice(0, 30)}'`).join(' | ')",
    )


def search(ctx, url: str, keyword: str, counties: list[str], days: int) -> list[str]:
    """Run one search; return detail-page URLs."""
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        log.info("search form: %s", describe_form(page)[:1500])
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
    _try(lambda: page.get_by_label(re.compile("Exact Phrase", re.I)).first.check(timeout=OPTIONAL_MS, force=True))


TICK_JS = """(names) => {
  const want = new Set(names.map(n => n.toLowerCase()));
  const seen = []; let n = 0;
  for (const cb of document.querySelectorAll('input[type=checkbox]')) {
    let t = '';
    if (cb.id) { const l = document.querySelector(`label[for="${cb.id}"]`); if (l) t = l.textContent; }
    if (!t && cb.nextSibling) t = cb.nextSibling.textContent || '';
    if (!t && cb.parentElement) t = cb.parentElement.textContent || '';
    t = t.replace(/\\s+/g, ' ').trim().toLowerCase();
    seen.push(t);
    if (want.has(t)) { cb.checked = true; n++; }
  }
  return [n, seen.length, seen.slice(0, 15)];
}"""


def _tick_counties(page, counties: list[str]) -> None:
    # The county list sits in a collapsed panel, so set the boxes directly
    # instead of clicking them; the form posts checked boxes either way.
    ticked, total, sample = page.evaluate(TICK_JS, counties)
    log.info("ticked %d/%d counties (%d checkboxes on page, e.g. %s)", ticked, len(counties), total, sample)
    if ticked == 0:
        log.warning("form controls seen: %s", describe_form(page))
        raise RuntimeError("no county checkboxes found; search form changed?")


def _set_days(page, days: int) -> None:
    _try(lambda: page.get_by_label(re.compile("In the last", re.I)).first.check(timeout=OPTIONAL_MS, force=True))
    num = page.locator("input[type=text][id*='Days'], input[type=text][id*='LastNum']")
    if num.count():
        _try(lambda: num.first.fill(str(days), timeout=OPTIONAL_MS))


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
