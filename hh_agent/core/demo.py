from __future__ import annotations

import asyncio
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich.markdown import Markdown
from hh_agent.core.harness.loader import HarnessLoader

console = Console()


class HarnessDemoRunner:
    """Demonstrates all 6 stages of the HH.ru AI Harness using live configs and clear mock data."""

    def __init__(self):
        self.loader = HarnessLoader()

    async def run_interactive_demo(self) -> None:
        console.clear()
        console.print(
            Panel.fit(
                "[bold cyan]🥛 ДЕМОНСТРАЦИЯ РАБОТЫ HH.RU HARNESS АГЕНТА: 6 СТАДИЙ[/bold cyan]\n"
                "[dim]Интерактивная визуализация: от сырых ингредиентов до идеального коктейля (отклика)[/dim]",
                border_style="cyan",
            )
        )
        await asyncio.sleep(1.0)

        # =====================================================================
        # СТАДИЯ 1: Ингредиенты на полке (PRD)
        # =====================================================================
        console.print("\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
        console.print("[bold yellow]🍓 СТАДИЯ 1: ИНГРЕДИЕНТЫ НА ВАШЕЙ ПОЛКЕ (PRD)[/bold yellow]")
        console.print("[dim]Загрузка проверенных фактов о кандидате из config/prd.yaml[/dim]\n")

        with console.status("[cyan]Проверка холодильника с продуктами (PRD)...[/cyan]"):
            await asyncio.sleep(1.2)

        tree = Tree("📁 [bold green]Ваш профиль кандидата (PRD.yaml)[/bold green]")
        
        facts_node = tree.add("🥛 [bold]Свежие ингредиенты (Факты):[/bold]")
        for f in self.loader.prd.facts[:4]:
            facts_node.add(f"[cyan]{f.id}[/cyan] [dim]{f.tags}:[/dim] {f.text}")

        wants_node = tree.add("🎯 [bold]Желаемый вкус (Wants):[/bold]")
        wants_node.add(f"Зарплата: [green]от {self.loader.prd.wants.salary_net_min:,} руб. net[/green]")
        wants_node.add(f"Формат: [green]{', '.join(self.loader.prd.wants.format)}[/green]")
        wants_node.add(f"Стоп-слова: [red]{', '.join(self.loader.prd.wants.stop_words[:5])}...[/red]")

        security_node = tree.add("⛔ [bold red]ЯД! Запрещено сыпать в блендер (Never Disclose):[/bold red]")
        for nd in self.loader.prd.never_disclose[:3]:
            security_node.add(f"[red]{nd}[/red]")

        console.print(tree)
        await asyncio.sleep(1.5)

        # =====================================================================
        # СТАДИЯ 2: Доставка продуктов с рынка (hh.ru)
        # =====================================================================
        console.print("\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
        console.print("[bold yellow]🚚 СТАДИЯ 2: ДОСТАВКА ПРОДУКТОВ С РЫНКА (HH.RU)[/bold yellow]")
        console.print("[dim]Курьер привез 3 новые вакансии за последние 24–48 часов[/dim]\n")

        with console.status("[cyan]Сканирование поисковой выдачи hh.ru...[/cyan]"):
            await asyncio.sleep(1.2)

        vacancies = [
            {
                "id": "vac_1",
                "title": "Разработчик AI-агентов / LLM-инженер (Multi-Agent, RAG)",
                "company": "NeuraTech AI Labs",
                "salary": "220 000 – 280 000 ₽ на руки",
                "type": "Мульти-агентные системы, Llama 3.3, Weaviate, удаленка",
            },
            {
                "id": "vac_2",
                "title": "Младший разметчик данных / Оператор аннотаций AI",
                "company": "ДатаКрауд Офис",
                "salary": "35 000 ₽ (оклад 25к)",
                "type": "Стоп-слова: разметчик данных, стажер, оператор",
            },
            {
                "id": "vac_3",
                "title": "Lead AI Engineer (RAG / Agentic Architect) + Тест",
                "company": "RoboCore Dynamics",
                "salary": "260 000 ₽",
                "type": "Отличный стек, но требует архитектурное тестовое задание",
            },
        ]

        table_vac = Table(title="Новые вакансии с hh.ru (AI / LLM)")
        table_vac.add_column("№", style="bold")
        table_vac.add_column("Позиция", style="cyan")
        table_vac.add_column("Компания", style="white")
        table_vac.add_column("Зарплата", style="green")
        table_vac.add_column("Специфика", style="dim")

        for idx, v in enumerate(vacancies, 1):
            table_vac.add_row(str(idx), v["title"], v["company"], v["salary"], v["type"])

        console.print(table_vac)
        await asyncio.sleep(1.8)

        # =====================================================================
        # СТАДИЯ 3: Нож первичной сортировки (Qwen Local)
        # =====================================================================
        console.print("\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
        console.print("[bold yellow]🔪 СТАДИЯ 3: ОСТРЫЙ НОЖ СОРТИРОВКИ (ЛОКАЛЬНАЯ QWEN 2.5 7B)[/bold yellow]")
        console.print("[dim]Мгновенная проверка на стоп-слова и базовый скоринг на видеокарте[/dim]\n")

        with console.status("[cyan]Нож шинкует и оценивает продукты по шкале 0..10...[/cyan]"):
            await asyncio.sleep(1.5)

        console.print("  ❌ [red]Вакансия №2 (Разметчик данных):[/red] Обнаружены стоп-слова: [bold]'Разметчик данных'[/bold], [bold]'Оператор'[/bold].")
        console.print("     [bold red]ВКУС: 0 / 10[/bold red] ➔ [bold]Мгновенно летит в мусорку[/bold] (0 потраченных токенов NIM).\n")
        await asyncio.sleep(0.8)

        console.print("  ✔ [green]Вакансия №1 (Разработчик AI-агентов):[/green] Профиль Multi-Agent, RAG, удаленка, ЗП 220k–280k (в вилке 220k net).")
        console.print("     [bold green]ВКУС: 9.6 / 10[/bold green] ➔ [bold]Одобрено для глубокого анализа[/bold].\n")
        await asyncio.sleep(0.8)

        console.print("  ✔ [green]Вакансия №3 (Lead AI Engineer + Тест):[/green] Топовый стек, обнаружена форма с тестом по архитектуре.")
        console.print("     [bold green]ВКУС: 8.3 / 10[/bold green] ➔ [bold]Одобрено, требуется проверка сценария[/bold].\n")
        await asyncio.sleep(1.5)

        # =====================================================================
        # СТАДИЯ 4: Профессиональный миксер (NVIDIA NIM)
        # =====================================================================
        console.print("\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
        console.print("[bold yellow]🌪 СТАДИЯ 4: ПРОФЕССИОНАЛЬНЫЙ МИКСЕР (NVIDIA NIM 70B)[/bold yellow]")
        console.print("[dim]Взбиваем идеальный коктейль: досье на компанию и персонализированное письмо[/dim]\n")

        with console.status("[cyan]NVIDIA NIM готовит досье и авторское письмо для Вакансии №1...[/cyan]"):
            await asyncio.sleep(1.8)

        dossier_text = (
            "**Обзор компании:** Продуктовая AI-лаборатория, специализирующаяся на автономных агентах для Enterprise.\n"
            "**Плюсы:** Белая зарплата 250k, современный стек (Llama 3.3, Weaviate, Groq), сильная engineering-команда, нет бюрократии.\n"
            "**Риски:** Высокие требования к latency и стабильности ответов мульти-агентных цепочек.\n"
            "**Вердикт NIM:** Рекомендуется откликаться в первую очередь."
        )
        console.print(Panel(Markdown(dossier_text), title="📑 Досье работодателя (NVIDIA NIM)", border_style="green"))

        cover_letter = (
            "Добрый день!\n\n"
            "Более 3.5 лет занимаюсь разработкой AI-систем и автономных агентов. В портфолио на GitHub (github.com/14Segun88):\n"
            "• MOGE — мульти-агентная система госэкспертизы (8 AI-агентов с оркестратором на Llama-3.3-70B, сократила ручной анализ с 12–42 дней до 5–10 минут);\n"
            "• PD Document Analyzer — 7-шаговый CoT-пайплайн извлечения метаданных из строительных PDF с верификацией через Knowledge Base (100% точность);\n"
            "• News Predictor AI — гибридная система прогнозирования (PyTorch Fusion Network + 4 CatBoost + эмбеддинги знаний).\n\n"
            "Свободно работаю с FastAPI, Weaviate (гибридный поиск), локальными моделями в LM Studio и облачными API (NVIDIA NIM, Groq). "
            "Буду рад обсудить архитектурные задачи вашей команды на техническом интервью."
        )
        console.print(Panel(cover_letter, title="✉ Сгенерированное письмо (Без клише, реальные проекты Георгия с GitHub)", border_style="cyan"))
        await asyncio.sleep(1.8)

        # =====================================================================
        # СТАДИЯ 5: Защитная крышка и сценарии (Specs & Atomic Tasks)
        # =====================================================================
        console.print("\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
        console.print("[bold yellow]🛡 СТАДИЯ 5: ЗАЩИТНАЯ КРЫШКА И СЦЕНАРИИ (SPECS & TASKS)[/bold yellow]")
        console.print("[dim]Проверка безопасности на уровне Python-кода (allowed_effects & approval)[/dim]\n")

        with console.status("[cyan]Проверка датчиков блокировки крышки...[/cyan]"):
            await asyncio.sleep(1.2)

        console.print("  [cyan]Сценарий для Вакансии №1 (cover_letter):[/cyan]")
        console.print("    • Требуется письмо: [bold green]ДА (подготовлено на Стадии 4)[/bold green]")
        console.print("    • Разрешенные эффекты таски: [bold]['draft_db', 'fill_letter'][/bold]")
        console.print("    • Результат: [bold green]Отклик готов к безопасной отправке.[/bold green]\n")

        console.print("  [yellow]Сценарий для Вакансии №3 (complex_test):[/yellow]")
        console.print("    • Обнаружен тест по агентной архитектуре: [bold red]ТРЕБУЕТСЯ КОД[/bold red]")
        console.print("    • Политика из specs.yaml: [bold red]REQUIRES_HUMAN (approval: required)[/bold red]")
        console.print("    • [bold yellow]Защитная крышка сработала![/bold yellow] Модель не отправляет решения наугад.")
        console.print("      Задача заморожена, Георгию сформирован алерт в Telegram с ссылкой на тестовое задание.\n")
        await asyncio.sleep(1.8)

        # =====================================================================
        # СТАДИЯ 6: Дегустация и Книга рецептов (Feedback & lessons.md)
        # =====================================================================
        console.print("\n[bold yellow]═══════════════════════════════════════════════════════════════[/bold yellow]")
        console.print("[bold yellow]📖 СТАДИЯ 6: ДЕГУСТАЦИЯ И КНИГА РЕЦЕПТОВ (FEEDBACK & LESSONS)[/bold yellow]")
        console.print("[dim]Фиксация результатов в SQLite и обновление живого опыта[/dim]\n")

        with console.status("[cyan]Отправка сводки в Telegram и сохранение опыта...[/cyan]"):
            await asyncio.sleep(1.4)

        tg_card = (
            "🎯 <b>HH.RU HARNESS: СВОДКА СЕССИИ ДЛЯ ГЕОРГИЯ (AI ENGINEER)</b>\n\n"
            "• Вакансия <b>NeuraTech AI Labs</b> (AI-агенты, 9.6/10): Готов отклик с письмом\n"
            "• Вакансия <b>RoboCore Dynamics</b> (8.3/10): Требует вашего участия (архитектурный тест)\n"
            "• Мусор (разметчик данных): 1 вакансия отсеяна мгновенно\n\n"
            "👉 <b>Запись в config/lessons.md:</b>\n"
            "<i>«Работодатели в сфере AI-агентов максимально высоко конвертируют отклики с упоминанием мульти-агентной системы MOGE и ссылкой на GitHub 14Segun88»</i>"
        )
        console.print(Panel(tg_card, title="📱 Telegram Уведомление на вашем телефоне", border_style="magenta"))

        console.print("\n[bold green]✔ ДЕМОНСТРАЦИЯ УСПЕШНО ЗАВЕРШЕНА![/bold green]")
        console.print("[dim]Все 6 стадий отработали синхронно в рамках строгих контрактов и нулевого расхода лишней памяти.[/dim]\n")
