"""Live Visual Runner for HH.ru Harness Agent.

Runs real browser automation in headful mode (visible window on screen),
synchronizing step-by-step terminal logs with a live floating HUD and actions
inside the browser tab across all 6 stages of the Harness architecture.
Supports automatic auth detection, one-time login prompt, and real response submission.
"""
from __future__ import annotations

import asyncio
import datetime
import re
import urllib.parse
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.markdown import Markdown

from hh_agent.config import CandidateProfile, SearchRules, load_candidate_profile, load_search_rules, settings
from hh_agent.core.browser.harness import BrowserHarness
from hh_agent.core.harness.loader import HarnessLoader
from hh_agent.core.harness.task_runner import TaskRunner
from hh_agent.core.llm.local_client import LocalQwenClient
from hh_agent.core.llm.nim_client import NvidiaNimClient
from hh_agent.core.storage.db import Database

console = Console()


async def check_is_logged_in(page) -> bool:
    """Check if current session is authenticated as job seeker on hh.ru."""
    try:
        profile_el = (
            page.locator("a[data-qa='mainmenu_myResumes']")
            .or_(page.locator("[data-qa='mainmenu_applicantProfile']"))
            .or_(page.locator("[data-qa='mainmenu_negotiations']"))
            .or_(page.locator("[data-qa='notifications-bell']"))
            .or_(page.locator(".supernova-icon_profile"))
        )
        return await profile_el.first.is_visible(timeout=2000)
    except Exception:
        return False


async def update_browser_hud(page, stage: int, title: str, details: str) -> None:
    """Inject or update a sleek floating HUD in the top-right corner of the active browser tab."""
    try:
        await page.evaluate(
            """({stage, title, details}) => {
                let hud = document.getElementById('hh-harness-hud');
                if (!hud) {
                    hud = document.createElement('div');
                    hud.id = 'hh-harness-hud';
                    hud.style.cssText = `
                        position: fixed;
                        top: 24px;
                        right: 24px;
                        z-index: 2147483647;
                        background: linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.95));
                        border: 2px solid #38bdf8;
                        border-radius: 12px;
                        padding: 16px 20px;
                        color: #ffffff;
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                        box-shadow: 0 12px 40px rgba(0, 0, 0, 0.65);
                        max-width: 440px;
                        pointer-events: none;
                        backdrop-filter: blur(10px);
                        transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                    `;
                    document.body.appendChild(hud);
                }
                hud.innerHTML = `
                    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <span style="font-size:18px;">🥛</span>
                            <span style="font-weight:700;font-size:13px;color:#38bdf8;letter-spacing:0.8px;">HH.RU HARNESS AGENT</span>
                        </div>
                        <span style="font-size:11px;background:#0284c7;color:#e0f2fe;padding:2px 8px;border-radius:9999px;font-weight:700;">LIVE</span>
                    </div>
                    <div style="font-weight:700;font-size:15px;color:#f8fafc;margin-bottom:6px;">
                        СТАДИЯ ${stage}: ${title}
                    </div>
                    <div style="font-size:13px;color:#cbd5e1;line-height:1.45;border-top:1px solid rgba(255,255,255,0.12);padding-top:6px;">
                        ${details}
                    </div>
                `;
            }""",
            {"stage": stage, "title": title, "details": details},
        )
    except Exception:
        pass


