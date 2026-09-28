from __future__ import annotations

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
            await db.commit()

    async def vacancy_exists(self, hh_id: str) -> bool:
        """Check if vacancy was already processed (parameterized query)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM vacancies WHERE hh_id = ? LIMIT 1", (hh_id,)
            )
            row = await cursor.fetchone()
            return row is not None

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
                    dossier, verdict, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hh_id) DO UPDATE SET
                    score = excluded.score,
                    red_flags = excluded.red_flags,
                    extracted_stack = excluded.extracted_stack,
                    dossier = excluded.dossier,
                    verdict = excluded.verdict,
                    status = excluded.status,
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
