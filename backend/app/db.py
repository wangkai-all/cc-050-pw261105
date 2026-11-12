"""SQLite 存取层。所有时间以 ISO8601 字符串存储，比较前统一归一到 UTC。"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "merge.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS source_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    batch TEXT NOT NULL,            -- 来源文件/批次名
    business_key TEXT NOT NULL,
    payload TEXT NOT NULL,          -- 原始 JSON，原样保留
    version TEXT,                   -- 来源自带的业务版本号（可能各自独立编号）
    updated_at TEXT,                -- 来源声明的更新时间（带时区）
    received_at TEXT NOT NULL       -- 到达时间
);
CREATE TABLE IF NOT EXISTS merge_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    business_key_field TEXT NOT NULL,
    shared_version_scheme INTEGER NOT NULL DEFAULT 0,  -- 各来源是否共用同一套业务版本号
    field_mappings TEXT NOT NULL    -- {source_name: {canonical_field: source_key}}
);
CREATE TABLE IF NOT EXISTS field_rules (
    field TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,         -- source_priority | latest_update | manual
    priority TEXT NOT NULL DEFAULT '[]',  -- source_priority 策略下的来源顺序
    null_handling TEXT NOT NULL DEFAULT 'ignore'  -- ignore(视为未提供) | clear(显式清空)
);
CREATE TABLE IF NOT EXISTS merge_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'  -- draft | published
);
CREATE TABLE IF NOT EXISTS merge_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES merge_runs(id),
    business_key TEXT NOT NULL,
    field TEXT NOT NULL,
    candidates TEXT NOT NULL,       -- [{source_record_id, source, batch, provided, value, updated_at_utc, version}]
    fingerprint TEXT NOT NULL,      -- 候选+规则+比较依据 的哈希，用于裁决沿用
    status TEXT NOT NULL,           -- auto | conflict | resolved
    final_value TEXT,               -- JSON 编码的最终值
    decision TEXT,                  -- {type, reason, reused} 裁决信息
    UNIQUE (run_id, business_key, field)
);
CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_no INTEGER NOT NULL UNIQUE,
    run_id INTEGER NOT NULL REFERENCES merge_runs(id),
    published_at TEXT NOT NULL,
    snapshot TEXT NOT NULL          -- {business_key: {field: value}}
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def j(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def unj(s: str):
    return json.loads(s)