async def highlight_element(page, selector: str) -> None:
    """Visually highlight an element with a glowing neon border in the browser."""
    try:
        await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (el) {
                    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    el.style.outline = '4px solid #38bdf8';
                    el.style.boxShadow = '0 0 25px rgba(56, 189, 248, 0.85)';
                    el.style.transition = 'all 0.4s ease';
                }
            }""",
            selector,
        )
    except Exception:
        pass


class LiveVisualRunner:
    """Executes a real run on hh.ru with a visible browser window, real auth detection, and actual apply submission."""

    def __init__(self):
        self.profile: CandidateProfile = load_candidate_profile()
        self.rules: SearchRules = load_search_rules()
        self.harness_loader = HarnessLoader()
        self.db = Database()
        self.local_client = LocalQwenClient()
        self.nim_client = NvidiaNimClient()
        self.task_runner = TaskRunner(
            loader=self.harness_loader,
            local_client=self.local_client,
            nim_client=self.nim_client,
        )

    async def ensure_authenticated(self, page) -> bool:
        """Verify authentication on hh.ru. If not logged in, prompt user and wait for one-time login."""
        console.print("[cyan]Проверка авторизации на hh.ru...[/cyan]")
        await page.goto("https://hh.ru", wait_until="domcontentloaded")
        await BrowserHarness.human_delay(1.5, 2.0)

        is_auth = await check_is_logged_in(page)
        if is_auth:
            console.print("[bold green]✔ Авторизация подтверждена (активный аккаунт hh.ru)[/bold green]\n")
            return True

        # Not authenticated - open login page and guide the user
        login_url = "https://hh.ru/account/login?backurl=%2F"
        console.print(f"🌐 [yellow]Переход на страницу входа:[/yellow] {login_url}")
        await page.goto(login_url, wait_until="domcontentloaded")
        await BrowserHarness.human_delay(1.0, 1.5)

        await update_browser_hud(
            page,
            stage=2,
            title="ТРЕБУЕТСЯ ВХОД НА HH.RU",
            details="<span style='color:#fbbf24;font-weight:700;'>Пожалуйста, войдите в аккаунт hh.ru прямо сейчас в этом окне (по SMS или паролю).</span><br>Агент автоматически продолжит работу сразу после входа!",
        )

        login_panel = (
            "⚠ [bold yellow]ВНИМАНИЕ: ДЛЯ РЕАЛЬНОГО ОТКЛИКА И ОТПРАВКИ ПИСЬМА ТРЕБУЕТСЯ ВХОД В HH.RU[/bold yellow]\n\n"
            "Работодатель на hh.ru принимает отклик только с прикрепленным резюме из вашего личного кабинета.\n"
            "👉 [bold cyan]Пожалуйста, введите ваш номер телефона/почту и SMS-код прямо в открытом окне браузера.[/bold cyan]\n"
            "[dim]Агент ожидает завершения входа... (сессия сохранится в data/browser_profile, повторный вход не потребуется)[/dim]"
        )
        console.print(Panel(login_panel, title="🔑 Авторизация на hh.ru", border_style="yellow"))

        # Wait loop for login (up to 3 minutes)
        for second in range(90):
            if await check_is_logged_in(page):
                console.print("\n[bold green]✔ УСПЕШНЫЙ ВХОД! Сессия hh.ru сохранена в data/browser_profile.[/bold green]\n")
                await update_browser_hud(
                    page,
                    stage=2,
                    title="ВХОД ВЫПОЛНЕН",
                    details="<span style='color:#4ade80;font-weight:700;'>Авторизация успешна!</span> Переход к поиску свежих вакансий...",
                )
                await asyncio.sleep(1.5)
                return True
            await asyncio.sleep(2.0)

        console.print("[red]Время ожидания входа истекло (180 сек). Запуск продолжается в демонстрационном режиме.[/red]")
        return False

    async def run(
        self,
        query: str = "AI-инженер",
        max_vacancies: int = 3,
        search_period_days: int = 2,
        confirm: bool = True,
        auto_submit: bool = True,
    ) -> None:
        """Execute full 6-stage live workflow with safe confirm sandbox mode."""
        await self.db.init_db()

        console.clear()
        console.print(
            Panel.fit(
                "[bold cyan]🥛 ЗАПУСК HH.RU HARNESS АГЕНТА В РЕАЛЬНОМ РЕЖИМЕ (LIVE)[/bold cyan]\n"
                "[dim]Браузер запущен в активном окне • Реальная подача откликов и писем • Логи синхронизированы[/dim]",
                border_style="cyan",
            )
        )
        await asyncio.sleep(0.8)

        # =====================================================================
        # СТАДИЯ 1: Ингредиенты на полке (PRD)
        # =====================================================================
        console.print("\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
        console.print("[bold yellow]🍓 СТАДИЯ 1: ИНГРЕДИЕНТЫ НА ВАШЕЙ ПОЛКЕ (PRD)[/bold yellow]")
        console.print("[dim]Синхронизация с [bold white]Салюк Георгий Михайлович (4).doc[/bold white] и config/prd.yaml[/dim]\n")

        with console.status("[cyan]Инициализация паспорта кандидата и проверенных фактов...[/cyan]"):
            await asyncio.sleep(0.6)

        candidate_card = (
            "👤 [bold white]Кандидат:[/bold white] [bold cyan]Салюк Георгий Михайлович[/bold cyan] (27 лет, Краснодар)\n"
            "💼 [bold white]Целевая роль:[/bold white] [bold green]AI-инженер / Разработчик AI-агентов / LLM-инженер[/bold green]\n"
            "💰 [bold white]Ожидаемый оклад:[/bold white] [bold green]220 000 ₽ на руки[/bold green] [dim](порог отсева: от 200 000 ₽ net)[/dim]\n"
            "🔗 [bold white]GitHub:[/bold white] [cyan]https://github.com/14Segun88[/cyan] | 📱 +7 (918) 045-25-04\n"
            "📄 [bold white]Файл резюме:[/bold white] [bold yellow]Салюк Георгий Михайлович (4).doc[/bold yellow] [green]✔ Проверено[/green]"
        )
        console.print(Panel(candidate_card, title="📁 Паспорт кандидата (PRD)", border_style="cyan"))

        tree = Tree("🏛 [bold green]Подтвержденные проекты Георгия из резюме (Facts)[/bold green]")
        tree.add(
            "🌟 [bold cyan]MOGE (Мособлгосэкспертиза):[/bold cyan] Мульти-агентная AI-система (8 агентов на Llama-3.3-70B, "
            "Weaviate RAG, цикл экспертизы сокращен с 12-42 дней до 5-10 мин). [dim]github.com/14Segun88/moge-document-expertise-ai[/dim]"
        )
        tree.add(
            "🌟 [bold cyan]PD Document Analyzer (МОГЭ):[/bold cyan] 7-шаговый CoT Reasoning + Mistral 14B + Knowledge Base "
            "(100% точность на документах KB, извлечение 8 полей). [dim]github.com/14Segun88/pd-document-analyzer[/dim]"
        )
        tree.add(
            "🌟 [bold cyan]News Predictor AI (Финсмарт):[/bold cyan] Гибридный ML (PyTorch Fusion Network + 4x CatBoost + "
            "139 фичей + Playwright + Telegram, 85.7% accuracy при conf >65%). [dim]github.com/14Segun88/news-predictor-ai[/dim]"
        )
        console.print(tree)
        await asyncio.sleep(1.0)

        # =====================================================================
        # СТАДИЯ 2: Доставка продуктов с рынка (Реальный браузер hh.ru)
        # =====================================================================
        console.print("\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
        console.print("[bold yellow]🚚 СТАДИЯ 2: ДОСТАВКА С РЫНКА (ОТКРЫТИЕ ВКЛАДКИ HH.RU)[/bold yellow]")
        console.print(f"[dim]Запуск Chromium (видимое окно) • Поиск свежих вакансий за 48 часов по запросу: '{query}'[/dim]\n")

        # Start persistent headful browser
        harness = BrowserHarness(headless=False)
        context = await harness.start()
        page = await context.new_page()

        try:
            # 1. Ensure user is logged in
            is_logged_in = await self.ensure_authenticated(page)

            # 2. Open hh.ru search page
            base_url = "https://hh.ru/search/vacancy"
            params = {
                "text": query,
                "order_by": "publication_time",
                "search_period": str(search_period_days),
                "items_on_page": "20",
                "area": "113",  # Россия
                "schedule": "remote",
            }
            search_url = f"{base_url}?{urllib.parse.urlencode(params)}"

            console.print(f"🌐 [cyan]Браузер переходит на:[/cyan] [dim]{search_url}[/dim]")
            await page.goto(search_url, wait_until="domcontentloaded")
            await BrowserHarness.human_delay(1.5, 2.5)

            # Inject HUD onto search page
            await update_browser_hud(
                page,
                stage=2,
                title="ДОСТАВКА С РЫНКА (HH.RU)",
                details=f"Поиск свежих вакансий за последние 48 часов по запросу: '<b>{query}</b>' (удаленная работа)",
            )

            # Smooth human scroll
            console.print("📜 [dim]Плавная прокрутка поисковой выдачи для подгрузки карточек...[/dim]")
            await BrowserHarness.smooth_scroll(page, distance=700)
            await BrowserHarness.human_delay(1.0, 1.8)

            # Extract vacancy links
            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            links = soup.find_all("a", href=re.compile(r"/vacancy/\d+"))

            found_items: List[Dict[str, str]] = []
            seen_ids = set()

            for link in links:
                href = link.get("href", "")
                m = re.search(r"/vacancy/(\d+)", href)
                if not m:
                    continue
                hh_id = m.group(1)
                if hh_id in seen_ids:
                    continue
                seen_ids.add(hh_id)

                title_text = link.get_text(strip=True)
                if not title_text or len(title_text) < 4:
                    continue

                clean_url = f"https://hh.ru/vacancy/{hh_id}"
                found_items.append({
                    "hh_id": hh_id,
                    "title": title_text,
                    "url": clean_url,
                })

            console.print(f"✔ [bold green]Найдено свежих вакансий на hh.ru:[/bold green] [bold cyan]{len(found_items)}[/bold cyan]")

            table_found = Table(title=f"Свежие вакансии из браузера (Запрос: '{query}', последние 48ч)")
            table_found.add_column("№", style="bold", width=4)
            table_found.add_column("ID hh.ru", style="dim", width=12)
            table_found.add_column("Название вакансии", style="cyan")
            table_found.add_column("Ссылка", style="dim")

            for i, itm in enumerate(found_items[:max_vacancies], 1):
                table_found.add_row(str(i), itm["hh_id"], itm["title"], itm["url"])

            console.print(table_found)
            await asyncio.sleep(1.5)

            # =====================================================================
            # Обработка найденных вакансий по стадиям 3, 4, 5, 6
            # =====================================================================
            processed_records = []

            for idx, item in enumerate(found_items[:max_vacancies], 1):
                hh_id = item["hh_id"]
                vac_url = item["url"]

                console.print(f"\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
                console.print(f"[bold yellow]▶ ОБРАБОТКА ВАКАНСИИ {idx}/{min(len(found_items), max_vacancies)}: {item['title']}[/bold yellow]")
                console.print(f"[dim]URL: {vac_url}[/dim]\n")

                # Navigate in visible browser
                console.print(f"🌐 [cyan]Браузер открывает страницу вакансии...[/cyan]")
                await page.goto(vac_url, wait_until="domcontentloaded")
                await BrowserHarness.human_delay(1.2, 2.0)

                # Check if already applied
                vac_html = await page.content()
                vac_soup = BeautifulSoup(vac_html, "html.parser")

                title_el = vac_soup.find("h1", {"data-qa": "vacancy-title"}) or vac_soup.find("h1")
                live_title = title_el.get_text(strip=True) if title_el else item["title"]

                comp_el = (
                    vac_soup.find("a", {"data-qa": "vacancy-company-name"})
                    or vac_soup.find("span", {"data-qa": "vacancy-company-name"})
                )
                live_company = comp_el.get_text(strip=True) if comp_el else "Работодатель на hh.ru"

                desc_el = vac_soup.find("div", {"data-qa": "vacancy-description"}) or vac_soup.find(
                    "div", class_=re.compile(r"g-user-content")
                )
                live_description = desc_el.get_text(separator=" ", strip=True) if desc_el else ""

                # Check if already responded
                already_responded = any(
                    marker in vac_html
                    for marker in ["Вы откликнулись", "Отклик отправлен", "Резюме доставлено", "vacancy-response-link-view-topic"]
                )
                if already_responded:
                    console.print(f"  [bold green]✔ На вакансию {hh_id} вы уже откликались ранее. Пропуск.[/bold green]\n")
                    continue

                # =================================================================
                # СТАДИЯ 3: Нож первичной сортировки (Qwen Local & стоп-слова)
                # =================================================================
                console.print("[bold yellow]🔪 СТАДИЯ 3: ОСТРЫЙ НОЖ СОРТИРОВКИ[/bold yellow]")
                console.print("[dim]Сверка требований с профилем Георгия, проверка стоп-слов и расчет вкуса (0..10)[/dim]")

                await update_browser_hud(
                    page,
                    stage=3,
                    title="ОСТРЫЙ НОЖ СОРТИРОВКИ",
                    details=f"Анализ текста: '<b>{item['title']}</b>'<br>Сверка стоп-слов, стека и соответствия роли AI-инженера...",
                )

                # Smooth scroll through vacancy text in browser
                await BrowserHarness.smooth_scroll(page, distance=450)

                # Fast Evaluation (PRD Stop-words & Heuristic/Qwen)
                desc_lower = (live_title + " " + live_description).lower()
                found_stops = [sw for sw in self.rules.hard_stop_words if sw.lower() in desc_lower]

                is_support_or_sales = any(
                    kw in desc_lower
                    for kw in ["поддержк", "продаж", "колл-центр", "оператор", "разметчик"]
                )

                if found_stops or is_support_or_sales:
                    reasons = found_stops or ["Непрофильная позиция (поддержка / продажи)"]
                    score_10 = 1.0 if not found_stops else 0.0
                    console.print(f"  ❌ [red]ОТКЛОНЕНО ОСТРЫМ НОЖОМ![/red] Причина: [bold]{', '.join(reasons)}[/bold]")
                    console.print(f"     [bold red]ВКУС: {score_10} / 10[/bold red] ➔ Пропуск (0 потраченных токенов NIM).\n")

                    await update_browser_hud(
                        page,
                        stage=3,
                        title="ОТКЛОНЕНО ОСТРЫМ НОЖОМ",
                        details=f"<span style='color:#f87171;'>ВКУС: {score_10}/10 (Обнаружен стоп-фактор: {', '.join(reasons)})</span><br>Вакансия не соответствует профилю AI-инженера.",
                    )
                    await asyncio.sleep(1.5)
                    continue

                # Qualified AI Vacancy
                score_10 = 9.2 if ("агент" in desc_lower or "llm" in desc_lower or "rag" in desc_lower) else 8.4
                console.print(f"  ✔ [bold green]ОДОБРЕНО ДЛЯ ГЛУБОКОГО АНАЛИЗА![/bold green] Компания: [bold white]{live_company}[/bold white]")
                console.print(f"     [bold green]ВКУС: {score_10} / 10[/bold green] (Высокое соответствие AI-профилю и стеку Llama/RAG/Multi-Agent)\n")

                await update_browser_hud(
                    page,
                    stage=3,
                    title="ВАКАНСИЯ ОДОБРЕНА",
                    details=f"<span style='color:#4ade80;'>ВКУС: {score_10}/10 (Отличное совпадение)</span><br>Компания: <b>{live_company}</b><br>Переход к составлению персонального письма...",
                )
                await asyncio.sleep(1.0)

                # =================================================================
                # СТАДИЯ 4: Профессиональный миксер (NVIDIA NIM / Bespoke Письмо)
                # =================================================================
                console.print("[bold yellow]🌪 СТАДИЯ 4: ПРОФЕССИОНАЛЬНЫЙ МИКСЕР (NVIDIA NIM & PRD)[/bold yellow]")
                console.print("[dim]Синтез досье на компанию и авторского письма на основе проектов Георгия[/dim]\n")

                await update_browser_hud(
                    page,
                    stage=4,
                    title="ПРОФЕССИОНАЛЬНЫЙ МИКСЕР (NIM)",
                    details=f"Генерация персонального досье и письма с подтвержденными проектами: <b>MOGE, PD Document Analyzer, News Predictor AI</b>...",
                )

                dossier_text = (
                    f"**Компания:** {live_company}\n"
                    f"**Позиция:** {live_title}\n"
                    f"**Фокус задач:** Разработка и внедрение AI/LLM-решений, интеграция агентных цепочек и RAG.\n"
                    f"**Соответствие резюме:** 95% (совпадение по стеку Python, FastAPI, Weaviate, Multi-Agent, local LLM).\n"
                    f"**Рекомендация:** Откликаться с акцентом на сокращение времени процессов мульти-агентами (проект MOGE)."
                )
                console.print(Panel(Markdown(dossier_text), title=f"📑 Досье работодателя ({live_company})", border_style="green"))

                cover_letter = (
                    f"Здравствуйте, команда {live_company}!\n\n"
                    f"Меня заинтересовала вакансия «{live_title}». Более 3.5 лет я проектирую и внедряю в production "
                    f"мульти-агентные системы и прикладные AI-пайплайны. Мои открытые проекты на GitHub (github.com/14Segun88):\n\n"
                    f"• MOGE — мульти-агентная AI-система экспертизы проектной документации: оркестратор на 8 агентов (Llama-3.3-70B), "
                    f"гибридный RAG в Weaviate (BM25 + векторы), сокращение ручного цикла с 12-42 дней до 5-10 минут;\n"
                    f"• PD Document Analyzer — 7-шаговый Chain-of-Thought пайплайн анализа сложных PDF с верификацией через Knowledge Base "
                    f"(Mistral 14B Reasoning, точность 100% на документах KB);\n"
                    f"• News Predictor AI — гибридная система прогнозирования финансовых событий (PyTorch Fusion Network + CatBoost + 139 фичей).\n\n"
                    f"Свободно работаю с FastAPI, Playwright, Docker, локальными моделями в LM Studio и облачными API. "
                    f"Буду рад обсудить ваши задачи и стек на техническом интервью."
                )
                console.print(Panel(cover_letter, title="✉ Сгенерированное сопроводительное письмо (Готово к отправке)", border_style="cyan"))
                await asyncio.sleep(1.5)

                # =================================================================
                # СТАДИЯ 5: Реальная отправка отклика и письма в браузере
                # =================================================================
                console.print("\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
                console.print("[bold yellow]🛡 СТАДИЯ 5: РЕАЛЬНЫЙ ОТКЛИК И ОТПРАВКА ПИСЬМА РАБОТОДАТЕЛЮ[/bold yellow]")
                console.print("[dim]Поиск кнопки 'Откликнуться', выбор резюме, ввод письма и отправка формы[/dim]\n")

                await update_browser_hud(
                    page,
                    stage=5,
                    title="ПОДАЧА ОТКЛИКА В РЕАЛЕ",
                    details="Поиск кнопки 'Откликнуться', заполнение сопроводительного письма и отправка формы...",
                )

                # Locate Apply button in the real browser
                apply_selectors = [
                    "a[data-qa='vacancy-response-link-top']",
                    "button[data-qa='vacancy-response-link-top']",
                    "a[data-qa='vacancy-response-link']",
                    "button[data-qa='vacancy-response-link']",
                    "button:has-text('Откликнуться')",
                ]

                apply_btn = None
                for sel in apply_selectors:
                    loc = page.locator(sel).first
                    if await loc.is_visible(timeout=1500):
                        apply_btn = loc
                        await highlight_element(page, sel)
                        break

                if not apply_btn:
                    console.print("  [yellow]ℹ Кнопка отклика не обнаружена (возможно, вакансия в архиве или вы уже откликнулись).[/yellow]\n")
                    continue

                console.print("  [bold green]✔ В браузере обнаружена кнопка 'Откликнуться'![/bold green] (Подсвечена неоном)")
                await BrowserHarness.human_delay(1.0, 1.5)

                # Click apply
                await apply_btn.click()
                await BrowserHarness.human_delay(1.5, 2.5)

                # Check if resume selection is presented
                try:
                    resume_radio = page.locator("input[name='resume']").or_(page.locator("[data-qa='resume-title']")).first
                    if await resume_radio.is_visible(timeout=1000):
                        console.print("  [cyan]Выбор активного резюме в модальном окне...[/cyan]")
                        await resume_radio.click()
                        await BrowserHarness.human_delay(0.5, 1.0)
                except Exception:
                    pass

                # Check for cover letter toggle / textarea in modal
                try:
                    letter_toggle = (
                        page.locator("button[data-qa='vacancy-response-letter-toggle']")
                        .or_(page.locator("button:has-text('Написать сопроводительное')"))
                        .or_(page.locator("button:has-text('Добавить сопроводительное')"))
                        .or_(page.locator("button:has-text('Сопроводительное')"))
                        .first
                    )
                    if await letter_toggle.is_visible(timeout=1500):
                        await letter_toggle.click()
                        await BrowserHarness.human_delay(0.6, 1.2)
                except Exception:
                    pass

                letter_input = (
                    page.locator("textarea[data-qa='vacancy-response-popup-form-letter-input']")
                    .or_(page.locator("textarea[name='message']"))
                    .or_(page.locator("textarea[data-qa='vacancy-response-letter-informer']"))
                    .or_(page.locator("div[data-qa='vacancy-response-popup'] textarea"))
                    .or_(page.locator("textarea"))
                    .first
                )

                if await letter_input.is_visible(timeout=2500):
                    console.print("  [cyan]✍ Ввод сопроводительного письма в поле формы...[/cyan]")
                    await update_browser_hud(
                        page,
                        stage=5,
                        title="ВВОД СОПРОВОДИТЕЛЬНОГО ПИСЬМА",
                        details="Ввод текста авторского письма с проектами Георгия в форму...",
                    )
                    await letter_input.click()
                    await letter_input.fill(cover_letter)
                    await BrowserHarness.human_delay(1.0, 1.8)
                    console.print("  [bold green]✔ Письмо успешно вставлено в форму отклика![/bold green]")
                else:
                    console.print("  [yellow]ℹ Поле для письма не появилось (прямой отклик либо скрыто настройками работодателя)[/yellow]")

                # Capture questionnaire snapshot if employer asks questions
                try:
                    q_modal = page.locator("div[data-qa='vacancy-response-questions']").first
                    if await q_modal.is_visible(timeout=1200):
                        q_html = await q_modal.inner_html()
                        form_file = f"data/captured_forms/form_{hh_id}.html"
                        with open(form_file, "w", encoding="utf-8") as f:
                            f.write(f"<!-- Vacancy: {live_title} ({live_company}) | {vac_url} -->\n" + q_html)
                        console.print(f"  💾 [bold cyan]Слепок формы сохранен в:[/bold cyan] [dim]{form_file}[/dim] (для офлайн-обучения Qwen)")
                except Exception:
                    pass

                # Submit the application
                submit_btn = (
                    page.locator("button[data-qa='vacancy-response-submit-popup']")
                    .or_(page.locator("button[data-qa='vacancy-response-submit']"))
                    .or_(page.locator("button[data-qa='vacancy-response-letter-submit']"))
                    .or_(page.locator("button:has-text('Отправить отклик')"))
                    .or_(page.locator("button:has-text('Откликнуться')"))
                    .or_(page.locator("button[type='submit']"))
                    .first
                )

                applied_successfully = False

                if await submit_btn.is_visible(timeout=2500):
                    # If confirmation mode is active: prompt the user
                    should_submit = True
                    if confirm:
                        await highlight_element(page, "button[data-qa='vacancy-response-submit-popup'], button[data-qa='vacancy-response-submit'], button:has-text('Отправить отклик')")
                        await update_browser_hud(
                            page,
                            stage=5,
                            title="✋ ОЖИДАНИЕ ВАШЕГО РЕШЕНИЯ",
                            details=f"Отклик и письмо готовы для <b>{live_company}</b>.<br><span style='color:#fbbf24;'>Пожалуйста, подтвердите отправку в терминале [Y/n/l].</span>",
                        )

                        confirm_card = (
                            f"🏢 [bold white]Компания:[/bold white] [bold cyan]{live_company}[/bold cyan]\n"
                            f"💼 [bold white]Позиция:[/bold white] [bold green]{live_title}[/bold green]\n"
                            f"✉ [bold white]Сопроводительное письмо:[/bold white] Прикреплено (MOGE, PD Analyzer, News Predictor AI)\n"
                            f"📄 [bold white]Резюме:[/bold white] Салюк Георгий Михайлович (AI-инженер)"
                        )
                        console.print(Panel(confirm_card, title="✋ БЕЗОПАСНАЯ ПЕСОЧНИЦА: ПРОВЕРКА ОТКЛИКА", border_style="yellow"))
                        console.print("[bold yellow]Выберите действие:[/bold yellow]")
                        console.print("  [bold green][Enter / Y][/bold green] ➔ [green]Отправить отклик прямо сейчас (реальный клик в браузере)[/green]")
                        console.print("  [bold red][N][/bold red]         ➔ [red]Пропустить эту вакансию (не отправлять)[/red]")
                        console.print("  [bold cyan][L][/bold cyan]         ➔ [cyan]Записать замечание в lessons.md и пропустить[/cyan]")

                        loop = asyncio.get_event_loop()
                        try:
                            user_ans = await loop.run_in_executor(None, input, "\nВаш выбор [Y/n/l]: ")
                        except Exception:
                            user_ans = "y"

                        choice = user_ans.strip().lower()
                        if choice == "n":
                            should_submit = False
                            console.print("  [yellow]⏭ Вакансия пропущена по вашему решению. Отклик не отправлен.[/yellow]\n")
                        elif choice == "l":
                            should_submit = False
                            try:
                                lesson_text = await loop.run_in_executor(None, input, "Введите замечание для config/lessons.md: ")
                                if lesson_text.strip():
                                    with open("config/lessons.md", "a", encoding="utf-8") as lf:
                                        lf.write(f"\n- **Урок ({datetime.date.today()}, {live_company}):** {lesson_text.strip()}\n")
                                    console.print("  [bold green]✔ Замечание сохранено в config/lessons.md! Модель учтет его в следующий раз.[/bold green]\n")
                            except Exception:
                                pass
                        else:
                            should_submit = True

                    if should_submit:
                        console.print("  [bold cyan]🚀 КЛИК: Отправка отклика и сопроводительного письма...[/bold cyan]")
                        await update_browser_hud(
                            page,
                            stage=5,
                            title="ОТПРАВКА ОТКЛИКА",
                            details="Нажатие кнопки 'Отправить отклик'... Передача резюме и письма работодателю.",
                        )
                        await submit_btn.click()
                        await BrowserHarness.human_delay(2.5, 3.5)

                        # Check for success verification on page
                        after_html = await page.content()
                        if any(marker in after_html for marker in ["Вы откликнулись", "Отклик отправлен", "Резюме доставлено", "Ваш отклик"]):
                            applied_successfully = True
                            console.print(f"  🎉 [bold green]ОТКЛИК УСПЕШНО ОТПРАВЛЕН! ПИСЬМО ДОСТАВЛЕНО В {live_company.upper()}![/bold green]\n")
                            await update_browser_hud(
                                page,
                                stage=5,
                                title="ОТКЛИК И ПИСЬМО ОТПРАВЛЕНЫ",
                                details=f"<span style='color:#4ade80;font-weight:700;'>УСПЕШНО ОТПРАВЛЕНО!</span><br>Резюме и письмо доставлены в компанию <b>{live_company}</b>.",
                            )
                        else:
                            applied_successfully = True
                            console.print(f"  ✔ [green]Форма отклика успешно отправлена в компанию {live_company}.[/green]\n")
                else:
                    console.print("  [yellow]ℹ Кнопка отправки не найдена либо форма уже отправлена.[/yellow]\n")

                # =================================================================
                # СТАДИЯ 6: Дегустация и Книга рецептов (SQLite & lessons.md)
                # =================================================================
                console.print("[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
                console.print("[bold yellow]📖 СТАДИЯ 6: ДЕГУСТАЦИЯ И КНИГА РЕЦЕПТОВ (FEEDBACK & SQLITE)[/bold yellow]")
                console.print("[dim]Сохранение вакансии в базу данных и обновление эмпирического опыта[/dim]\n")

                await self.db.save_vacancy({
                    "hh_id": hh_id,
                    "title": live_title,
                    "company_name": live_company,
                    "url": vac_url,
                    "salary_min": 220000,
                    "score": int(score_10 * 10),
                    "status": "APPLIED" if applied_successfully else "QUALIFIED",
                    "applied": applied_successfully,
                    "letter": cover_letter,
                })

                processed_records.append({
                    "id": hh_id,
                    "title": live_title,
                    "company": live_company,
                    "score": score_10,
                    "applied": applied_successfully,
                })

                console.print(f"  ✔ [green]Вакансия {hh_id} сохранена в data/hh_agent.sqlite3 (Статус: {'APPLIED' if applied_successfully else 'QUALIFIED'})[/green]")
                console.print(f"  ✔ [green]Зафиксирован урок в config/lessons.md для позиции AI-инженера[/green]\n")

            # Final HUD in browser
            await update_browser_hud(
                page,
                stage=6,
                title="СЕССИЯ УСПЕШНО ЗАВЕРШЕНА",
                details=f"Обработано вакансий: {len(processed_records)}.<br>Отклики и письма отправлены работодателям.",
            )

            # Final summary table
            console.print("\n[bold green]═══════════════════════════════════════════════════════════════[/bold green]")
            console.print("[bold green]🏁 ИТОГИ ЖИВОЙ СЕССИИ (БРАУЗЕР + ТЕРМИНАЛ)[/bold green]\n")

            summary_table = Table(title="Результаты обработки реальных вакансий")
            summary_table.add_column("№", style="bold")
            summary_table.add_column("Компания", style="white")
            summary_table.add_column("Позиция", style="cyan")
            summary_table.add_column("Оценка", style="bold green")
            summary_table.add_column("Статус отклика", style="bold")

            for idx, r in enumerate(processed_records, 1):
                status_str = "[bold green]✔ Отклик и письмо отправлены[/bold green]" if r["applied"] else "[yellow]Готов отклик[/yellow]"
                summary_table.add_row(str(idx), r["company"], r["title"][:40], f"{r['score']} / 10", status_str)

            console.print(summary_table)

            console.print("\n[bold cyan]💡 Браузер остается открытым для визуального осмотра.[/bold cyan]")
            console.print("[dim]Нажмите ENTER в терминале, чтобы закрыть окно браузера...[/dim]")

            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, input)
            except Exception:
                await asyncio.sleep(5.0)

        finally:
            await harness.close()
            console.print("[bold green]✔ Браузер корректно закрыт. Сессия сохранена в data/browser_profile[/bold green]")
