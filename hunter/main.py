"""Run Hunter: python -m hunter.main [--no-email] [--max-arv N]"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config as config_mod
from . import report
from .ai import Claude
from .collect import RawPage, collect
from .config import ROOT, Config, normalize_county
from .evaluate import classify, is_land
from .models import ArvEstimate, Deal, listing_id
from .store import Store

log = logging.getLogger("hunter")


def run(cfg: Config, store: Store, claude: Claude, pages: list[RawPage],
        status: dict[str, str], today: str, max_arv: int,
        max_land_arv: int = 5) -> tuple[list[Deal], dict[str, str]]:
    area = [f"{s}: {c}" for s, c in sorted(cfg.counties)]
    by_id: dict[str, Deal] = {}
    found: dict[str, int] = {}
    for rp in pages:
        try:
            listings = claude.extract(rp.page.text, rp.page.url, rp.deal_type, area)
        except Exception as e:
            log.exception("extract failed for %s", rp.page.url)
            status[f"read {rp.page.url}"] = f"FAILED: {e}"
            continue
        for l in listings:
            if l.county:
                l.county = normalize_county(l.county)
            l.url = l.url or rp.page.url
            if not cfg.in_area(l.state, l.county):
                continue
            did = listing_id(l)
            found[rp.source_id] = found.get(rp.source_id, 0) + 1
            if store.is_new(did) and did not in by_id:
                by_id[did] = Deal(id=did, source=rp.source_id, listing=l, first_seen=today)

    for sid, n in sorted(found.items()):
        status[f"{sid} in-area listings"] = str(n)

    # Value houses before land, so cheap tax parcels don't use up the per-run cap.
    valued = land_valued = 0
    for d in sorted(by_id.values(), key=lambda d: (is_land(d.listing), d.listing.price is None, d.listing.price or 0)):
        cached = store.cached_arv(d.id)
        if cached:
            d.arv = ArvEstimate.model_validate(cached)
        elif valued < max_arv and (not is_land(d.listing) or land_valued < max_land_arv):
            try:
                d.arv = claude.estimate_arv(d.listing)
            except Exception as e:
                log.warning("ARV failed for %s: %s", d.listing.address, e)
            valued += 1
            land_valued += is_land(d.listing)
        classify(d, cfg.max_ratio)
    pending = sum(1 for d in by_id.values() if d.arv is None)
    status["Summary"] = (f"{len(by_id)} new in-area properties, {valued} valued this run"
                         + (f", {pending} left for next run" if pending else ""))
    # Properties we couldn't value yet stay unseen so the next run retries them.
    return [d for d in by_id.values() if d.arv is not None], status


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--max-arv", type=int)
    ap.add_argument("--sources", help="comma-separated source ids to run (default: all)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = config_mod.load()
    if args.sources:
        keep = {x.strip() for x in args.sources.split(",") if x.strip()}
        cfg.raw["sources"] = [src for src in cfg.sources if src["id"] in keep]
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    store = Store(ROOT / "data")
    claude = Claude(cfg.claude)
    pages, status = collect(cfg, debug_dir=ROOT / "debug")
    deals, status = run(cfg, store, claude, pages, status, today,
                        args.max_arv if args.max_arv is not None else int(cfg.claude["max_arv_per_run"]),
                        int(cfg.claude.get("max_land_arv_per_run", 5)))
    store.add(deals)

    subject, body = report.build(deals, status, today,
                                 min_land_arv=float(cfg.raw.get("min_land_value", 10_000)),
                                 max_land=int(cfg.raw.get("max_land_in_email", 10)))
    (ROOT / "data" / "last_report.html").write_text(body)
    log.info("report: %s", subject)
    if not args.no_email and os.environ.get("SMTP_USER"):
        report.send(subject, body, cfg.raw["email"]["to"], cfg.raw["email"].get("subject_prefix", "Hunter deals"))
        log.info("emailed %s", cfg.raw["email"]["to"])


if __name__ == "__main__":
    main()
