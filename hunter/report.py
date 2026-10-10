"""Build and send the deal email."""
from __future__ import annotations

import html
import os
import smtplib
from email.message import EmailMessage

from .models import Deal

TYPE_LABEL = {
    "trustee_foreclosure": "Trustee foreclosure", "sheriff_sale": "Sheriff sale",
    "commissioner_sale": "Commissioner sale", "tax_sale": "Tax sale", "reo_hud": "HUD home",
    "reo_bank": "Bank-owned", "reo_usda": "USDA-owned", "reo_va": "VA-owned",
    "auction": "Online auction", "other": "Other",
}


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def money(v) -> str:
    return f"${v:,.0f}" if v else "?"


def _row(d: Deal) -> str:
    l, a = d.listing, d.arv
    where = ", ".join(x for x in [l.city, f"{l.county} Co." if l.county else None, l.state] if x)
    link = f'<a href="{html.escape(l.url)}">link</a>' if l.url else ""
    facts = " · ".join(x for x in [
        l.property_type, f"{l.beds:g} bd" if l.beds else None, f"{l.baths:g} ba" if l.baths else None,
        f"{l.sqft:,.0f} sqft" if l.sqft else None] if x)
    rent = f" · rent ~{money(a.monthly_rent)}/mo" if a and a.monthly_rent else ""
    pct = f" ({l.price / a.arv:.0%} of ARV)" if (l.price and a and a.arv) else ""
    return f"""<tr><td style="padding:8px;border-bottom:1px solid #ddd;vertical-align:top">
<b>{html.escape(l.address)}</b><br>{html.escape(where)}<br>
<span style="color:#555">{TYPE_LABEL.get(l.deal_type, l.deal_type)}{' · sale ' + html.escape(l.sale_date) if l.sale_date else ''}{' · ' + html.escape(facts) if facts else ''}</span></td>
<td style="padding:8px;border-bottom:1px solid #ddd;vertical-align:top;white-space:nowrap">
Price: <b>{money(l.price)}</b>{html.escape(pct)}<br>ARV: <b>{money(a.arv if a else None)}</b>
<span style="color:#777">({a.confidence if a else '-'})</span>{rent}<br>Max offer (50%): <b>{money(d.max_offer)}</b><br>{link}</td></tr>"""


def _table(title: str, deals: list[Deal], blurb: str) -> str:
    if not deals:
        return ""
    rows = "".join(_row(d) for d in deals)
    return f"<h3 style='margin:20px 0 4px'>{title} ({len(deals)})</h3><p style='margin:0 0 6px;color:#555'>{blurb}</p><table style='border-collapse:collapse;width:100%'>{rows}</table>"


def build(deals: list[Deal], source_status: dict[str, str], date: str) -> tuple[str, str]:
    good = sorted([d for d in deals if d.status == "deal"], key=lambda d: d.listing.price / d.arv.arv)
    watch = sorted([d for d in deals if d.status == "watch"], key=lambda d: d.listing.sale_date or "9999")
    subject = f"{_n(len(good), 'deal')}, {_n(len(watch), 'auction')} to watch ({date})"
    health = "".join(
        f"<li>{html.escape(k)}: {html.escape(v)}</li>" for k, v in sorted(source_status.items())
    )
    body = f"""<div style="font-family:Arial,sans-serif;font-size:14px;max-width:760px">
<h2 style="margin:0">Hunter report, {date}</h2>
<p>New properties within 100 miles of West Plains since the last run.</p>
{_table("Priced at or under 50% of ARV", good, "Asking price or opening bid is at or below half the estimated after-repair value.")}
{_table("Upcoming auctions to watch", watch, "No opening bid published. Don't bid above the max offer.")}
{'' if good or watch else '<p><b>No new deals this run.</b></p>'}
<p style="color:#777;font-size:12px">ARV is an AI estimate from recent nearby sales found online. Check comps and title before bidding.
Full history is in data/deals.csv in the hunter repo.</p>
<details><summary style="color:#777;font-size:12px">Sources checked</summary><ul style="color:#777;font-size:12px">{health}</ul></details>
</div>"""
    return subject, body


def send(subject: str, html_body: str, to: str, prefix: str = "Hunter deals") -> None:
    user = os.environ["SMTP_USER"]
    msg = EmailMessage()
    msg["Subject"] = f"{prefix}: {subject}"
    msg["From"] = os.environ.get("SMTP_FROM", user)
    msg["To"] = to
    msg.set_content("This report is HTML; open it in an email app that shows HTML.")
    msg.add_alternative(html_body, subtype="html")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port) as s:
        s.login(user, os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
