from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import aiosqlite
from hh_agent.config import settings


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.db_path

    async def init_db(self) -> None:
        """Initialize database tables with parameterized schemas and indices."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS vacancies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hh_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    company_name TEXT,
                    company_url TEXT,
                    salary_raw TEXT,
                    salary_min INTEGER,
                    salary_max INTEGER,
                    currency TEXT,
                    url TEXT NOT NULL,
                    description TEXT,
                    published_at TEXT,
                    score INTEGER DEFAULT 0,
                    red_flags TEXT,
                    extracted_stack TEXT,
                    dossier TEXT,
                    verdict TEXT,
                    status TEXT DEFAULT 'NEW',
                    applied_at TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vacancies_hh_id ON vacancies(hh_id);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vacancies_status ON vacancies(status);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vacancies_score ON vacancies(score);"
            )
            try:
                await db.execute("ALTER TABLE vacancies ADD COLUMN scenario TEXT DEFAULT 'DIRECT';")
            except Exception:
                pass

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS negotiations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hh_topic_id TEXT UNIQUE NOT NULL,
                    company_name TEXT,
                    vacancy_title TEXT,
                    vacancy_url TEXT,
                    last_message_text TEXT,
                    last_message_sender TEXT,
                    last_message_time TEXT,
                    classification TEXT,
                    extracted_questions TEXT,
                    extracted_dates TEXT,
                    drafted_response TEXT,
                    status TEXT DEFAULT 'UNREAD',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiations_topic ON negotiations(hh_topic_id);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_negotiations_status ON negotiations(status);"
            )

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS questionnaires (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hh_vacancy_id TEXT NOT NULL,
                    questions_json TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    status TEXT DEFAULT 'PARSED',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS funnel_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    all_count INTEGER DEFAULT 0,
                    interview_count INTEGER DEFAULT 0,
                    job_offer_count INTEGER DEFAULT 0,
                    waiting_count INTEGER DEFAULT 0,
                    discard_count INTEGER DEFAULT 0,
                    archive_count INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS crm_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tg_vacancies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT UNIQUE NOT NULL,
                    channel_name TEXT NOT NULL,
                    post_url TEXT NOT NULL,
                    published_at TEXT,
                    title TEXT,
                    company_name TEXT,
                    raw_text TEXT NOT NULL,
                    contact_type TEXT,
                    contact_target TEXT,
                    all_links TEXT,
                    all_mentions TEXT,
                    score INTEGER DEFAULT 0,
                    extracted_stack TEXT,
                    drafted_pitch TEXT,
                    status TEXT DEFAULT 'NEW',
                    applied_at TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tg_vacancies_post_id ON tg_vacancies(post_id);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tg_vacancies_channel ON tg_vacancies(channel_name);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tg_vacancies_status ON tg_vacancies(status);"
            )
            await db.commit()

    async def vacancy_exists(self, hh_id: str) -> bool:
        """Check if vacancy was already processed (parameterized query)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM vacancies WHERE hh_id = ? LIMIT 1", (hh_id,)
            )
            row = await cursor.fetchone()
            return row is not None

    async def is_applied(self, hh_id: str) -> bool:
        """Check if vacancy was already applied to (status='APPLIED' or applied_at not null)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM vacancies WHERE hh_id = ? AND (status = 'APPLIED' OR applied_at IS NOT NULL) LIMIT 1",
                (hh_id,),
            )
            row = await cursor.fetchone()
            return row is not None

    async def is_processed(self, hh_id: str) -> bool:
        """Check if vacancy was already processed (APPLIED, DISQUALIFIED, SKIPPED, or has applied_at)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT 1 FROM vacancies 
                WHERE hh_id = ? AND (
                    status IN ('APPLIED', 'DISQUALIFIED', 'SKIPPED') 
                    OR applied_at IS NOT NULL
                ) LIMIT 1
                """,
                (hh_id,),
            )
            row = await cursor.fetchone()
            return row is not None

    async def get_session_applied_ids(self) -> set[str]:
        """Return set of hh_ids that were applied to in this agent's campaign/sessions."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT hh_id FROM vacancies 
                WHERE status IN ('APPLIED', 'REJECTED', 'VIEWED', 'INTERVIEW', 'INVITATION', 'ОТКАЗ') 
                   OR applied_at IS NOT NULL
                """
            )
            rows = await cursor.fetchall()
            return {str(row[0]) for row in rows if row[0]}

    async def get_session_company_names(self) -> set[str]:
        """Return set of lowercase company names applied to in this agent's campaign/sessions."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT company_name FROM vacancies 
                WHERE status IN ('APPLIED', 'REJECTED', 'VIEWED', 'INTERVIEW', 'INVITATION', 'ОТКАЗ') 
                   OR applied_at IS NOT NULL
                """
            )
            rows = await cursor.fetchall()
            return {str(row[0]).strip().lower() for row in rows if row[0]}

    async def mark_disqualified(
        self, hh_id: str, title: str, company: str, reason: str, url: str = ""
    ) -> None:
        """Record disqualified vacancy so it is permanently skipped in future searches."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO vacancies (hh_id, title, company_name, url, verdict, status)
                VALUES (?, ?, ?, ?, ?, 'DISQUALIFIED')
                ON CONFLICT(hh_id) DO UPDATE SET
                    verdict = excluded.verdict,
                    status = 'DISQUALIFIED',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (hh_id, title or "Без названия", company or "Работодатель", url or f"https://hh.ru/vacancy/{hh_id}", reason),
            )
            await db.commit()

    async def mark_skipped(
        self, hh_id: str, title: str, company: str, reason: str, url: str = ""
    ) -> None:
        """Record skipped vacancy so it is not re-opened in future searches."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO vacancies (hh_id, title, company_name, url, verdict, status)
                VALUES (?, ?, ?, ?, ?, 'SKIPPED')
                ON CONFLICT(hh_id) DO UPDATE SET
                    verdict = excluded.verdict,
                    status = 'SKIPPED',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (hh_id, title or "Без названия", company or "Работодатель", url or f"https://hh.ru/vacancy/{hh_id}", reason),
            )
            await db.commit()

    async def save_vacancy(self, data: Dict[str, Any]) -> int:
        """Insert or update vacancy details using parameterized statement."""
        red_flags_str = (
            json.dumps(data.get("red_flags", []), ensure_ascii=False)
            if isinstance(data.get("red_flags"), list)
            else (data.get("red_flags") or "[]")
        )
        stack_str = (
            json.dumps(data.get("extracted_stack", []), ensure_ascii=False)
            if isinstance(data.get("extracted_stack"), list)
            else (data.get("extracted_stack") or "[]")
        )

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO vacancies (
                    hh_id, title, company_name, company_url, salary_raw,
                    salary_min, salary_max, currency, url, description,
                    published_at, score, red_flags, extracted_stack,
                    dossier, verdict, status, scenario
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hh_id) DO UPDATE SET
                    score = excluded.score,
                    red_flags = excluded.red_flags,
                    extracted_stack = excluded.extracted_stack,
                    dossier = excluded.dossier,
                    verdict = excluded.verdict,
                    status = excluded.status,
                    scenario = COALESCE(excluded.scenario, vacancies.scenario),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    data["hh_id"],
                    data.get("title", "Без названия"),
                    data.get("company_name", ""),
                    data.get("company_url", ""),
                    data.get("salary_raw", ""),
                    data.get("salary_min"),
                    data.get("salary_max"),
                    data.get("currency", "RUR"),
                    data.get("url", ""),
                    data.get("description", ""),
                    data.get("published_at", ""),
                    data.get("score", 0),
                    red_flags_str,
                    stack_str,
                    data.get("dossier", ""),
                    data.get("verdict", ""),
                    data.get("status", "NEW"),
                    data.get("scenario", "⚡ 1-Клик"),
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def update_vacancy_status(
        self, hh_id: str, status: str, applied: bool = False
    ) -> None:
        """Update vacancy status and application timestamp securely."""
        async with aiosqlite.connect(self.db_path) as db:
            if applied:
                await db.execute(
                    """
                    UPDATE vacancies 
                    SET status = ?, applied_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE hh_id = ?
                    """,
                    (status, hh_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE vacancies 
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE hh_id = ?
                    """,
                    (status, hh_id),
                )
            await db.commit()

    async def get_vacancies_for_review(self, min_score: int = 70) -> List[Dict[str, Any]]:
        """Retrieve top candidate vacancies for review or digest."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM vacancies 
                WHERE score >= ? AND status IN ('DOSSIER_READY', 'QUALIFIED')
                ORDER BY score DESC, created_at DESC
                LIMIT 50
                """,
                (min_score,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def save_negotiation(self, data: Dict[str, Any]) -> int:
        """Insert or update negotiation conversation item."""
        q_str = json.dumps(data.get("extracted_questions", []), ensure_ascii=False)
        d_str = json.dumps(data.get("extracted_dates", []), ensure_ascii=False)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO negotiations (
                    hh_topic_id, company_name, vacancy_title, vacancy_url,
                    last_message_text, last_message_sender, last_message_time,
                    classification, extracted_questions, extracted_dates,
                    drafted_response, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hh_topic_id) DO UPDATE SET
                    last_message_text = excluded.last_message_text,
                    last_message_sender = excluded.last_message_sender,
                    last_message_time = excluded.last_message_time,
                    classification = excluded.classification,
                    extracted_questions = excluded.extracted_questions,
                    extracted_dates = excluded.extracted_dates,
                    drafted_response = excluded.drafted_response,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    data["hh_topic_id"],
                    data.get("company_name", ""),
                    data.get("vacancy_title", ""),
                    data.get("vacancy_url", ""),
                    data.get("last_message_text", ""),
                    data.get("last_message_sender", "employer"),
                    data.get("last_message_time", ""),
                    data.get("classification", "OTHER"),
                    q_str,
                    d_str,
                    data.get("drafted_response", ""),
                    data.get("status", "UNREAD"),
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_unread_negotiations(self) -> List[Dict[str, Any]]:
        """Retrieve negotiations needing review or reply."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM negotiations 
                WHERE status IN ('UNREAD', 'DRAFTED')
                ORDER BY updated_at DESC
                """
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def save_questionnaire(
        self, hh_vacancy_id: str, questions: List[Dict[str, Any]], answers: Dict[str, Any]
    ) -> int:
        """Store employer questionnaire questions and mapped answers."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO questionnaires (hh_vacancy_id, questions_json, answers_json, status)
                VALUES (?, ?, ?, 'ANSWERED')
                """,
                (
                    hh_vacancy_id,
                    json.dumps(questions, ensure_ascii=False),
                    json.dumps(answers, ensure_ascii=False),
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def get_stats_summary(self) -> Dict[str, int]:
        """Get summary statistics for daily digest."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM vacancies")
            (total_vacancies,) = await cursor.fetchone() or (0,)

            cursor = await db.execute(
                "SELECT COUNT(*) FROM vacancies WHERE status = 'APPLIED'"
            )
            (applied_count,) = await cursor.fetchone() or (0,)

            cursor = await db.execute(
                "SELECT COUNT(*) FROM vacancies WHERE score >= 70"
            )
            (top_score_count,) = await cursor.fetchone() or (0,)

            cursor = await db.execute(
                "SELECT COUNT(*) FROM negotiations WHERE classification = 'INVITATION'"
            )
            (invitations_count,) = await cursor.fetchone() or (0,)

            return {
                "total_vacancies": total_vacancies,
                "applied_count": applied_count,
                "top_score_count": top_score_count,
                "invitations_count": invitations_count,
            }

    async def get_crm_metrics(self) -> Dict[str, Any]:
        """Compute full CRM pipeline metrics for Telegram Bitrix24 dashboard."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # 1. Total days active (since first vacancy created_at or today)
            cursor = await db.execute("SELECT MIN(created_at) FROM vacancies")
            (first_date,) = await cursor.fetchone() or (None,)
            days_active = 1
            if first_date:
                try:
                    dt = datetime.datetime.fromisoformat(str(first_date)[:19])
                    days_active = max(1, (datetime.datetime.now() - dt).days + 1)
                except Exception:
                    days_active = 1

            # 2. Total applied today
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM vacancies 
                WHERE (applied_at IS NOT NULL AND DATE(applied_at) = DATE('now', 'localtime'))
                   OR (status = 'APPLIED' AND (DATE(applied_at) = DATE('now', 'localtime') OR DATE(updated_at) = DATE('now', 'localtime')))
                """
            )
            (today_applied_total,) = await cursor.fetchone() or (0,)

            # 3. Breakdown of today's applied by scenario
            cursor = await db.execute(
                """
                SELECT scenario, COUNT(*) as cnt FROM vacancies 
                WHERE (applied_at IS NOT NULL AND DATE(applied_at) = DATE('now', 'localtime'))
                   OR (status = 'APPLIED' AND (DATE(applied_at) = DATE('now', 'localtime') OR DATE(updated_at) = DATE('now', 'localtime')))
                GROUP BY scenario
                """
            )
            rows = await cursor.fetchall()
            scenario_counts = {str(row["scenario"] or ""): row["cnt"] for row in rows}

            today_direct = 0
            today_questionnaire = 0
            today_test_task = 0

            for sc, cnt in scenario_counts.items():
                sc_lower = sc.lower()
                if any(k in sc_lower for k in ["тестов", "test", "форма", "google"]):
                    today_test_task += cnt
                elif any(k in sc_lower for k in ["анкет", "вопрос", "question"]):
                    today_questionnaire += cnt
                else:
                    today_direct += cnt

            if (today_direct + today_questionnaire + today_test_task) < today_applied_total:
                today_direct += (today_applied_total - (today_direct + today_questionnaire + today_test_task))

            # 4. Total rejections
            cursor = await db.execute(
                "SELECT COUNT(*) FROM vacancies WHERE status IN ('REJECTED', 'ОТКАЗ')"
            )
            (vac_rejections,) = await cursor.fetchone() or (0,)
            cursor = await db.execute(
                "SELECT COUNT(*) FROM negotiations WHERE status IN ('REJECTED', 'ОТКАЗ') OR classification = 'REJECTION'"
            )
            (neg_rejections,) = await cursor.fetchone() or (0,)
            total_rejections = max(vac_rejections, neg_rejections)

            # 5. Total invitations / interviews (strictly from verified green badge on hh.ru)
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM negotiations 
                WHERE status IN ('INVITATION', 'СОБЕСЕДОВАНИЕ', 'ПРИГЛАШЕНИЕ')
                """
            )
            (neg_invitations,) = await cursor.fetchone() or (0,)
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM vacancies 
                WHERE status IN ('INVITATION', 'INTERVIEW', 'СОБЕСЕДОВАНИЕ', 'ПРИГЛАШЕНИЕ')
                """
            )
            (vac_invitations,) = await cursor.fetchone() or (0,)
            total_invitations = max(neg_invitations, vac_invitations)

            # 6. Total vacancies in CRM
            cursor = await db.execute("SELECT COUNT(*) FROM vacancies")
            (total_vacancies,) = await cursor.fetchone() or (0,)

            # 7. Active chats
            cursor = await db.execute(
                "SELECT COUNT(*) FROM negotiations WHERE status IN ('REPLIED', 'UNREAD', 'DRAFTED')"
            )
            (active_chats,) = await cursor.fetchone() or (0,)

            # 8. HH.RU Funnel tabs metrics
            funnel = await self.get_funnel_metrics()

            # 9. Telegram Channel Outreach metrics
            tg_metrics = await self.get_tg_crm_metrics()

            return {
                "days_active": days_active,
                "today_applied_total": today_applied_total,
                "today_direct": today_direct,
                "today_questionnaire": today_questionnaire,
                "today_test_task": today_test_task,
                "total_rejections": total_rejections,
                "total_invitations": total_invitations,
                "total_vacancies": total_vacancies,
                "active_chats": active_chats,
                "funnel_all": funnel.get("all_count", 0),
                "funnel_interview": funnel.get("interview_count", 0),
                "funnel_job_offer": funnel.get("job_offer_count", 0),
                "funnel_waiting": funnel.get("waiting_count", 0),
                "funnel_discard": funnel.get("discard_count", 0),
                "funnel_archive": funnel.get("archive_count", 0),
                **tg_metrics,
            }

    async def save_funnel_metrics(self, metrics: Dict[str, int]) -> None:
        """Persist latest funnel statistics extracted from hh.ru negotiations tabs."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO funnel_metrics (
                    all_count, interview_count, job_offer_count,
                    waiting_count, discard_count, archive_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    metrics.get("all_count", 0),
                    metrics.get("interview_count", 0),
                    metrics.get("job_offer_count", 0),
                    metrics.get("waiting_count", 0),
                    metrics.get("discard_count", 0),
                    metrics.get("archive_count", 0),
                ),
            )
            await db.commit()

    async def get_funnel_metrics(self) -> Dict[str, int]:
        """Retrieve latest funnel metrics scanned from hh.ru tabs."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT all_count, interview_count, job_offer_count,
                       waiting_count, discard_count, archive_count
                FROM funnel_metrics
                ORDER BY id DESC LIMIT 1
                """
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "all_count": row["all_count"],
                    "interview_count": row["interview_count"],
                    "job_offer_count": row["job_offer_count"],
                    "waiting_count": row["waiting_count"],
                    "discard_count": row["discard_count"],
                    "archive_count": row["archive_count"],
                }
            return {
                "all_count": 0,
                "interview_count": 0,
                "job_offer_count": 0,
                "waiting_count": 0,
                "discard_count": 0,
                "archive_count": 0,
            }

    async def get_recent_deals(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent applied vacancies as CRM deals."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT hh_id, title, company_name, salary_raw, score, scenario, status, applied_at, url 
                FROM vacancies 
                WHERE status IN ('APPLIED', 'REJECTED', 'VIEWED', 'INTERVIEW', 'INVITATION', 'ОТКАЗ') 
                   OR applied_at IS NOT NULL
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_active_negotiations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve active employer chat negotiations."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT hh_topic_id, company_name, vacancy_title, last_message_text, 
                       classification, drafted_response, status, updated_at
                FROM negotiations
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_last_crm_snapshot(self) -> Optional[Dict[str, Any]]:
        """Retrieve last saved CRM card snapshot."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT value FROM crm_state WHERE key = 'last_crm_snapshot' LIMIT 1")
            row = await cursor.fetchone()
            if row and row[0]:
                try:
                    return json.loads(row[0])
                except Exception:
                    return None
            return None

    async def save_last_crm_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Persist latest CRM card snapshot."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO crm_state (key, value, updated_at)
                VALUES ('last_crm_snapshot', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (json.dumps(snapshot, ensure_ascii=False),),
            )
            await db.commit()

    async def tg_vacancy_exists(self, post_id: str) -> bool:
        """Check if Telegram vacancy post was already saved."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM tg_vacancies WHERE post_id = ? LIMIT 1",
                (post_id,),
            )
            row = await cursor.fetchone()
            return row is not None

    async def save_tg_vacancy(self, tg_vac: Dict[str, Any]) -> int:
        """Insert or update Telegram vacancy record."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO tg_vacancies (
                    post_id, channel_name, post_url, published_at,
                    title, company_name, raw_text, contact_type,
                    contact_target, all_links, all_mentions, score,
                    extracted_stack, drafted_pitch, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(post_id) DO UPDATE SET
                    score = excluded.score,
                    drafted_pitch = excluded.drafted_pitch,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tg_vac.get("post_id"),
                    tg_vac.get("channel_name"),
                    tg_vac.get("post_url"),
                    tg_vac.get("published_at"),
                    tg_vac.get("title"),
                    tg_vac.get("company_name"),
                    tg_vac.get("raw_text", ""),
                    tg_vac.get("contact_type", "UNKNOWN"),
                    tg_vac.get("contact_target", ""),
                    json.dumps(tg_vac.get("all_links", []), ensure_ascii=False),
                    json.dumps(tg_vac.get("all_mentions", []), ensure_ascii=False),
                    tg_vac.get("score", 0),
                    json.dumps(tg_vac.get("extracted_stack", []), ensure_ascii=False),
                    tg_vac.get("drafted_pitch", ""),
                    tg_vac.get("status", "PITCH_READY"),
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0

    async def update_tg_vacancy_status(
        self,
        post_id: str,
        status: str,
        applied: bool = False,
    ) -> None:
        """Update workflow status of a Telegram vacancy (e.g. APPLIED, REPLIED)."""
        applied_at = datetime.datetime.now().isoformat() if applied else None
        async with aiosqlite.connect(self.db_path) as db:
            if applied_at:
                await db.execute(
                    """
                    UPDATE tg_vacancies
                    SET status = ?, applied_at = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE post_id = ?
                    """,
                    (status, applied_at, post_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE tg_vacancies
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE post_id = ?
                    """,
                    (status, post_id),
                )
            await db.commit()

    async def get_tg_vacancies(
        self,
        min_score: int = 50,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieve top Telegram vacancies sorted by score."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM tg_vacancies WHERE score >= ?"
            params: List[Any] = [min_score]
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_tg_crm_metrics(self) -> Dict[str, Any]:
        """Aggregate Telegram vacancy metrics for CRM dashboard."""
        today_iso = datetime.date.today().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM tg_vacancies")
            (total_found,) = await cursor.fetchone() or (0,)

            cursor = await db.execute(
                "SELECT COUNT(*) FROM tg_vacancies WHERE published_at LIKE ?",
                (f"{today_iso}%",),
            )
            (today_found,) = await cursor.fetchone() or (0,)

            cursor = await db.execute(
                "SELECT COUNT(*) FROM tg_vacancies WHERE status = 'APPLIED' AND applied_at LIKE ?",
                (f"{today_iso}%",),
            )
            (today_contacted,) = await cursor.fetchone() or (0,)

            cursor = await db.execute("SELECT COUNT(*) FROM tg_vacancies WHERE status = 'REPLIED'")
            (replied_count,) = await cursor.fetchone() or (0,)

            cursor = await db.execute("SELECT COUNT(*) FROM tg_vacancies WHERE status = 'INTERVIEW'")
            (interview_count,) = await cursor.fetchone() or (0,)

            return {
                "tg_total_found": total_found,
                "tg_today_found": today_found,
                "tg_today_contacted": today_contacted,
                "tg_replied": replied_count,
                "tg_interview": interview_count,
            }


