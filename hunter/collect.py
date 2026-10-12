"""Load every configured source and return raw pages for Claude to read."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .sources import browser, notices

log = logging.getLogger(__name__)

@dataclass
class RawPage:
    source_id: str
    deal_type: str | None
    page: browser.Page


def collect(cfg: Config, debug_dir: Path | None = None) -> tuple[list[RawPage], dict[str, str], list[dict]]:
    """Pages for Claude to read, per-source status, and public-notice leads."""
    pages: list[RawPage] = []
    status: dict[str, str] = {}
    leads: list[dict] = []
    with browser.browser() as ctx:
        for src in cfg.sources:
            if src.get("enabled", True) is False:
                continue
            sid = src["id"]
            try:
                if src["kind"] == "notices":
                    got = _notices(ctx, cfg, src)
                    leads += got
                    status[src["name"]] = f"ok, {len(got)} notice(s) from our counties"
                else:
                    got = _pages(ctx, src)
                    pages += got
                    status[src["name"]] = f"ok, {len(got)} page(s) read"
            except Exception as e:
                log.exception("source %s failed", sid)
                status[src["name"]] = f"FAILED: {type(e).__name__}: {str(e)[:150]}"
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        for i, rp in enumerate(pages):
            (debug_dir / f"{i:03d}-{rp.source_id}.txt").write_text(f"{rp.page.url}\n\n{rp.page.text}")
    return pages, status, leads


def _pages(ctx, src: dict) -> list[RawPage]:
    out, errors = [], []
    for url in src["urls"]:
        try:
            page = browser.load(ctx, url, search_text=src.get("search_text"))
            if len(page.text.strip()) < 200:
                raise RuntimeError("page looked empty")
            log.info("%s %s -> %s\n%s", src["id"], url, page.url, page.text[:800])
            out.append(RawPage(src["id"], src.get("deal_type"), page))
        except Exception as e:
            errors.append(f"{url}: {str(e).splitlines()[0][:120]}")
    if not out:
        raise RuntimeError("; ".join(errors))
    return out


def _notices(ctx, cfg: Config, src: dict) -> list[dict]:
    counties = cfg.county_names(src["state"])
    days = int(cfg.raw.get("notice_lookback_days", 7))
    limit = int(cfg.raw.get("max_notices_per_site", 60))
    leads: list[dict] = []
    for kw in src["keywords"]:
        leads += notices.search(ctx, src["url"], kw, counties, days)
    leads = list({l["id"]: {**l, "state": src["state"], "source": src["id"]} for l in leads}.values())[:limit]
    log.info("%s: %d notices", src["id"], len(leads))
    return leads
