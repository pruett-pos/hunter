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
def describe_form(page) -> str:
    """Short list of the page's non-checkbox form controls, for the run log."""
    return page.eval_on_selector_all(
        "input, select, button, label, a[id]",
        "els => els.filter(e => !['hidden', 'checkbox'].includes(e.type) && !(e.tagName === 'LABEL' && e.control && e.control.type === 'checkbox'))"
        ".slice(0, 80).map(e => `${e.tagName}#${e.id || ''}[${e.type || ''}]` + "
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
        after = snapshot(page)
        log.info("after search: %s\n%s\nlinks: %s", page.url, after.text[:2000].replace("\n", " / "),
                 [h for _, h in after.links][:40])
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
    page.evaluate("""() => {
      const r = document.querySelector("input[type=radio][value=EXACT i], input[type=radio][value=exact i]");
      if (r) r.checked = true;
    }""")


TICK_JS = """(names) => {
  const want = new Set(names.map(n => n.toLowerCase()));
  const seen = []; let n = 0;
  let boxes = document.querySelectorAll('input[type=checkbox][id*=County i]');
  if (!boxes.length) boxes = document.querySelectorAll('input[type=checkbox]');
  for (const cb of boxes) {
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


DAYS_JS = """(days) => {
  // Pick the "In the last N days" option and fill in N.
  for (const lab of document.querySelectorAll('label')) {
    if (!/in the last/i.test(lab.textContent)) continue;
    const radio = lab.control || lab.querySelector('input[type=radio]') || lab.previousElementSibling;
    if (radio && radio.type === 'radio') radio.checked = true;
    let el = (radio || lab).nextElementSibling;
    for (let i = 0; el && i < 4; i++, el = el.nextElementSibling) {
      if (el.tagName === 'INPUT' && el.type === 'text') { el.value = String(days); return el.id || 'days box'; }
    }
  }
  const box = document.querySelector("input[type=text][id*=Days i], input[type=text][id*=LastNum i]");
  if (box) { box.value = String(days); return box.id; }
  return null;
}"""

SUBMIT_JS = """() => {
  const byId = document.querySelector("[id*=btnGo i], [id*=btnSearch i], [id*=lnkSearch i], [id*=btnSubmit i]");
  const isGo = e => /^(search|go|submit)$/i.test((e.value || e.textContent || '').trim());
  const el = byId || [...document.querySelectorAll("input[type=submit], input[type=button], input[type=image], button, a")].find(isGo);
  if (!el) return null;
  el.click();
  return `${el.tagName}#${el.id}`;
}"""


def _set_days(page, days: int) -> None:
    log.info("date range box: %s", page.evaluate(DAYS_JS, days))


def _submit(page) -> None:
    clicked = page.evaluate(SUBMIT_JS)
    if not clicked:
        log.warning("form controls seen: %s", describe_form(page))
        raise RuntimeError("no Search button found; search form changed?")
    log.info("clicked %s", clicked)
    # Results come back either as a full postback or an in-place update; wait for both.
    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass
    page.wait_for_timeout(1500)


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
