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
                "title": "Руководитель отдела продаж (B2B / Консалтинг)",
                "company": "Smart Consulting Group",
                "salary": "180 000 – 250 000 ₽ на руки",
                "type": "B2B продажи, удаленка, управление командой 10+ человек",
            },
            {
                "id": "vac_2",
                "title": "Оператор колл-центра / Менеджер на холодные звонки",
                "company": "БыстроЛид Офис",
                "salary": "30 000 ₽ (оклад 20к + %)",
                "type": "Стоп-слова: оператор, холодные звонки, оклад 20000",
            },
            {
                "id": "vac_3",
                "title": "Head of Sales / Директор по продажам + Анкета",
                "company": "Global FinTech Retail",
                "salary": "220 000 ₽",
                "type": "Высокий чек, но требует заполнить анкету с бизнес-кейсом",
            },
        ]

        table_vac = Table(title="Новые вакансии с hh.ru")
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

        console.print("  ❌ [red]Вакансия №2 (Оператор колл-центра):[/red] Обнаружены стоп-слова: [bold]'Оператор'[/bold], [bold]'Холодные звонки'[/bold].")
        console.print("     [bold red]ВКУС: 0 / 10[/bold red] ➔ [bold]Мгновенно летит в мусорку[/bold] (0 потраченных токенов NIM).\n")
        await asyncio.sleep(0.8)

        console.print("  ✔ [green]Вакансия №1 (РОП B2B Консалтинг):[/green] Профиль РОПа, B2B, удаленка, ЗП 180k–250k (выше целевых 150k).")
        console.print("     [bold green]ВКУС: 9.4 / 10[/bold green] ➔ [bold]Одобрено для глубокого анализа[/bold].\n")
        await asyncio.sleep(0.8)

        console.print("  ✔ [green]Вакансия №3 (Head of Sales + Кейс):[/green] Отличные условия, обнаружена анкета с бизнес-кейсом.")
        console.print("     [bold green]ВКУС: 8.1 / 10[/bold green] ➔ [bold]Одобрено, требуется проверка сценария[/bold].\n")
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
            "**Обзор компании:** Устойчивая консалтинговая B2B-компания, системные продажи услуг для бизнеса.\n"
            "**Плюсы:** Белый оклад 180k + прозрачные KPI за выполнение плана отделом, внедрена AmoCRM, адекватные учредители.\n"
            "**Риски:** Необходимость пересборки системы найма и мотивации действующих менеджеров.\n"
            "**Вердикт NIM:** Рекомендуется откликаться в первую очередь."
        )
        console.print(Panel(Markdown(dossier_text), title="📑 Досье работодателя (NVIDIA NIM)", border_style="green"))

        cover_letter = (
            "Добрый день!\n\n"
            "Более 5 лет работаю в сфере продаж, из них более 3 лет — Руководителем отдела продаж (РОП) "
            "в B2B и консалтинговых услугах. В текущей компании (РБКС) выстроил отдел продаж с нуля: "
            "внедрил сквозные KPI, систему мотивации и стандарты работы в CRM, что позволило обеспечить "
            "стабильное выполнение плановых показателей.\n\n"
            "Имею личный опыт найма, обучения и аттестации менеджеров, а также ведения ключевых сложных сделок с первыми лицами. "
            "Буду рад обсудить цели по выручке вашей компании на интервью."
        )
        console.print(Panel(cover_letter, title="✉ Сгенерированное письмо (Без клише, только реальные факты Георгия)", border_style="cyan"))
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
        console.print("    • Обнаружен бизнес-кейс по продажам: [bold red]ТРЕБУЕТСЯ СТРАТЕГИЯ[/bold red]")
        console.print("    • Политика из specs.yaml: [bold red]REQUIRES_HUMAN (approval: required)[/bold red]")
        console.print("    • [bold yellow]Защитная крышка сработала![/bold yellow] Модель не отправляет решения наугад.")
        console.print("      Задача заморожена, Георгию сформирован алерт в Telegram с ссылкой на анкету.\n")
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
            "🎯 <b>HH.RU HARNESS: СВОДКА СЕССИИ ДЛЯ ГЕОРГИЯ</b>\n\n"
            "• Вакансия <b>Smart Consulting Group</b> (РОП, 9.4/10): Готов отклик с письмом\n"
            "• Вакансия <b>Global FinTech Retail</b> (8.1/10): Требует вашего участия (бизнес-кейс)\n"
            "• Мусор (холодные звонки/оператор): 1 вакансия отсеяна мгновенно\n\n"
            "👉 <b>Запись в config/lessons.md:</b>\n"
            "<i>«В B2B-вакансиях работодатели высоко конвертируют письма с упоминанием опыта внедрения KPI и работы в CRM»</i>"
        )
        console.print(Panel(tg_card, title="📱 Telegram Уведомление на вашем телефоне", border_style="magenta"))

        console.print("\n[bold green]✔ ДЕМОНСТРАЦИЯ УСПЕШНО ЗАВЕРШЕНА![/bold green]")
        console.print("[dim]Все 6 стадий отработали синхронно в рамках строгих контрактов и нулевого расхода лишней памяти.[/dim]\n")
