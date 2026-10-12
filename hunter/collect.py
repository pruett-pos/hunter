"""Load every configured source and return raw pages for Claude to read."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .sources import browser, notices

log = logging.getLogger(__name__)

NOTICE_BATCH_CHARS = 45_000


@dataclass
class RawPage:
    source_id: str
    deal_type: str | None
    page: browser.Page


def collect(cfg: Config, debug_dir: Path | None = None) -> tuple[list[RawPage], dict[str, str]]:
    pages: list[RawPage] = []
    status: dict[str, str] = {}
    with browser.browser() as ctx:
        for src in cfg.sources:
            if src.get("enabled", True) is False:
                continue
            sid = src["id"]
            try:
                got = _notices(ctx, cfg, src) if src["kind"] == "notices" else _pages(ctx, src)
                pages += got
                status[src["name"]] = f"ok, {len(got)} page(s) read"
            except Exception as e:
                log.exception("source %s failed", sid)
                status[src["name"]] = f"FAILED: {type(e).__name__}: {str(e)[:150]}"
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        for i, rp in enumerate(pages):
            (debug_dir / f"{i:03d}-{rp.source_id}.txt").write_text(f"{rp.page.url}\n\n{rp.page.text}")
    return pages, status


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


def _notices(ctx, cfg: Config, src: dict) -> list[RawPage]:
    counties = cfg.county_names(src["state"])
    days = int(cfg.raw.get("notice_lookback_days", 7))
    limit = int(cfg.raw.get("max_notices_per_site", 60))
    urls: list[str] = []
    for kw in src["keywords"]:
        urls += notices.search(ctx, src["url"], kw, counties, days)
    urls = list(dict.fromkeys(urls))[:limit]
    log.info("%s: %d notices", src["id"], len(urls))
    # Group notices into batches so Claude reads ~15 per call instead of one each.
    out: list[RawPage] = []
    batch: list[str] = []
    for u in urls:
        page = notices.read_notice(ctx, u)
        text = re.sub(r"\n{3,}", "\n\n", page.text)
        batch.append(f"=== NOTICE url: {u} ===\n{text}")
        if sum(len(b) for b in batch) > NOTICE_BATCH_CHARS:
            out.append(_batch_page(src, batch))
            batch = []
    if batch:
        out.append(_batch_page(src, batch))
    return out


def _batch_page(src: dict, batch: list[str]) -> RawPage:
    return RawPage(src["id"], None, browser.Page(url=src["url"], text="\n\n".join(batch)))
