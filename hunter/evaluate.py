"""Apply the 50%-of-ARV rule."""
from __future__ import annotations

from .models import Deal

LAND_WORDS = ("land", "lot", "acre", "vacant", "timber", "pasture")
AUCTION_TYPES = {"trustee_foreclosure", "sheriff_sale", "commissioner_sale", "tax_sale", "auction"}


def classify(deal: Deal, max_ratio: float) -> Deal:
    a, l = deal.arv, deal.listing
    if not a or not a.arv:
        deal.status = "no_arv"
        return deal
    deal.max_offer = round(a.arv * max_ratio, -2)
    if l.price and l.price > 0:
        if l.price > deal.max_offer:
            deal.status = "too_expensive"
        else:
            deal.status = "land_deal" if is_land(l) else "deal"
    elif l.deal_type in AUCTION_TYPES:
        # Courthouse/auction sale with no known opening bid: show the max bid to go to.
        deal.status = "watch"
    else:
        deal.status = "no_arv"
    return deal


def is_land(listing) -> bool:
    kind = (listing.property_type or "").lower()
    return any(w in kind for w in LAND_WORDS) and not any(w in kind for w in ("home", "house", "mobile"))
