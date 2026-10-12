"""Newspaper public-notice sites (mopublicnotices.com, arkansaspublicnotices.com).

Both run the same search software. The site's "Popular Searches" (Foreclosure,
Sheriff Sales, Tax Sale) return statewide results, newest first; each result row
names the paper's county and opens its full text via a "view" button whose
onclick points at Details.aspx. We keep rows from our counties (or whose snippet
names one), stop once results are older than the lookback, then open each notice
so Claude can read the full text. Keywords with no popular search fall back to
the advanced form.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from urllib.parse import urljoin

from .browser import Page, snapshot

log = logging.getLogger(__name__)

DETAIL_RE = re.compile(r"Details\.aspx\?", re.I)
# Snippets that read like a property sale; drops ballot measures, budgets etc. that match "sheriff" or "tax".
SALE_RE = re.compile(
    r"trustee|foreclos|deed of trust|mortgage|commissioner'?s sale|sheriff'?s sale|tax sale|"
    r"delinquent (land|tax|real)|land tax|real (estate|property)|judicial sale|public auction|lien sale", re.I)
JUNK_RE = re.compile(r"constitutional amendment|ballot|budget|election", re.I)
def describe_form(page) -> str:
    """Short list of the page's non-checkbox form controls, for the run log."""
    return page.eval_on_selector_all(
        "input, select, button, label, a[id]",
        "els => els.filter(e => !['hidden', 'checkbox'].includes(e.type) && !(e.tagName === 'LABEL' && e.control && e.control.type === 'checkbox'))"
        ".slice(0, 80).map(e => `${e.tagName}#${e.id || ''}[${e.type || ''}]` + "
        "`'${(e.innerText || e.value || '').replace(/\\s+/g, ' ').trim().slice(0, 30)}'`).join(' | ')",
    )


def search(ctx, url: str, keyword: str, counties: list[str], days: int,
           today: dt.date | None = None) -> list[str]:
    """Run one search; return detail-page URLs for notices from our counties."""
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        if not _popular_search(page, keyword):
            _fill_keyword(page, keyword)
            _tick_counties(page, counties)
            _set_days(page, days)
            _submit(page)
        _per_page(page, 50)
        cutoff = (today or dt.date.today()) - dt.timedelta(days=days)
        want = {c.lower() for c in counties}
        found: list[str] = []
        rows_seen = 0
        counties_seen: dict[str, int] = {}
        for n in range(1, 31):  # result pages
            rows = page.evaluate(ROWS_JS)
            if not rows:  # plain link list (older layout)
                found += [h for _, h in snapshot(page).links if DETAIL_RE.search(h)]
            rows_seen += len(rows)
            oldest = None
            for r in rows:
                counties_seen[r["county"]] = counties_seen.get(r["county"], 0) + 1
                d = _date(r["date"])
                if d:
                    oldest = d if oldest is None else min(oldest, d)
                if d and d < cutoff:
                    continue
                if _ours(r, want) and r["href"] and SALE_RE.search(r["text"]) and not JUNK_RE.search(r["text"]):
                    found.append(urljoin(page.url, r["href"]))
            if oldest and oldest < cutoff:
                break
            if not _next_page(page, n + 1):
                break
        top = sorted(counties_seen.items(), key=lambda kv: -kv[1])[:8]
        log.info("%s: %d result rows read, %d sale notices from our counties (papers by county: %s)",
                 keyword, rows_seen, len(found), top)
        return list(dict.fromkeys(found))
    finally:
        page.close()


ROWS_JS = """() => [...document.querySelectorAll('table.wsResultsGrid table.nested')].map(t => {
  const btn = t.querySelector('input.viewButton[onclick*="Details.aspx"], a[href*="Details.aspx"]');
  const m = btn && (btn.getAttribute('onclick') || btn.getAttribute('href') || '').match(/Details\\.aspx\\?[^'"]+/);
  const left = t.querySelector('div.left'), right = t.querySelector('div.right');
  const county = right ? (right.textContent.match(/County:\\s*([^\\n<]+)/) || [])[1] || '' : '';
  const date = left ? (left.textContent.match(/[A-Z][a-z]+ \\d{1,2}, \\d{4}/) || [''])[0] : '';
  return {href: m ? m[0].replace(/&amp;/g, '&') : '', county: county.trim(), date, text: t.textContent.replace(/\\s+/g, ' ')};
})"""


def _date(s: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(s, "%B %d, %Y").date()
    except ValueError:
        return None


def _ours(row: dict, want: set[str]) -> bool:
    from ..config import normalize_county
    if row["county"] and normalize_county(row["county"]).lower() in want:
        return True
    text = row["text"].lower()
    return any(f"{c} county" in text for c in want)


def _per_page(page, n: int) -> None:
    sel = page.locator("select[id*=PerPage i]")
    if not sel.count():
        return
    try:
        sel.first.select_option(str(n))
        page.wait_for_timeout(1000)
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception as e:
        log.info("per-page not set: %s", str(e).splitlines()[0][:120])


def read_notice(ctx, url: str) -> Page:
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        return snapshot(page, url)
    finally:
        page.close()


def _popular_search(page, keyword: str) -> bool:
    """Use the site's own "Popular Searches" entry when one matches (e.g. Foreclosure, Sheriff Sales).

    Picking one runs the site's saved search server-side, which is more reliable
    than driving the advanced form. County filtering then happens when Claude reads the notices.
    """
    dd = page.locator("select[id*=PopularSearches i]")
    if not dd.count():
        return False
    options = [o.strip() for o in dd.first.locator("option").all_inner_texts()]
    match = next((o for o in options if o.lower() == keyword.lower()), None)
    if not match:
        log.info("no popular search for %r; options: %s", keyword, options)
        return False
    dd.first.select_option(label=match)
    log.info("popular search: %s", match)
    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    return True


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
    btn = page.locator("[id*=btnGo i], [id*=btnSearch i]")
    clicked = None
    if btn.count():
        try:
            btn.first.click(timeout=5_000)
            clicked = "button (real click)"
        except Exception:
            pass
    clicked = clicked or page.evaluate(SUBMIT_JS)
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


def _next_page(page, number: int) -> bool:
    """Go to result page `number` via the grid pager; False when there is none."""
    before = page.evaluate(ROWS_JS)
    nxt = page.locator(
        f"table.wsResultsGrid a:text-is('{number}'), [id*=btnNext i], [id*=lnkNext i], "
        "input[title*=next i], a[title*=next i]")
    if not nxt.count():
        nxt = page.get_by_role("link", name=re.compile(r"^(Next|>|»)", re.I))
    if not nxt.count():
        if number == 2:
            log.info("no pager found: %s", page.evaluate(
                "() => [...document.querySelectorAll('[id*=Page i], [class*=pag i]')].slice(0, 12)"
                ".map(e => e.outerHTML.replace(/\\s+/g, ' ').slice(0, 300)).join(' | ')"))
        return False
    try:
        nxt.first.click(timeout=5_000)
        page.wait_for_timeout(1000)
        page.wait_for_load_state("networkidle", timeout=20_000)
        return page.evaluate(ROWS_JS) != before
    except Exception:
        return False
