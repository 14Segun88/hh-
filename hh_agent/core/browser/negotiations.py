from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import Page
from hh_agent.core.browser.harness import BrowserHarness


class NegotiationsBrowser:
    """Interacts with hh.ru chat threads, invitations, and negotiations."""

    def __init__(self, page: Page):
        self.page = page

    async def fetch_recent_negotiations(self) -> List[Dict[str, Any]]:
        """Navigate to applicant negotiations and gather conversation threads."""
        url = "https://hh.ru/applicant/negotiations"
        await self.page.goto(url, wait_until="domcontentloaded")
        await BrowserHarness.human_delay(1.5, 2.5)
        await BrowserHarness.smooth_scroll(self.page, distance=500)

        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")

        threads = []
        # Negotiation items are listed as cards or links with /applicant/negotiations?topicId=...
        cards = soup.find_all("div", {"data-qa": re.compile(r"negotiations-item")}) or \
                soup.find_all("a", href=re.compile(r"topicId=\d+"))

        seen_topics = set()
        for card in cards:
            href = card.get("href", "") or (card.find("a") and card.find("a").get("href", ""))
            match = re.search(r"topicId=(\d+)", href)
            if not match:
                continue
            topic_id = match.group(1)
            if topic_id in seen_topics:
                continue
            seen_topics.add(topic_id)

            company_tag = card.find(string=re.compile(r"ООО|АО|ИП|[А-ЯA-Z][a-zа-я]+"))
            company_name = company_tag.strip() if company_tag else "Работодатель"

            # Vacancy title
            title_tag = card.find(["h3", "span", "a"], {"data-qa": re.compile(r"vacancy|title")})
            vac_title = title_tag.get_text(strip=True) if title_tag else "Вакансия"

            # Last message snippet
            snippet_tag = card.find("div", class_=re.compile(r"message|snippet|preview"))
            last_message = snippet_tag.get_text(strip=True) if snippet_tag else ""

            # Check unread indicator
            is_unread = bool(card.find(class_=re.compile(r"unread|badge|dot")))

            threads.append({
                "hh_topic_id": topic_id,
                "company_name": company_name,
                "vacancy_title": vac_title,
                "last_message_text": last_message,
                "is_unread": is_unread,
                "topic_url": f"https://hh.ru/applicant/negotiations?topicId={topic_id}",
            })

        return threads

    async def read_full_chat_history(self, topic_id: str) -> List[Dict[str, str]]:
        """Open specific chat thread and extract message messages with sender info."""
        url = f"https://hh.ru/applicant/negotiations?topicId={topic_id}"
        await self.page.goto(url, wait_until="domcontentloaded")
        await BrowserHarness.human_delay(1.5, 2.0)

        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")

        messages = []
        msg_blocks = soup.find_all("div", class_=re.compile(r"chat-message|message-item"))
        for block in msg_blocks:
            is_employer = "employer" in str(block.get("class", [])).lower()
            text = block.get_text(separator="\n", strip=True)
            if text:
                messages.append({
                    "sender": "employer" if is_employer else "candidate",
                    "text": text,
                })
        return messages

    async def send_reply_message(self, topic_id: str, reply_text: str) -> bool:
        """Type and send a message inside an active negotiation topic."""
        url = f"https://hh.ru/applicant/negotiations?topicId={topic_id}"
        await self.page.goto(url, wait_until="domcontentloaded")
        await BrowserHarness.human_delay(1.5, 2.0)

        input_box = self.page.locator("textarea[data-qa='chat-input-textarea']").or_(
            self.page.locator("textarea")
        )
        if not await input_box.is_visible(timeout=3000):
            return False

        await input_box.click()
        await input_box.fill(reply_text)
        await BrowserHarness.human_delay(0.8, 1.5)

        send_btn = self.page.locator("button[data-qa='chat-submit-button']").or_(
            self.page.locator("button:has-text('Отправить')")
        )
        if await send_btn.is_visible(timeout=2000):
            await send_btn.click()
            await BrowserHarness.human_delay(1.5, 2.5)
            return True
        return False
