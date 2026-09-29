from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import Frame, Page
from hh_agent.core.browser.harness import BrowserHarness


class NegotiationsBrowser:
    """Interacts with hh.ru chat threads, invitations, and negotiations (Magritte UI + chatik)."""

    def __init__(self, page: Page):
        self.page = page

    async def fetch_recent_negotiations(self) -> List[Dict[str, Any]]:
        """Navigate to applicant negotiations and gather conversation cards."""
        url = "https://hh.ru/applicant/negotiations"
        await self.page.goto(url, wait_until="domcontentloaded")
        await BrowserHarness.human_delay(1.5, 2.2)
        await BrowserHarness.smooth_scroll(self.page, distance=400)

        cards = await self.page.locator("div[data-qa='negotiations-item']").all()
        threads: List[Dict[str, Any]] = []

        for idx, card in enumerate(cards):
            card_text = await card.inner_text()
            vac_link = card.locator("a[href*='/vacancy/']").first
            vac_title = (await vac_link.inner_text()).strip() if await vac_link.is_visible() else "Вакансия"
            href = (await vac_link.get_attribute("href") or "") if await vac_link.is_visible() else ""
            m = re.search(r"/vacancy/(\d+)", href)
            hh_id = m.group(1) if m else f"topic_{idx + 1}"

            emp_link = card.locator("a[href*='/employer/']").first
            comp_name = (await emp_link.inner_text()).strip() if await emp_link.is_visible() else "Работодатель"

            # Parse status strictly from official hh.ru status badge (green for interview/invite)
            status = await self._extract_status_from_card(card)

            chat_btn = card.locator("button[data-qa='open_chat']").first
            has_chat = await chat_btn.is_visible()

            threads.append({
                "index": idx,
                "hh_id": hh_id,
                "hh_topic_id": hh_id,
                "company_name": comp_name,
                "vacancy_title": vac_title,
                "status": status,
                "has_chat": has_chat,
                "summary": card_text.replace("\n", " ")[:150],
            })

        return threads

    async def extract_funnel_metrics(
        self, click_tabs: bool = False, force_reload: bool = True
    ) -> Dict[str, int]:
        """
        Parse the status funnel counts across all tabs on https://hh.ru/applicant/negotiations:
        - Все
        - Собеседование (includes Приглашение + Собеседование)
        - Выход на работу
        - Ожидание
        - Отказ
        - Архив (includes Архив + Удалённые)
        """
        if force_reload or "applicant/negotiations" not in (self.page.url or ""):
            try:
                await self.page.goto("https://hh.ru/applicant/negotiations", wait_until="domcontentloaded")
                await BrowserHarness.human_delay(1.5, 2.0)
                await self.page.wait_for_selector('[role="tab"]', timeout=8000)
            except Exception:
                pass

        funnel = {
            "all_count": 0,
            "interview_count": 0,
            "job_offer_count": 0,
            "waiting_count": 0,
            "discard_count": 0,
            "archive_count": 0,
        }

        tabs = await self.page.locator('[role="tab"]').all()
        for t in tabs:
            lbl_loc = t.locator('[class*="tab-label"]')
            if await lbl_loc.count() > 0:
                lbl = (await lbl_loc.inner_text()).strip().lower()
            else:
                lbl = (await t.inner_text()).strip().lower()

            post_loc = t.locator('[data-qa="tab-postfix"]')
            count = 0
            if await post_loc.count() > 0:
                txt = (await post_loc.inner_text()).strip()
                digits = re.findall(r"\d+", txt)
                if digits:
                    count = int("".join(digits))

            if "все" in lbl:
                funnel["all_count"] = max(funnel["all_count"], count)
            elif "собеседован" in lbl or "приглаш" in lbl:
                funnel["interview_count"] += count
            elif "выход на" in lbl or "работу" in lbl:
                funnel["job_offer_count"] += count
            elif "ожидан" in lbl:
                funnel["waiting_count"] += count
            elif "отказ" in lbl:
                funnel["discard_count"] += count
            elif "архив" in lbl or "удалён" in lbl:
                funnel["archive_count"] += count

            if click_tabs:
                try:
                    await t.click()
                    await asyncio.sleep(0.4)
                except Exception:
                    pass

        if click_tabs and tabs:
            try:
                await tabs[0].click()
                await asyncio.sleep(0.4)
            except Exception:
                pass

        return funnel

    async def open_chat_frame(self, card_index: int) -> Optional[Frame]:
        """Click open_chat on card at given index and wait for chatik iframe."""
        cards = await self.page.locator("div[data-qa='negotiations-item']").all()
        if card_index >= len(cards):
            return None
        card = cards[card_index]
        btn = card.locator("button[data-qa='open_chat']").first
        if not await btn.is_visible():
            return None

        await btn.scroll_into_view_if_needed()
        await btn.click()
        await asyncio.sleep(2.0)

        # Find chatik frame
        for _ in range(12):
            for f in self.page.frames:
                if "chatik.hh.ru" in f.url:
                    return f
            await asyncio.sleep(0.5)
        return None

    async def read_chat_messages(self, chat_frame: Frame) -> List[Dict[str, str]]:
        """Read all individual message bubbles from the chatik frame."""
        bubbles = await chat_frame.locator("div[class*='message--']").all()
        messages: List[Dict[str, str]] = []
        for b in bubbles:
            cls = await b.get_attribute("class") or ""
            sender = "candidate" if "message_my" in cls else "employer"
            text = (await b.inner_text()).strip()
            if text:
                messages.append({"sender": sender, "text": text})
        return messages

    async def send_chat_reply(self, chat_frame: Frame, reply_text: str) -> bool:
        """Type reply in chatik frame textarea and click send button."""
        ta = chat_frame.locator("textarea[data-qa='text-input'], textarea").first
        if not await ta.is_visible(timeout=3000):
            return False

        await ta.click()
        await ta.fill(reply_text)
        await BrowserHarness.human_delay(0.8, 1.2)

        send_btn = chat_frame.locator("button[data-qa='chatik-do-send-message']").first
        if await send_btn.is_visible(timeout=2000):
            await send_btn.click()
            await BrowserHarness.human_delay(1.5, 2.5)
            return True
        else:
            # Fallback to Enter key
            await ta.press("Enter")
            await BrowserHarness.human_delay(1.5, 2.5)
            return True

    async def close_chat(self) -> None:
        """Dismiss active chatik widget."""
        try:
            for f in self.page.frames:
                if "chatik.hh.ru" in f.url:
                    back_btn = f.locator("button[data-qa='chatik-back-to-chats-button']").first
                    if await back_btn.is_visible(timeout=500):
                        await back_btn.click()
                        await asyncio.sleep(0.5)
                        break
        except Exception:
            pass
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _extract_status_from_card(self, card) -> str:
        """
        Extract status strictly from the official hh.ru status badge/tag.
        Green badge = СОБЕСЕДОВАНИЕ / ПРИГЛАШЕНИЕ.
        Red/gray badge = ОТКАЗ.
        Blue/yellow/gray = ПРОСМОТРЕН / НЕ ПРОСМОТРЕН.
        Never infer status merely from message snippets, chat text, or disclaimers.
        """
        # 1. Direct QA attribute checks on status tags
        if await card.locator("[data-qa*='negotiations-item-interview'], [data-qa*='tag-interview']").count() > 0:
            return "СОБЕСЕДОВАНИЕ"
        if await card.locator("[data-qa*='negotiations-item-invitation'], [data-qa*='tag-invitation']").count() > 0:
            return "ПРИГЛАШЕНИЕ"
        if await card.locator("[data-qa*='negotiations-item-discard'], [data-qa*='tag-discard'], [data-qa*='negotiations-item-rejected']").count() > 0:
            return "ОТКАЗ"
        if await card.locator("[data-qa*='negotiations-item-not-viewed'], [data-qa*='tag-not-viewed']").count() > 0:
            return "НЕ ПРОСМОТРЕН"
        if await card.locator("[data-qa*='negotiations-item-viewed'], [data-qa*='tag-viewed']").count() > 0:
            return "ПРОСМОТРЕН"

        # 2. Inspect specific tag / badge elements inside the card
        tag_locators = card.locator(
            "[data-qa*='negotiations-tag'], [data-qa*='negotiations-item-status'], "
            "[class*='tag--'], [class*='badge--'], [class*='status--'], [class*='magritte-tag']"
        )
        tag_count = await tag_locators.count()
        for i in range(tag_count):
            tag_el = tag_locators.nth(i)
            if not await tag_el.is_visible():
                continue
            text = (await tag_el.inner_text()).strip()
            text_lower = text.lower()

            if text_lower in ("собеседование", "собеседование назначено"):
                return "СОБЕСЕДОВАНИЕ"
            if text_lower in ("приглашение", "приглашение на собеседование"):
                return "ПРИГЛАШЕНИЕ"
            if text_lower in ("отказ", "отказано", "отклонено"):
                return "ОТКАЗ"
            if text_lower in ("не просмотрен", "не\xa0просмотрен"):
                return "НЕ ПРОСМОТРЕН"
            if text_lower in ("просмотрен",):
                return "ПРОСМОТРЕН"

        return "ОТКЛИК"

