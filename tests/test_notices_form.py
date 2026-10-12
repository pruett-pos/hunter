"""Drives the notice-site form against a local copy shaped like the real one."""
import logging
import os
from pathlib import Path

import pytest

from hunter.sources import browser, notices

FIX = Path(__file__).parent / "fixtures" / "notices"


@pytest.mark.skipif(os.environ.get("SKIP_BROWSER") == "1", reason="no browser")
def test_search_form_flow(caplog):
    caplog.set_level(logging.INFO)
    with browser.browser() as ctx:
        urls = notices.search(ctx, (FIX / "Search.html").as_uri(), "trustee's sale", ["Howell", "Oregon"], 7)
    assert [u.split("/")[-1] for u in urls] == ["Details.aspx?SID=1&ID=10", "Details.aspx?SID=1&ID=11"]
    assert "ticked 2/2 counties" in caplog.text            # county boxes only, not the Howell city box
    assert "txtLastNumDays" in caplog.text                  # date range filled
    assert "btnGo" in caplog.text                           # link-style Search button clicked
