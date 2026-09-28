from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from playwright.async_api import Page
from hh_agent.config import SearchConfig
from hh_agent.core.browser.harness import BrowserHarness


class VacancyBrowser:
    """Manages search, navigation, and extraction of vacancies on hh.ru."""

    def __init__(self, page: Page):
        self.page = page

    def build_search_url(
        self, query: str, config: SearchConfig, search_period_days: int = 2
    ) -> str:
        """Construct hh.ru search URL targeting recent vacancies (yesterday + today)."""
        base = "https://hh.ru/search/vacancy"
        params = {
            "text": query,
            "order_by": config.order_by,
            "search_period": str(search_period_days),  # 2 days: yesterday + today
            "items_on_page": "20",
        }
        if config.area_id:
            params["area"] = str(config.area_id)
        if config.only_remote:
            params["schedule"] = "remote"
        for exp in config.experience:
            params.setdefault("experience", exp)

        return f"{base}?{urllib.parse.urlencode(params)}"

    async def fetch_search_results(self, search_url: str) -> List[Dict[str, str]]:
        """Navigate to search page and gather vacancy links and titles."""
        await self.page.goto(search_url, wait_until="domcontentloaded")
        await BrowserHarness.human_delay(1.5, 2.5)
        await BrowserHarness.smooth_scroll(self.page, distance=600)

        # Handle cookies banner if present
        try:
            cookie_accept = self.page.locator(
                "button[data-qa='cookies-policy-informer-accept']"
            )
            if await cookie_accept.is_visible(timeout=1500):
                await cookie_accept.click()
        except Exception:
            pass

        content = await self.page.content()
        soup = BeautifulSoup(content, "html.parser")

        results = []
        # Find vacancy title links
        links = soup.find_all("a", href=re.compile(r"/vacancy/\d+"))
        seen_ids = set()

        for link in links:
            href = link.get("href", "")
            # Extract clean vacancy ID
            match = re.search(r"/vacancy/(\d+)", href)
            if not match:
                continue
            hh_id = match.group(1)
            if hh_id in seen_ids:
                continue
            seen_ids.add(hh_id)

            title = link.get_text(strip=True)
            if not title:
                continue

            clean_url = f"https://hh.ru/vacancy/{hh_id}"
            results.append({
                "hh_id": hh_id,
                "title": title,
                "url": clean_url,
            })

        return results

    async def extract_vacancy_details(self, vacancy_url: str) -> Optional[Dict[str, Any]]:
        """Navigate directly to vacancy page and extract structured details."""
        try:
            await self.page.goto(vacancy_url, wait_until="domcontentloaded")
            await BrowserHarness.human_delay(1.0, 2.0)
            await BrowserHarness.smooth_scroll(self.page, distance=500)

            # Check for captcha or blocking page
            title = await self.page.title()
            if "Доступ ограничен" in title or "Подтвердите, что вы не робот" in title:
                return {
                    "is_blocked": True,
                    "error": "Captcha triggered: please solve in headful browser",
                }

            html = await self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Vacancy ID
            match = re.search(r"/vacancy/(\d+)", vacancy_url)
            hh_id = match.group(1) if match else ""

            # Title
            title_tag = soup.find("h1", {"data-qa": "vacancy-title"}) or soup.find("h1")
            vac_title = title_tag.get_text(strip=True) if title_tag else "Без названия"

            # Company
            company_tag = (
                soup.find("a", {"data-qa": "vacancy-company-name"})
                or soup.find("span", {"data-qa": "vacancy-company-name"})
            )
            company_name = company_tag.get_text(strip=True) if company_tag else "Не указана"
            company_url = ""
            if company_tag and company_tag.name == "a" and company_tag.get("href"):
                company_url = urllib.parse.urljoin("https://hh.ru", company_tag.get("href"))

            # Salary
            salary_tag = soup.find("span", {"data-qa": "vacancy-salary-compensation-type-net"}) or \
                         soup.find("span", {"data-qa": "vacancy-salary-compensation-type-gross"}) or \
                         soup.find("div", {"data-qa": "vacancy-salary"})
            salary_raw = salary_tag.get_text(strip=True) if salary_tag else "Зарплата не указана"

            # Parse numeric salary
            salary_min, salary_max, currency = self._parse_salary_numbers(salary_raw)

            # Full description
            desc_tag = soup.find("div", {"data-qa": "vacancy-description"}) or soup.find(
                "div", class_=re.compile(r"g-user-content")
            )
            description = desc_tag.get_text(separator="\n", strip=True) if desc_tag else ""

            # Key skills badges
            skill_tags = soup.find_all("span", {"data-qa": "bloko-tag__text"})
            extracted_skills = [s.get_text(strip=True) for s in skill_tags if s.get_text(strip=True)]

            # Check if already applied
            already_applied = False
            applied_badge = soup.find(string=re.compile(r"Вы откликнулись|Отклик отправлен", re.I))
            if applied_badge:
                already_applied = True

            return {
                "hh_id": hh_id,
                "title": vac_title,
                "company_name": company_name,
                "company_url": company_url,
                "salary_raw": salary_raw,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "currency": currency,
                "url": vacancy_url,
                "description": description,
                "key_skills": extracted_skills,
                "already_applied": already_applied,
                "is_blocked": False,
            }
        except Exception as e:
            return None

    def _parse_salary_numbers(self, text: str) -> tuple[Optional[int], Optional[int], str]:
        """Helper to extract integer ranges from salary text."""
        currency = "RUR"
        if "USD" in text or "$" in text:
            currency = "USD"
        elif "EUR" in text or "€" in text:
            currency = "EUR"

        # Remove spaces in numbers (e.g. "250 000" -> "250000")
        clean_text = re.sub(r"(\d)\s+(\d)", r"\1\2", text)
        numbers = [int(n) for n in re.findall(r"\b\d{4,7}\b", clean_text)]

        if not numbers:
            return None, None, currency
        if len(numbers) == 1:
            if "от" in text.lower():
                return numbers[0], None, currency
            return None, numbers[0], currency
        return min(numbers), max(numbers), currency
