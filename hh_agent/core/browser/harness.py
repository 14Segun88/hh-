from __future__ import annotations

import asyncio
import os
import random
from pathlib import Path
from typing import Optional
from playwright.async_api import BrowserContext, Page, async_playwright
from hh_agent.config import settings


class BrowserHarness:
    """Manages persistent Playwright browser context with stealth properties and session storage."""

    def __init__(
        self,
        user_data_dir: Optional[Path] = None,
        headless: Optional[bool] = None,
    ):
        self.user_data_dir = str(user_data_dir or settings.browser_profile_dir)
        self.headless = settings.headless_browser if headless is None else headless
        self._playwright = None
        self.context: Optional[BrowserContext] = None

    async def __aenter__(self) -> BrowserHarness:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> BrowserContext:
        """Launch persistent browser context with stealth injections and user profile."""
        os.makedirs(self.user_data_dir, exist_ok=True)
        self._playwright = await async_playwright().start()

        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1366,768",
        ]

        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            args=args,
        )

        # Stealth: mask navigator.webdriver and add common browser properties
        await self.context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ru-RU', 'ru', 'en-US', 'en']
            });
            window.chrome = {
                runtime: {}
            };
            """
        )
        return self.context

    async def new_page(self) -> Page:
        """Create a new page with default stealth applied."""
        if not self.context:
            await self.start()
        page = await self.context.new_page()
        # Humanized default timeout
        page.set_default_timeout(25000)
        return page

    async def close(self) -> None:
        """Gracefully close browser and persistent context."""
        if self.context:
            await self.context.close()
            self.context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    @staticmethod
    async def human_delay(min_sec: float = 1.0, max_sec: float = 2.5) -> None:
        """Introduce randomized delay to emulate human reading/scrolling."""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    @staticmethod
    async def smooth_scroll(page: Page, distance: int = 400) -> None:
        """Simulate realistic human page scrolling."""
        steps = random.randint(4, 7)
        step_distance = distance // steps
        for _ in range(steps):
            await page.mouse.wheel(0, step_distance)
            await asyncio.sleep(random.uniform(0.05, 0.12))
