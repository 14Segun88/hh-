from __future__ import annotations

import asyncio
import os
import random
import re
import subprocess
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

    def _get_dynamic_user_agent(self) -> str:
        """
        Dynamically construct a realistic User-Agent matching the current installed Chromium engine version.
        Prevents anti-bot fingerprinting discrepancies between User-Agent and internal browser features.
        """
        chrome_version = "132.0.0.0"
        try:
            exe = self._playwright.chromium.executable_path if self._playwright else None
            if exe and os.path.exists(exe):
                out = subprocess.check_output([exe, "--version"], timeout=2.0).decode().strip()
                match = re.search(r"(\d+\.\d+\.\d+\.\d+)", out)
                if match:
                    chrome_version = match.group(1)
                else:
                    major = re.search(r"(\d+)", out)
                    if major:
                        chrome_version = f"{major.group(1)}.0.0.0"
        except Exception:
            pass

        return (
            f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36"
        )

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

        dynamic_user_agent = self._get_dynamic_user_agent()

        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            viewport={"width": 1366, "height": 768},
            user_agent=dynamic_user_agent,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            args=args,
        )

        # Stealth: mask navigator.webdriver without tampering with native navigator.plugins
        await self.context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
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
