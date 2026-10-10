"""Running record of everything Hunter has seen, kept in data/ and committed back to the repo."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Deal

COLUMNS = [
    "first_seen", "status", "deal_type", "address", "city", "county", "state", "zip",
    "price", "price_kind", "arv", "arv_low", "arv_high", "max_offer", "price_to_arv",
    "monthly_rent", "arv_confidence", "sale_date", "property_type", "beds", "baths", "sqft",
    "source", "url", "notes", "comps", "id",
]


class Store:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.dir / "seen.json"
        self.csv_path = self.dir / "deals.csv"
        self.seen: dict[str, dict] = json.loads(self.seen_path.read_text()) if self.seen_path.exists() else {}

    def is_new(self, deal_id: str) -> bool:
        return deal_id not in self.seen

    def cached_arv(self, deal_id: str) -> dict | None:
        return self.seen.get(deal_id, {}).get("arv")

    def add(self, deals: list[Deal]) -> None:
        new_file = not self.csv_path.exists()
        with self.csv_path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            if new_file:
                w.writeheader()
            for d in deals:
                w.writerow(row(d))
                self.seen[d.id] = {
                    "first_seen": d.first_seen, "status": d.status,
                    "arv": d.arv.model_dump() if d.arv else None,
                }
        self.seen_path.write_text(json.dumps(self.seen, indent=1, sort_keys=True))


def row(d: Deal) -> dict:
    l, a = d.listing, d.arv
    ratio = round(l.price / a.arv, 2) if (a and a.arv and l.price) else None
    return {
        "first_seen": d.first_seen, "status": d.status, "deal_type": l.deal_type,
        "address": l.address, "city": l.city, "county": l.county, "state": l.state, "zip": l.zip,
        "price": l.price, "price_kind": l.price_kind,
        "arv": a.arv if a else None, "arv_low": a.arv_low if a else None, "arv_high": a.arv_high if a else None,
        "max_offer": d.max_offer, "price_to_arv": ratio,
        "monthly_rent": a.monthly_rent if a else None, "arv_confidence": a.confidence if a else None,
        "sale_date": l.sale_date, "property_type": l.property_type, "beds": l.beds, "baths": l.baths,
        "sqft": l.sqft, "source": d.source, "url": l.url, "notes": l.notes,
        "comps": " | ".join(a.comps) if a else None, "id": d.id,
    }
