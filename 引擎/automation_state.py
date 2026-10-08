# -*- coding: utf-8 -*-
"""自动化运行的本地去重与重试状态。"""
import datetime
import os
import sqlite3


def now_text():
    return datetime.datetime.now().isoformat(timespec="seconds")


class AutomationState:
    def __init__(self, root):
        self.path = os.path.join(root, "报告", "自动化状态.db")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS news_items (
                news_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT,
                status TEXT NOT NULL,
                error TEXT,
                input_folder TEXT,
                draft_folder TEXT,
                first_seen_at TEXT NOT NULL,
                last_attempt_at TEXT NOT NULL,
                last_success_at TEXT
            )
        """)
        self.db.commit()

    def get(self, key):
        row = self.db.execute(
            "SELECT news_key,url,title,source,status,error,input_folder,draft_folder "
            ",first_seen_at,last_attempt_at,last_success_at "
            "FROM news_items WHERE news_key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        return dict(zip(("news_key", "url", "title", "source", "status", "error",
                         "input_folder", "draft_folder", "first_seen_at",
                         "last_attempt_at", "last_success_at"), row))

    def has_success_for_url(self, url):
        row = self.db.execute(
            "SELECT news_key,title,status FROM news_items WHERE url = ? AND status = 'success' "
            "ORDER BY last_success_at DESC LIMIT 1", (url,)
        ).fetchone()
        return row

    def mark(self, key, record, status, error="", input_folder="", draft_folder=""):
        now = now_text()
        previous = self.get(key)
        first_seen = previous and previous.get("first_seen_at") or now
        success_at = now if status == "success" else (previous and previous.get("last_success_at"))
        self.db.execute("""
            INSERT INTO news_items(
                news_key,url,title,source,status,error,input_folder,draft_folder,
                first_seen_at,last_attempt_at,last_success_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(news_key) DO UPDATE SET
                url=excluded.url, title=excluded.title, source=excluded.source,
                status=excluded.status, error=excluded.error,
                input_folder=excluded.input_folder, draft_folder=excluded.draft_folder,
                last_attempt_at=excluded.last_attempt_at,
                last_success_at=excluded.last_success_at
        """, (
            key, record.get("link", ""), record.get("title", ""), record.get("source", ""),
            status, error, input_folder, draft_folder, first_seen, now, success_at,
        ))
        self.db.commit()

    def close(self):
        self.db.close()
