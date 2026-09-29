"""Autonomous Telegram Vacancy Hunter.

Scans public tech hiring Telegram channels (careerspace, datasciencejobs, Getitrussia, it_hr_vacancy)
via Telegram's official web mirror (https://t.me/s/...) without needing my.telegram.org API keys.

Workflow:
1. Fetch latest posts for today/recent days.
2. Filter & score vacancies using CandidateProfile & SearchRules (AI, LLM, Agents, RAG, Python).
3. Classify Call-To-Action (CTA):
   - Direct Telegram message to recruiter (@username)
   - External URL / ATS form (Huntflow, Careerspace, Notion, Google Forms)
   - Telegram application bot (e.g. @g_jobbot)
   - Email
4. Generate bespoke high-converting Telegram pitch for Georgiy Salyuk.
5. Save records into SQLite database (tg_vacancies).
6. Dispatch interactive cards with 1-click action buttons to Telegram CRM bot.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hh_agent.config import CandidateProfile, SearchRules, load_candidate_profile, load_search_rules
from hh_agent.core.storage.db import Database

logger = logging.getLogger(__name__)
console = Console()

DEFAULT_CHANNELS = [
    "datasciencejobs",
    "careerspace",
    "Getitrussia",
    "it_hr_vacancy",
]


class TelegramVacancyHunter:
    """Scrapes, analyzes, scores, and tracks Telegram channel job postings."""

    def __init__(
        self,
        db: Optional[Database] = None,
        profile: Optional[CandidateProfile] = None,
        rules: Optional[SearchRules] = None,
        channels: Optional[List[str]] = None,
    ):
        self.db = db or Database()
        self.profile = profile or load_candidate_profile()
        self.rules = rules or load_search_rules()
        self.channels = channels or DEFAULT_CHANNELS

    async def fetch_channel_posts(
        self,
        channel_name: str,
        days_back: int = 1,
    ) -> List[Dict[str, Any]]:
        """Fetch and parse recent posts from public web mirror https://t.me/s/{channel_name}."""
        clean_channel = channel_name.strip().lstrip("@").replace("https://t.me/", "").replace("t.me/", "")
        url = f"https://t.me/s/{clean_channel}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        posts: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    console.print(f"  [yellow]⚠ Канал @{clean_channel}: HTTP {resp.status_code}[/yellow]")
                    return []
                html = resp.text
        except Exception as e:
            console.print(f"  [red]❌ Ошибка загрузки @{clean_channel}:[/red] {e}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        msg_divs = soup.find_all("div", class_="tgme_widget_message")

        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff_date = now - datetime.timedelta(days=days_back)

        for div in msg_divs:
            raw_post_id = div.get("data-post") or ""
            if not raw_post_id:
                continue

            time_el = div.find("time")
            published_dt = None
            if time_el and time_el.get("datetime"):
                try:
                    published_dt = datetime.datetime.fromisoformat(time_el["datetime"])
                except Exception:
                    published_dt = None

            # Filter by date if datetime is present
            if published_dt and published_dt < cutoff_date:
                continue

            text_div = div.find("div", class_="tgme_widget_message_text")
            if not text_div:
                continue

            raw_text = text_div.get_text("\n", strip=True)
            if len(raw_text) < 40:
                continue

            # Extract links
            links = []
            for a in text_div.find_all("a"):
                href = a.get("href")
                if href and not href.startswith("?q=") and f"t.me/s/{clean_channel}" not in href:
                    links.append(href)

            # Extract mentions (@username)
            mentions = re.findall(r"@[a-zA-Z0-9_]{4,}", raw_text)
            clean_mentions = [
                m for m in mentions
                if m.lower() not in (f"@{clean_channel.lower()}", "@datasciencejobs", "@careerspace", "@getitrussia", "@it_hr_vacancy")
            ]

            posts.append({
                "post_id": raw_post_id,
                "channel_name": clean_channel,
                "post_url": f"https://t.me/{raw_post_id}",
                "published_at": published_dt.isoformat() if published_dt else now.isoformat(),
                "raw_text": raw_text,
                "links": links,
                "mentions": clean_mentions,
            })

        return posts

    def analyze_and_classify_post(self, post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Evaluate vacancy match and determine CTA contact method."""
        text = post["raw_text"]
        text_lower = text.lower()
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        first_line = lines[0] if lines else "Вакансия в Telegram"

        # 1. Stop-word filtering
        # Junior/intern restricted strictly to the first 2 lines (headline)
        headline = " ".join(lines[:2]).lower()
        junior_keywords = {"junior", "джуниор", "стажер", "стажировка", "intern", "internship", "trainee", "практикант"}

        for sw in self.rules.hard_stop_words:
            sw_lower = sw.lower()
            if sw_lower in junior_keywords:
                if sw_lower in headline:
                    return None
            else:
                if sw_lower in text_lower:
                    return None

        # 2. Key AI / LLM / Python pattern matching
        ai_patterns = {
            "Python": ["python", "питон", "пайтон"],
            "LLM / GenAI": ["llm", "large language model", "языковые модели", "genai", "генеративн", "gpt", "rag"],
            "AI Agents": ["agent", "агент", "crewai", "autogen", "langgraph", "мультиагент"],
            "RAG / Vector DB": ["rag", "weaviate", "qdrant", "chroma", "векторн", "vector", "faiss"],
            "FastAPI / Backend": ["fastapi", "asyncio", "микросервис", "rest api"],
            "ML / Data Science": ["pytorch", "torch", "catboost", "xgboost", "машинное обучение", "machine learning", "data science"],
            "OpenSource LLM": ["llama", "qwen", "mistral", "ollama", "lm studio", "vllm"],
        }

        matched_skills = []
        for skill_name, keywords in ai_patterns.items():
            if any(kw in text_lower for kw in keywords):
                matched_skills.append(skill_name)

        # Must have at least 2 AI/Python markers to be considered relevant
        if len(matched_skills) < 2 and not any(kw in text_lower for kw in ["ai-инженер", "llm", "prompt engineer", "ai engineer"]):
            return None

        # Calculate score (0 to 100)
        score = min(98, 50 + len(matched_skills) * 8)
        if any(term in text_lower for term in ["удален", "remote", "удалён"]):
            score = min(98, score + 10)

        # 3. Determine Contact CTA
        contact_type = "UNKNOWN"
        contact_target = ""

        # Check for recruiter mention first (@username)
        if post["mentions"]:
            contact_type = "DM_TELEGRAM"
            contact_target = post["mentions"][0]
        else:
            # Check links
            telegram_links = [l for l in post["links"] if "t.me/" in l and not any(ch in l.lower() for ch in DEFAULT_CHANNELS)]
            external_links = [l for l in post["links"] if "t.me/" not in l]

            if telegram_links:
                contact_type = "DM_TELEGRAM"
                contact_target = telegram_links[0]
            elif external_links:
                contact_type = "EXTERNAL_URL"
                contact_target = external_links[0]
            else:
                email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text)
                if email_match:
                    contact_type = "EMAIL"
                    contact_target = email_match.group(0)

        # Extract title and company name heuristically
        title = first_line[:80].strip(" #•*—:-")
        company = "Компания из Telegram"
        comp_match = re.search(r"(?:компания|в команду|в|от)\s+([A-Za-zА-Яа-я0-9\s\-_]{2,30})", text, re.IGNORECASE)
        if comp_match:
            candidate_comp = comp_match.group(1).strip()
            if len(candidate_comp) > 2 and "\n" not in candidate_comp:
                company = candidate_comp

        # Draft short bespoke pitch
        drafted_pitch = self._build_telegram_pitch(
            title=title,
            company=company,
            channel=post["channel_name"],
            matched_skills=matched_skills,
        )

        return {
            "post_id": post["post_id"],
            "channel_name": post["channel_name"],
            "post_url": post["post_url"],
            "published_at": post["published_at"],
            "title": title,
            "company_name": company,
            "raw_text": text,
            "contact_type": contact_type,
            "contact_target": contact_target,
            "all_links": post["links"],
            "all_mentions": post["mentions"],
            "score": score,
            "extracted_stack": matched_skills,
            "drafted_pitch": drafted_pitch,
            "status": "PITCH_READY",
        }

    def _build_telegram_pitch(
        self,
        title: str,
        company: str,
        channel: str,
        matched_skills: List[str],
    ) -> str:
        """Formulate a concise 4-5 line high-conversion message for Georgiy Salyuk."""
        skills_str = ", ".join(matched_skills[:4]) if matched_skills else "LLM, RAG, Python"
        pitch = (
            f"Здравствуйте! Увидел вашу вакансию на позицию «{title}» в канале @{channel}.\n\n"
            f"Я AI-инженер / LLM-разработчик (опыт 3.5+ лет). Специализируюсь на проектировании мультиагентных систем "
            f"(MOGE на Llama-3.3-70B/Qwen), гибридном RAG в Weaviate и надежном бэкенде на Python/FastAPI. "
            f"Стек: {skills_str}.\n\n"
            f"Портфолио и проекты на GitHub: https://github.com/14Segun88\n"
            f"Резюме и контакты: +7 (918) 045-25-04 (Георгий Салюк).\n\n"
            f"Буду рад обсудить задачи и требования. Подскажите, когда вам удобно созвониться на 15 минут?"
        )
        return pitch

    async def scan_all_channels(self, days_back: int = 1) -> List[Dict[str, Any]]:
        """Scan all configured channels and collect matching AI/LLM job postings."""
        await self.db.init_db()
        console.print(Panel.fit(
            f"[bold cyan]✈️ СКАНЕР TELEGRAM-КАНАЛОВ (БЕЗ API-КЛЮЧЕЙ)[/bold cyan]\n"
            f"[dim]Каналы: {', '.join(['@' + c for c in self.channels])} • Окно: {days_back} дн.[/dim]",
            border_style="cyan",
        ))

        all_qualified: List[Dict[str, Any]] = []

        for ch in self.channels:
            console.print(f"  🔍 [cyan]Проверка канала @{ch}...[/cyan]")
            posts = await self.fetch_channel_posts(ch, days_back=days_back)
            console.print(f"     Найдено постов за период: [bold white]{len(posts)}[/bold white]")

            ch_qualified = 0
            for post in posts:
                # Skip if already in database
                if await self.db.tg_vacancy_exists(post["post_id"]):
                    continue

                analysis = self.analyze_and_classify_post(post)
                if analysis:
                    await self.db.save_tg_vacancy(analysis)
                    all_qualified.append(analysis)
                    ch_qualified += 1

            if ch_qualified > 0:
                console.print(f"     🎯 [bold green]Отобрано релевантных AI/LLM вакансий:[/bold green] {ch_qualified}")
            else:
                console.print(f"     [dim]Нет новых релевантных вакансий[/dim]")

            await asyncio.sleep(0.5)

        # Print summary table
        if all_qualified:
            table = Table(title="🔥 Найденные вакансии в Telegram за сегодня")
            table.add_column("№", style="bold", width=3)
            table.add_column("Канал", style="magenta", width=16)
            table.add_column("Позиция", style="cyan", width=32)
            table.add_column("Скор", style="bold green", width=6)
            table.add_column("Тип отклика", style="yellow", width=14)
            table.add_column("Контакт", style="white")

            for idx, vac in enumerate(all_qualified, 1):
                contact_display = vac["contact_target"] or "в посте"
                table.add_row(
                    str(idx),
                    f"@{vac['channel_name']}",
                    vac["title"][:30],
                    f"{vac['score']}%",
                    vac["contact_type"],
                    contact_display[:30],
                )
            console.print(table)
        else:
            console.print("\n[dim]Новых подходящих AI/LLM вакансий в Telegram за указанный период не обнаружено.[/dim]\n")

        return all_qualified
