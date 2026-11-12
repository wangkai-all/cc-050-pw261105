"""FastAPI 入口：配置、源数据、合并草稿、人工裁决、发布、血缘反查。"""
import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .db import connect, init_db, j, unj
from .merge import build_candidates, fingerprint, resolve
from .seed import (SEED_DIR, import_source_file, load_config, load_rules,
                   now_utc, seed_config)

app = FastAPI(title="多源逐字段合并")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def fresh_conn():
    conn = connect()
    init_db(conn)
    return conn


@app.on_event("startup")
def startup():
    conn = fresh_conn()
    # 首次启动：写入默认配置并导入三个源文件
    if conn.execute("SELECT COUNT(*) c FROM merge_config").fetchone()["c"] == 0:
        seed_config(conn)
    if conn.execute("SELECT COUNT(*) c FROM source_records").fetchone()["c"] == 0:
        for f in sorted(SEED_DIR.glob("*.json")):
            import_source_file(conn, f)
    conn.close()


# ---------- 配置 ----------

class ConfigIn(BaseModel):
    business_key_field: str
    shared_version_scheme: bool
    field_mappings: dict[str, dict[str, str]]


@app.get("/api/config")
def get_config():
    conn = fresh_conn()
    cfg = load_config(conn)
    conn.close()
    return cfg


@app.put("/api/config")
def put_config(cfg: ConfigIn):
    conn = fresh_conn()
    conn.execute(
        "UPDATE merge_config SET business_key_field=?, shared_version_scheme=?, field_mappings=? WHERE id=1",
        (cfg.business_key_field, int(cfg.shared_version_scheme), j(cfg.field_mappings)))
    conn.commit()
    conn.close()
    return {"ok": True}


class RuleIn(BaseModel):
    strategy: str
    priority: list[str] = []
    null_handling: str = "ignore"


@app.get("/api/rules")
def get_rules():
    conn = fresh_conn()
    rules = load_rules(conn)
    conn.close()
    return rules


@app.put("/api/rules/{field}")
def put_rule(field: str, rule: RuleIn):
    if rule.strategy not in ("source_priority", "latest_update", "manual"):
        raise HTTPException(400, "strategy 必须是 source_priority / latest_update / manual")
    if rule.null_handling not in ("ignore", "clear"):
        raise HTTPException(400, "null_handling 必须是 ignore / clear")
    conn = fresh_conn()
    conn.execute(
        "INSERT OR REPLACE INTO field_rules (field, strategy, priority, null_handling) VALUES (?,?,?,?)",
        (field, rule.strategy, j(rule.priority), rule.null_handling))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- 来源数据 ----------

@app.get("/api/sources")
def list_sources():
    conn = fresh_conn()
    rows = conn.execute(
        "SELECT s.*, COUNT(r.id) AS record_count FROM sources s"
        " LEFT JOIN source_records r ON r.source_id = s.id GROUP BY s.id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/source-records")
def list_source_records(source: str | None = None):
    conn = fresh_conn()
    q = ("SELECT r.*, s.name AS source FROM source_records r JOIN sources s ON s.id=r.source_id")
    params: list = []
    if source:
        q += " WHERE s.name = ?"
        params.append(source)
    q += " ORDER BY r.business_key, s.name, r.id"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = unj(d["payload"])
        out.append(d)
    return out


@app.get("/api/source-records/{record_id}/impact")
def record_impact(record_id: int, run_id: int | None = None):
    """从源记录反查：它作为候选参与了哪些合并结果，输赢如何。"""
    conn = fresh_conn()
    rec = conn.execute(
        "SELECT r.*, s.name AS source FROM source_records r JOIN sources s ON s.id=r.source_id"
        " WHERE r.id = ?", (record_id,)).fetchone()
    if not rec:
        conn.close()
        raise HTTPException(404, "源记录不存在")
    if run_id is None:
        row = conn.execute("SELECT MAX(id) AS m FROM merge_runs").fetchone()
        run_id = row["m"]
    impacts = []
    if run_id:
        rows = conn.execute("SELECT * FROM merge_results WHERE run_id = ?", (run_id,)).fetchall()
        for r in rows:
            cands = unj(r["candidates"])
            mine = [c for c in cands if c["source_record_id"] == record_id]
            if not mine:
                continue
            c = mine[0]
            final = unj(r["final_value"]) if r["final_value"] is not None else None
            if not c["provided"]:
                outcome = "not_provided"
            elif r["status"] == "conflict":
                outcome = "conflict"
            elif final is not None and json.dumps(final, sort_keys=True) == json.dumps(c["value"], sort_keys=True):
                outcome = "won"
            else:
                outcome = "lost"
            impacts.append({"business_key": r["business_key"], "field": r["field"],
                            "candidate": c, "result_status": r["status"],
                            "final_value": final, "outcome": outcome})
    conn.close()
    return {"record": {**dict(rec), "payload": unj(rec["payload"])},
            "run_id": run_id, "impacts": impacts}


