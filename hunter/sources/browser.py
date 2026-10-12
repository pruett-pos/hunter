"""Headless browser helpers. Every source goes through here so pages render like they do for a person."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urljoin

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
MAX_TEXT = 120_000


@dataclass
class Page:
    url: str
    text: str
    links: list[tuple[str, str]] = field(default_factory=list)  # (text, absolute href)


@contextmanager
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path=os.environ.get("CHROMIUM_PATH") or None)
        ctx = b.new_context(user_agent=USER_AGENT, viewport={"width": 1400, "height": 1000})
        ctx.set_default_timeout(30_000)
        try:
            yield ctx
        finally:
            b.close()


def snapshot(page, url: str | None = None) -> Page:
    text = page.inner_text("body")[:MAX_TEXT]
    links = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => [e.innerText.trim(), e.getAttribute('href')])"
    )
    base = url or page.url
    return Page(url=page.url, text=text, links=[(t, urljoin(base, h)) for t, h in links if h])


def load(ctx, url: str, wait_ms: int = 2500, search_text: str | None = None) -> Page:
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded")
        if search_text:
            box = page.locator("input[type=search], input[type=text]").first
            box.fill(search_text, timeout=10_000)
            box.press("Enter")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        _scroll(page)
        return snapshot(page, url)
    finally:
        page.close()


def _scroll(page, steps: int = 6) -> None:
    """Scroll so lazy-loaded result lists render."""
    for _ in range(steps):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(400)
