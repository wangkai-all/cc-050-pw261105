"""默认配置与源文件导入。"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .db import j, unj

SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"

DEFAULT_CONFIG = {
    "business_key_field": "customer_id",
    "shared_version_scheme": False,  # crm/erp/web 各自独立编号，不允许按版本号比新旧
    "field_mappings": {
        "crm": {"name": "customer_name", "address": "addr", "phone": "phone",
                "email": "email", "status": "status", "credit_limit": "credit_limit"},
        "erp": {"name": "name", "address": "address", "phone": "tel",
                "email": "email", "status": "status", "credit_limit": "credit"},
        "web": {"name": "fullName", "address": "address1", "phone": "phone",
                "email": "email", "status": "tier", "credit_limit": "limit"},
    },
}

DEFAULT_RULES = [
    {"field": "name", "strategy": "source_priority", "priority": ["crm", "erp", "web"],
     "null_handling": "ignore"},
    {"field": "address", "strategy": "source_priority", "priority": ["erp", "crm", "web"],
     "null_handling": "ignore"},
    {"field": "phone", "strategy": "latest_update", "priority": [],
     "null_handling": "ignore"},
    {"field": "email", "strategy": "latest_update", "priority": [],
     "null_handling": "ignore"},
    {"field": "status", "strategy": "manual", "priority": [],
     "null_handling": "ignore"},
    {"field": "credit_limit", "strategy": "latest_update", "priority": [],
     "null_handling": "clear"},  # 显式 null 表示主动清空
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_config(conn) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO merge_config (id, business_key_field, shared_version_scheme, field_mappings)"
        " VALUES (1, ?, ?, ?)",
        (DEFAULT_CONFIG["business_key_field"], int(DEFAULT_CONFIG["shared_version_scheme"]),
         j(DEFAULT_CONFIG["field_mappings"])))
    for r in DEFAULT_RULES:
        conn.execute(
            "INSERT OR REPLACE INTO field_rules (field, strategy, priority, null_handling)"
            " VALUES (?, ?, ?, ?)",
            (r["field"], r["strategy"], j(r["priority"]), r["null_handling"]))
    conn.commit()


def import_source_file(conn, path: Path) -> int:
    """导入一个源文件作为一个批次，原始 payload 原样保留。返回记录数。"""
    doc = json.loads(path.read_text(encoding="utf-8"))
    src = doc["source"]
    conn.execute("INSERT OR IGNORE INTO sources (name, description) VALUES (?, ?)",
                 (src, doc.get("description", "")))
    source_id = conn.execute("SELECT id FROM sources WHERE name = ?", (src,)).fetchone()["id"]
    batch = path.name
    n = 0
    for rec in doc["records"]:
        conn.execute(
            "INSERT INTO source_records (source_id, batch, business_key, payload, version, updated_at, received_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source_id, batch, rec["business_key"], j(rec["payload"]),
             rec.get("version"), rec.get("updated_at"),
             rec.get("received_at") or now_utc()))
        n += 1
    conn.commit()
    return n


def load_config(conn) -> dict:
    row = conn.execute("SELECT * FROM merge_config WHERE id = 1").fetchone()
    return {"business_key_field": row["business_key_field"],
            "shared_version_scheme": bool(row["shared_version_scheme"]),
            "field_mappings": unj(row["field_mappings"])}


def load_rules(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM field_rules ORDER BY field").fetchall()
    return [{"field": r["field"], "strategy": r["strategy"],
             "priority": unj(r["priority"]), "null_handling": r["null_handling"]}
            for r in rows]
