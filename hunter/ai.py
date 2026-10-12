"""Claude calls: read listings out of page text, and estimate ARV with web search."""
from __future__ import annotations

import json
import logging
import os
import re

import anthropic

from .models import ArvEstimate, Listing, ListingBatch

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
CHUNK_CHARS = 60_000

EXTRACT_SYSTEM = """You read real-estate web pages and legal notices and pull out properties for sale.
Return every property you find, but only residential or residential-usable land
(houses, mobile homes, multi-family, lots/acreage). Skip vehicles, equipment and
personal property. Return one entry per property or parcel; never group
several parcels into one entry. Use only facts on the page; leave a field null when the page
does not say. Counties must be the county name only (e.g. "Howell").
When the text holds several notices marked "=== NOTICE url: ... ===", set each
property's url to the url of the notice it came from."""

ARV_SYSTEM = """You are a residential real-estate analyst in the Missouri and Arkansas Ozarks.
Estimate the after-repair value (ARV): what the property would sell for in good,
updated condition today, based on recent nearby sales of similar homes.
Search the web for comparable sales (Zillow, Redfin, Realtor.com, county records).
Prefer sold comps within the last 12 months, same town or within a few miles,
similar beds/baths/sqft. For land, value it as land. If you cannot find a reasonable
basis, return arv null with confidence low. Be conservative."""


class Claude:
    def __init__(self, cfg: dict, client: anthropic.Anthropic | None = None):
        self.cfg = cfg
        self.client = client or anthropic.Anthropic(api_key=api_key_from_env())

    def _create(self, **kw):
        resp = self.client.beta.messages.create(
            model=self.cfg["model"],
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **kw,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined: {getattr(resp.stop_details, 'category', None)}")
        return resp

    def extract(self, page_text: str, url: str, hint_deal_type: str | None,
                counties: list[str]) -> list[Listing]:
        out: list[Listing] = []
        for start in range(0, max(len(page_text), 1), CHUNK_CHARS):
            chunk = page_text[start:start + CHUNK_CHARS]
            prompt = (
                f"Source URL: {url}\n"
                + (f"Most listings here are deal type: {hint_deal_type}\n" if hint_deal_type else "")
                + "Only return properties in these counties (state: county): "
                + "; ".join(counties)
                + "\nIf a listing gives a city but no county, fill in the county if you are sure.\n"
                + "\n<page>\n" + chunk + "\n</page>"
            )
            resp = self._create(
                max_tokens=16000,
                system=EXTRACT_SYSTEM,
                output_config={
                    "effort": self.cfg.get("extract_effort", "low"),
                    "format": {"type": "json_schema", "schema": _schema(ListingBatch)},
                },
                messages=[{"role": "user", "content": prompt}],
            )
            out += ListingBatch.model_validate_json(_text(resp)).listings
        return out

    def estimate_arv(self, listing: Listing) -> ArvEstimate:
        facts = listing.model_dump(exclude_none=True, exclude={"url", "notes"})
        messages = [{"role": "user", "content": "Estimate ARV for:\n" + json.dumps(facts, indent=1)}]
        tools = [{
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": int(self.cfg.get("max_web_searches_per_arv", 5)),
            "user_location": {"type": "approximate", "city": "West Plains", "region": "Missouri", "country": "US"},
        }]
        for _ in range(4):  # resume server-tool pauses
            resp = self._create(
                max_tokens=16000,
                system=ARV_SYSTEM,
                tools=tools,
                output_config={
                    "effort": self.cfg.get("arv_effort", "medium"),
                    "format": {"type": "json_schema", "schema": _schema(ArvEstimate)},
                },
                messages=messages,
            )
            if resp.stop_reason != "pause_turn":
                return ArvEstimate.model_validate_json(_text(resp))
            messages = messages[:1] + [{"role": "assistant", "content": resp.content}]
        raise RuntimeError("ARV search did not finish")


def api_key_from_env() -> str | None:
    """Read the key even if extra text (like a pasted curl example) came along with it."""
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    m = re.search(r"sk-ant-[A-Za-z0-9_\-]+", raw)
    if m and m.group(0) != raw.strip():
        log.warning("ANTHROPIC_API_KEY secret has extra text around the key; using just the key")
    return m.group(0) if m else (raw.strip() or None)


def _text(resp) -> str:
    texts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    if not texts:
        raise RuntimeError(f"no text in response (stop_reason={resp.stop_reason})")
    return texts[-1]


def _schema(model) -> dict:
    """Pydantic JSON schema tightened for structured outputs."""
    schema = model.model_json_schema()

    def fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}).keys())
            for k in ("title", "default"):
                node.pop(k, None)
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)
    fix(schema)
    return schema
