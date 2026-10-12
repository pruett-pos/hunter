from __future__ import annotations

import hashlib
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

DealType = Literal[
    "trustee_foreclosure", "sheriff_sale", "commissioner_sale", "tax_sale",
    "reo_hud", "reo_bank", "reo_usda", "reo_va", "auction", "other",
]


class Listing(BaseModel):
    """One property pulled from a source page."""
    address: str = Field(description="Street address, or legal description if no street address")
    city: Optional[str] = None
    county: Optional[str] = Field(None, description="County name without the word County")
    state: Optional[Literal["MO", "AR"]] = None
    zip: Optional[str] = None
    deal_type: DealType
    price: Optional[float] = Field(None, description="List price, opening bid, minimum bid or amount owed, in dollars")
    price_kind: Optional[str] = Field(None, description="What price means: list, opening_bid, minimum_bid, amount_owed, judgment")
    sale_date: Optional[str] = Field(None, description="Sale or auction date as YYYY-MM-DD if known")
    property_type: Optional[str] = Field(None, description="e.g. single family, land, mobile home, multi-family")
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[float] = None
    url: Optional[str] = None
    notes: Optional[str] = Field(None, description="One short line of anything an investor should know")


class ListingBatch(BaseModel):
    listings: list[Listing]


class ArvEstimate(BaseModel):
    arv: Optional[float] = Field(None, description="Estimated after-repair value in dollars; null if no basis")
    arv_low: Optional[float] = None
    arv_high: Optional[float] = None
    monthly_rent: Optional[float] = Field(None, description="Estimated market rent after repair")
    confidence: Literal["low", "medium", "high"]
    comps: list[str] = Field(default_factory=list, description="Up to 5 comps: address, sale price, date, sqft")
    reasoning: str = Field(description="Two sentences max")


class Deal(BaseModel):
    """A listing after ARV and filtering."""
    id: str
    source: str
    listing: Listing
    arv: Optional[ArvEstimate] = None
    status: Literal["deal", "land_deal", "watch", "too_expensive", "no_arv", "out_of_area"] = "no_arv"
    max_offer: Optional[float] = None
    first_seen: str = ""


def listing_id(listing: Listing) -> str:
    addr = re.sub(r"[^a-z0-9]", "", (listing.address or "").lower())
    key = f"{addr}|{(listing.city or '').lower()}|{listing.state or ''}|{listing.deal_type}|{listing.sale_date or ''}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]
