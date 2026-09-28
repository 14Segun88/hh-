from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import Page
from hh_agent.core.browser.harness import BrowserHarness


class VacancyApplicant:
    """Manages application execution, cover letter submission, and questionnaire handling on hh.ru."""

    def __init__(self, page: Page):
        self.page = page

    async def apply_to_vacancy(
        self,
        vacancy_url: str,
        cover_letter: Optional[str] = None,
        answers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute application flow:
        - Click apply button
        - Insert customized cover letter if required
        - Detect questions / questionnaire forms
        """
        await self.page.goto(vacancy_url, wait_until="domcontentloaded")
        await BrowserHarness.human_delay(1.5, 2.5)

        # Locate Apply button
        apply_btn = (
            self.page.locator("a[data-qa='vacancy-response-link-top']")
            .or_(self.page.locator("button[data-qa='vacancy-response-link-top']"))
            .or_(self.page.locator("a[data-qa='vacancy-response-link']"))
            .or_(self.page.locator("text='Откликнуться'").first)
        )

        if not await apply_btn.is_visible(timeout=3000):
            return {
                "success": False,
                "reason": "Кнопка 'Откликнуться' не найдена (возможно, уже откликнулись или вакансия в архиве)",
            }

        # Click apply
        await apply_btn.click()
        await BrowserHarness.human_delay(1.2, 2.0)

        # Check if an external redirect is required
        if "response/external" in self.page.url:
            return {
                "success": False,
                "requires_external": True,
                "external_url": self.page.url,
                "reason": "Требуется отклик на внешнем сайте работодателя",
            }

        # Check if employer questions / questionnaire modal is displayed
        question_modal = self.page.locator("div[data-qa='vacancy-response-questions']")
        if await question_modal.is_visible(timeout=2000):
            detected_questions = await self.extract_modal_questions()
            return {
                "success": False,
                "requires_questionnaire": True,
                "questions": detected_questions,
                "reason": "Работодатель требует заполнить анкету с вопросами",
            }

        # Check for cover letter toggle / input
        letter_toggle = self.page.locator("button[data-qa='vacancy-response-letter-toggle']")
        if await letter_toggle.is_visible(timeout=1500):
            await letter_toggle.click()
            await BrowserHarness.human_delay(0.5, 1.0)

        letter_input = self.page.locator(
            "textarea[data-qa='vacancy-response-popup-form-letter-input']"
        ).or_(self.page.locator("textarea[name='message']"))

        if cover_letter and await letter_input.is_visible(timeout=1500):
            # Type cover letter with realistic human speed
            await letter_input.click()
            await letter_input.fill(cover_letter)
            await BrowserHarness.human_delay(1.0, 1.8)

        # Submit application
        submit_btn = (
            self.page.locator("button[data-qa='vacancy-response-submit-popup']")
            .or_(self.page.locator("button[data-qa='vacancy-response-submit']")
            .or_(self.page.locator("button:has-text('Отправить отклик')")))
        )

        if await submit_btn.is_visible(timeout=2000):
            await submit_btn.click()
            await BrowserHarness.human_delay(2.0, 3.0)

        # Verify application success
        content = await self.page.content()
        if "Вы откликнулись" in content or "Отклик отправлен" in content or "Резюме доставлено" in content:
            return {
                "success": True,
                "reason": "Отклик успешно доставлен работодателю",
            }

        return {
            "success": True,
            "reason": "Форма отправлена (проверьте статус в личном кабинете)",
        }

    async def extract_modal_questions(self) -> List[Dict[str, Any]]:
        """Extract questionnaire field labels and input IDs from page DOM."""
        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")
        modal = soup.find("div", {"data-qa": "vacancy-response-questions"})
        if not modal:
            return []

        questions = []
        blocks = modal.find_all("div", class_=lambda x: x and "question" in x.lower())
        for idx, block in enumerate(blocks):
            label = block.find("label") or block.find("span")
            text = label.get_text(strip=True) if label else f"Вопрос {idx + 1}"
            input_tag = block.find(["input", "textarea"])
            input_name = input_tag.get("name", f"q_{idx}") if input_tag else f"q_{idx}"
            questions.append({
                "id": input_name,
                "text": text,
            })
        return questions
