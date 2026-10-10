from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    raw: dict
    counties: set[tuple[str, str]] = field(default_factory=set)

    @property
    def max_ratio(self) -> float:
        return float(self.raw["max_price_to_arv"])

    @property
    def claude(self) -> dict:
        return self.raw["claude"]

    @property
    def sources(self) -> list[dict]:
        return self.raw["sources"]

    def county_names(self, state: str | None = None) -> list[str]:
        return sorted(c for s, c in self.counties if state is None or s == state)

    def in_area(self, state: str | None, county: str | None) -> bool:
        if not state or not county:
            return False
        return (state.strip().upper(), normalize_county(county)) in self.counties


def normalize_county(name: str) -> str:
    n = name.strip()
    for suffix in (" County", " county", " Co.", " Co"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    n = n.replace("Saint ", "St. ")
    if n.startswith("St ") :
        n = "St. " + n[3:]
    return n.strip().title()


def load(path: Path | None = None) -> Config:
    raw = yaml.safe_load((path or ROOT / "config.yaml").read_text())
    counties = {(c["state"].upper(), normalize_county(c["county"])) for c in raw["counties"]}
    return Config(raw=raw, counties=counties)
