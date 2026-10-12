from hunter import config as config_mod
from hunter.collect import RawPage
from hunter.evaluate import classify
from hunter.main import run
from hunter.models import ArvEstimate, Deal, Listing, listing_id
from hunter import report
from hunter.sources.browser import Page
from hunter.store import Store


class FakeClaude:
    def __init__(self, listings, arv=100_000):
        self.listings, self.arv, self.arv_calls = listings, arv, 0

    def extract(self, text, url, hint, counties):
        return self.listings

    def estimate_arv(self, listing):
        self.arv_calls += 1
        return ArvEstimate(arv=self.arv, confidence="medium", comps=["1 Main St $98k 2026-05"], reasoning="x")


def L(**kw):
    base = dict(address="123 Elm St", city="West Plains", county="Howell County", state="MO",
                deal_type="reo_hud", price=40_000, price_kind="list")
    base.update(kw)
    return Listing(**base)


def page():
    return [RawPage("hud", "reo_hud", Page(url="https://x", text="..."))]


def test_county_normalization_and_area():
    cfg = config_mod.load()
    assert cfg.in_area("MO", "Howell County")
    assert cfg.in_area("AR", "Baxter")
    assert cfg.in_area("MO", "Saint Francois")
    assert not cfg.in_area("MO", "Jackson")   # Kansas City
    assert not cfg.in_area("AR", "Pulaski")   # Little Rock
    assert len(cfg.counties) == 54


def test_classify_rules():
    arv = ArvEstimate(arv=100_000, confidence="high", reasoning="x")
    d = classify(Deal(id="a", source="s", listing=L(price=50_000), arv=arv), 0.5)
    assert d.status == "deal" and d.max_offer == 50_000
    assert classify(Deal(id="b", source="s", listing=L(price=60_000), arv=arv), 0.5).status == "too_expensive"
    auction = L(deal_type="trustee_foreclosure", price=None)
    assert classify(Deal(id="c", source="s", listing=auction, arv=arv), 0.5).status == "watch"
    assert classify(Deal(id="d", source="s", listing=L(), arv=None), 0.5).status == "no_arv"


def test_run_filters_area_dedupes_and_caps(tmp_path):
    cfg = config_mod.load()
    store = Store(tmp_path)
    listings = [L(), L(), L(address="9 Far Rd", county="Jackson", city="Kansas City"),
                L(address="5 Oak", deal_type="sheriff_sale", price=None)]
    claude = FakeClaude(listings)
    status = {}
    deals, status = run(cfg, store, claude, page(), status, "2026-10-12", max_arv=1)
    assert claude.arv_calls == 1
    assert len(deals) == 1 and deals[0].status == "deal"
    assert "1 left for next run" in status["Summary"]
    store.add(deals)

    # Next run: the seen deal is skipped, the capped one is valued now.
    claude2 = FakeClaude(listings)
    deals2, _ = run(cfg, store, claude2, page(), {}, "2026-10-14", max_arv=5)
    assert [d.listing.address for d in deals2] == ["5 Oak"]
    assert deals2[0].status == "watch" and deals2[0].max_offer == 50_000


def test_store_roundtrip(tmp_path):
    s = Store(tmp_path)
    d = classify(Deal(id=listing_id(L()), source="hud", listing=L(), first_seen="2026-10-12",
                      arv=ArvEstimate(arv=90_000, confidence="low", reasoning="x")), 0.5)
    s.add([d])
    s2 = Store(tmp_path)
    assert not s2.is_new(d.id)
    assert s2.cached_arv(d.id)["arv"] == 90_000
    assert (tmp_path / "deals.csv").read_text().count("\n") == 2


def test_report_build():
    arv = ArvEstimate(arv=120_000, monthly_rent=950, confidence="medium", reasoning="x")
    deals = [classify(Deal(id="a", source="hud", listing=L(price=45_000), arv=arv), 0.5),
             classify(Deal(id="b", source="mo", listing=L(address="7 Pine", deal_type="tax_sale", price=None,
                                                          sale_date="2026-10-20"), arv=arv), 0.5)]
    subject, body = report.build(deals, {"HUD Home Store": "ok"}, "2026-10-12")
    assert subject.startswith("1 deal, 1 auction to watch")
    assert "123 Elm St" in body and "$60,000" in body and "7 Pine" in body


def test_land_goes_to_its_own_section():
    arv = ArvEstimate(arv=30_000, confidence="low", reasoning="x")
    tiny = ArvEstimate(arv=2_000, confidence="low", reasoning="x")
    land = classify(Deal(id="l", source="cosl", listing=L(deal_type="tax_sale", property_type="land", price=500), arv=arv), 0.5)
    scrap = classify(Deal(id="s", source="cosl", listing=L(address="Parcel 9", deal_type="tax_sale", property_type="vacant lot", price=74), arv=tiny), 0.5)
    home = classify(Deal(id="h", source="cosl", listing=L(address="8 Ash", property_type="mobile home on land", price=5000), arv=arv), 0.5)
    assert (land.status, scrap.status, home.status) == ("land_deal", "land_deal", "deal")
    subject, body = report.build([land, scrap, home], {}, "2026-10-14")
    assert subject.startswith("1 deal,") and "Land under 50% of value" in body
    assert "Parcel 9" not in body