# ---------- 合并运行（草稿） ----------

def _load_records_by_key(conn) -> dict[str, list[dict]]:
    rows = conn.execute(
        "SELECT r.*, s.name AS source FROM source_records r JOIN sources s ON s.id=r.source_id"
        " ORDER BY r.id").fetchall()
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        d = dict(r)
        d["payload"] = unj(d["payload"])
        by_key.setdefault(d["business_key"], []).append(d)
    return by_key


@app.post("/api/runs")
def create_run():
    """生成合并草稿。沿用上轮人工裁决的前提：候选值、字段规则、比较依据均未变（指纹一致）。"""
    conn = fresh_conn()
    cfg = load_config(conn)
    rules = load_rules(conn)
    by_key = _load_records_by_key(conn)

    prev: dict[tuple, sqlite3.Row] = {}
    last = conn.execute("SELECT MAX(id) AS m FROM merge_runs").fetchone()["m"]
    if last is not None:
        for r in conn.execute("SELECT * FROM merge_results WHERE run_id = ?", (last,)).fetchall():
            prev[(r["business_key"], r["field"])] = r

    cur = conn.execute("INSERT INTO merge_runs (created_at, status) VALUES (?, 'draft')",
                       (now_utc(),))
    run_id = cur.lastrowid

    for key, records in sorted(by_key.items()):
        for rule in rules:
            cands = build_candidates(records, rule["field"], cfg["field_mappings"], rule)
            fp = fingerprint(cands, rule, cfg["shared_version_scheme"])
            result = resolve(cands, rule, cfg["shared_version_scheme"])

            old = prev.get((key, rule["field"]))
            if (old and old["fingerprint"] == fp and old["status"] == "resolved"
                    and unj(old["decision"]).get("type") == "manual"):
                # 候选、规则、比较依据都没变 —— 沿用原人工裁决
                old_dec = unj(old["decision"])
                old_dec["reused"] = True
                result = {"status": "resolved", "final_value": unj(old["final_value"]),
                          "decision": old_dec}

            conn.execute(
                "INSERT INTO merge_results (run_id, business_key, field, candidates, fingerprint,"
                " status, final_value, decision) VALUES (?,?,?,?,?,?,?,?)",
                (run_id, key, rule["field"], j(cands), fp, result["status"],
                 j(result["final_value"]), j(result["decision"])))
    conn.commit()
    conn.close()
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs():
    conn = fresh_conn()
    rows = conn.execute("""
        SELECT r.*,
          SUM(CASE WHEN m.status='conflict' THEN 1 ELSE 0 END) AS conflicts,
          SUM(CASE WHEN m.status='resolved' THEN 1 ELSE 0 END) AS resolved,
          COUNT(m.id) AS fields
        FROM merge_runs r LEFT JOIN merge_results m ON m.run_id = r.id
        GROUP BY r.id ORDER BY r.id DESC""").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    """按业务键展开：每个字段的全部候选与最终选择。"""
    conn = fresh_conn()
    run = conn.execute("SELECT * FROM merge_runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        conn.close()
        raise HTTPException(404, "合并运行不存在")
    rows = conn.execute(
        "SELECT * FROM merge_results WHERE run_id = ? ORDER BY business_key, field",
        (run_id,)).fetchall()
    conn.close()
    keys: dict[str, list] = {}
    for r in rows:
        keys.setdefault(r["business_key"], []).append({
            "field": r["field"],
            "status": r["status"],
            "candidates": unj(r["candidates"]),
            "final_value": unj(r["final_value"]) if r["final_value"] is not None else None,
            "decision": unj(r["decision"]) if r["decision"] else None,
            "fingerprint": r["fingerprint"],
        })
    return {"run": dict(run), "keys": keys}


class DecideIn(BaseModel):
    business_key: str
    field: str
    final_value: object = None       # 选中的候选值或人工修正值
    reason: str
    source_record_id: int | None = None  # 若直接选了某个候选


@app.post("/api/runs/{run_id}/decide")
def decide(run_id: int, d: DecideIn):
    if not d.reason.strip():
        raise HTTPException(400, "人工裁决必须填写原因")
    conn = fresh_conn()
    run = conn.execute("SELECT * FROM merge_runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        conn.close()
        raise HTTPException(404, "合并运行不存在")
    if run["status"] == "published":
        conn.close()
        raise HTTPException(409, "该草稿已发布，不能再修改裁决")
    row = conn.execute(
        "SELECT * FROM merge_results WHERE run_id=? AND business_key=? AND field=?",
        (run_id, d.business_key, d.field)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "字段结果不存在")
    decision = {"type": "manual", "reason": d.reason, "reused": False,
                "decided_at": now_utc()}
    if d.source_record_id is not None:
        decision["source_record_id"] = d.source_record_id
    conn.execute(
        "UPDATE merge_results SET status='resolved', final_value=?, decision=?"
        " WHERE run_id=? AND business_key=? AND field=?",
        (j(d.final_value), j(decision), run_id, d.business_key, d.field))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- 发布 ----------

@app.post("/api/runs/{run_id}/publish")
def publish(run_id: int):
    conn = fresh_conn()
    run = conn.execute("SELECT * FROM merge_runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        conn.close()
        raise HTTPException(404, "合并运行不存在")
    if run["status"] == "published":
        conn.close()
        raise HTTPException(409, "该草稿已发布过")
    conflicts = conn.execute(
        "SELECT COUNT(*) c FROM merge_results WHERE run_id=? AND status='conflict'",
        (run_id,)).fetchone()["c"]
    if conflicts:
        conn.close()
        raise HTTPException(409, f"仍有 {conflicts} 个冲突未处理，不能发布")
    rows = conn.execute("SELECT * FROM merge_results WHERE run_id=?", (run_id,)).fetchall()
    snapshot: dict[str, dict] = {}
    for r in rows:
        snapshot.setdefault(r["business_key"], {})[r["field"]] = (
            unj(r["final_value"]) if r["final_value"] is not None else None)
    version_no = (conn.execute("SELECT COALESCE(MAX(version_no),0) v FROM publications")
                  .fetchone()["v"] + 1)
    conn.execute(
        "INSERT INTO publications (version_no, run_id, published_at, snapshot) VALUES (?,?,?,?)",
        (version_no, run_id, now_utc(), j(snapshot)))
    conn.execute("UPDATE merge_runs SET status='published' WHERE id=?", (run_id,))
    conn.commit()
    conn.close()
    return {"version_no": version_no}


@app.get("/api/publications")
def list_publications():
    conn = fresh_conn()
    rows = conn.execute("SELECT id, version_no, run_id, published_at FROM publications"
                        " ORDER BY version_no DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/publications/{version_no}")
def get_publication(version_no: int):
    conn = fresh_conn()
    row = conn.execute("SELECT * FROM publications WHERE version_no=?", (version_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "发布版本不存在")
    d = dict(row)
    d["snapshot"] = unj(d["snapshot"])
    return d


# ---------- 维护 ----------

@app.post("/api/reset")
def reset():
    """清空并重置为初始种子状态（源文件重新导入，发布历史清空）。"""
    conn = fresh_conn()
    for t in ("publications", "merge_results", "merge_runs", "source_records", "sources"):
        conn.execute(f"DELETE FROM {t}")
    seed_config(conn)
    for f in sorted(SEED_DIR.glob("*.json")):
        import_source_file(conn, f)
    conn.close()
    return {"ok": True}


# ---------- 前端静态资源 ----------
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        file = FRONTEND_DIST / full_path
        if full_path and file.exists() and file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
