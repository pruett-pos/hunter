# Hunter

Hunter looks for discounted houses within 100 miles of West Plains, MO, in Missouri and Arkansas.
It checks foreclosures, sheriff and commissioner sales, tax sales, HUD/bank/USDA/VA-owned homes and
online auctions. It keeps deals priced at or under **50% of the estimated after-repair value (ARV)**
and emails a report every Monday, Wednesday and Friday morning.

## How it works

1. **Collect.** A headless browser opens each source in `config.yaml`. For the newspaper public-notice
   sites (mopublicnotices.com, arkansaspublicnotices.com) it searches the last 7 days of
   foreclosure, sheriff-sale and tax-sale notices in the target counties and opens every notice.
2. **Read.** Claude reads each page and pulls out properties: address, county, sale type, price or
   opening bid, sale date and details. Properties outside the 54 target counties are dropped.
3. **Value.** For each property Hunter hasn't seen before, Claude searches the web for recent nearby
   sales and estimates ARV and market rent (capped at `max_arv_per_run` per run to control cost).
4. **Filter.**
   - **Deal**: price or opening bid is at or below 50% of ARV.
   - **Watch**: a courthouse sale or auction with no published opening bid. The email shows the
     max bid (50% of ARV).
   - Everything else is recorded but not emailed.
5. **Report.** Results are added to `data/deals.csv` (full history, opens in Excel), committed back to
   the repo, and the new deals are emailed.

## Setup

Add these under **Settings > Secrets and variables > Actions > New repository secret**:

| Secret | What it is |
| --- | --- |
| `ANTHROPIC_API_KEY` | API key from console.anthropic.com |
| `SMTP_USER` | The Gmail / Google Workspace address that sends the email |
| `SMTP_PASSWORD` | A Google **app password** for that account (myaccount.google.com > Security > App passwords; needs 2-Step Verification) |

To run it right away: **Actions > Hunter run > Run workflow**.

## Tuning

Everything lives in `config.yaml`: the 50% rule (`max_price_to_arv`), the counties, the source URLs,
how far back to search notices, the Claude model and the per-run ARV cap.

## Costs

GitHub Actions is free for this usage. Claude reads pages and notices in batches, and runs one web-search
call per new property it values. With the default model (Claude Opus 5.5) and caps, expect about
$3-6 per run, or roughly $40-75 a month at three runs a week. Lower `max_arv_per_run` or
`max_notices_per_site` to spend less.

## Limits

- ARV is an AI estimate from comps found online. Check comps, condition and title before you bid.
- Missouri tax-sale parcels that go unsold (post-third offering) are sold by calling the county
  collector, so Hunter can't see them.
- Sites change their layout. Each run uploads the page text it read (Actions > run > Artifacts) and
  lists every source's status at the bottom of the email, so a broken source shows up quickly.

## Development

```
pip install -r requirements.txt pytest
python -m playwright install chromium
python -m pytest -q
python -m hunter.main --no-email      # needs ANTHROPIC_API_KEY
```
