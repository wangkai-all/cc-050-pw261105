"""逐字段合并引擎。

核心原则：
- 缺字段 = 未提供；显式 null 是否清空由字段规则 null_handling 决定。
- 时间统一归一到 UTC 后比较。
- 只有配置明确"各来源共用同一套业务版本号"时，才按版本号比较新旧；
  否则版本号仅作展示，绝不用两套独立编号判断新旧。
- 按所选规则仍分不出先后的不同值，保留为冲突（conflict）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

MISSING = object()  # 字段未提供


def parse_ts(ts: str | None) -> datetime | None:
    """解析带时区的 ISO 时间并归一到 UTC；无法解析返回 None。"""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # 无时区的一律按 UTC 处理
    return dt.astimezone(timezone.utc)


def build_candidates(records: list[dict], field: str, mappings: dict, rule: dict) -> list[dict]:
    """从来源记录中抽取某字段的候选值。

    records: [{id, source, batch, payload, version, updated_at}]
    mappings: {source_name: {canonical_field: source_key}}
    """
    candidates = []
    for rec in records:
        src_key = mappings.get(rec["source"], {}).get(field)
        provided = False
        value = None
        if src_key is not None and src_key in rec["payload"]:
            raw = rec["payload"][src_key]
            if raw is None and rule["null_handling"] == "ignore":
                provided = False  # 显式 null 按规则视为未提供
            else:
                provided = True
                value = raw  # null_handling == clear 时 None 也是有效候选（主动清空）
        ts = parse_ts(rec.get("updated_at"))
        candidates.append({
            "source_record_id": rec["id"],
            "source": rec["source"],
            "batch": rec["batch"],
            "provided": provided,
            "value": value if provided else None,
            "updated_at_utc": ts.isoformat() if ts else None,
            "version": rec.get("version"),
        })
    return candidates


def _value_key(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def fingerprint(candidates: list[dict], rule: dict, shared_version_scheme: bool) -> str:
    """裁决沿用依据：候选值、字段规则、比较依据三者任一变化则指纹变化。"""
    basis = {
        "candidates": [
            {
                "source": c["source"],
                "provided": c["provided"],
                "value": c["value"],
                "updated_at_utc": c["updated_at_utc"],
                "version": c["version"],
            }
            for c in candidates
        ],
        "rule": {
            "strategy": rule["strategy"],
            "priority": rule["priority"],
            "null_handling": rule["null_handling"],
        },
        "shared_version_scheme": shared_version_scheme,
    }
    blob = json.dumps(basis, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _version_key(v):
    """版本号比较键：纯数字按数值比，否则按字符串。仅在共用版本体系下才会被调用。"""
    s = str(v)
    return (0, int(s)) if s.isdigit() else (1, s)


def resolve(candidates: list[dict], rule: dict, shared_version_scheme: bool) -> dict:
    """按规则自动裁决。返回 {status, final_value, decision}；分不出先后则 conflict。"""
    provided = [c for c in candidates if c["provided"]]
    if not provided:
        return {"status": "auto", "final_value": None,
                "decision": {"type": "auto", "reason": "所有来源均未提供该字段"}}

    distinct = {_value_key(c["value"]) for c in provided}
    if len(distinct) == 1:
        return {"status": "auto", "final_value": provided[0]["value"],
                "decision": {"type": "auto", "reason": "各来源取值一致"}}

    strategy = rule["strategy"]

    if strategy == "source_priority":
        for src in rule["priority"]:
            for c in provided:
                if c["source"] == src:
                    return {"status": "auto", "final_value": c["value"],
                            "decision": {"type": "auto",
                                         "reason": f"按来源优先级取自 {src}",
                                         "source_record_id": c["source_record_id"]}}
        # 优先级表外的来源提供了值 —— 规则覆盖不到，分不出先后
        return {"status": "conflict", "final_value": None,
                "decision": {"type": "auto", "reason": "提供值的来源不在优先级表中"}}

    if strategy == "latest_update":
        use_version = (shared_version_scheme
                       and all(c.get("version") not in (None, "") for c in provided))
        if use_version:
            keyfn = lambda c: _version_key(c["version"])
            basis = "共用业务版本号"
        else:
            # 时间统一归一到 UTC 后比较（build_candidates 已归一）
            if any(c["updated_at_utc"] is None for c in provided):
                return {"status": "conflict", "final_value": None,
                        "decision": {"type": "auto", "reason": "部分候选缺少可比较的更新时间"}}
            keyfn = lambda c: c["updated_at_utc"]
            basis = "更新时间(UTC)"
        best = max(provided, key=keyfn)
        tied = [c for c in provided if keyfn(c) == keyfn(best)]
        tied_values = {_value_key(c["value"]) for c in tied}
        if len(tied) > 1 and len(tied_values) > 1:
            return {"status": "conflict", "final_value": None,
                    "decision": {"type": "auto",
                                 "reason": f"按{basis}并列最新但取值不同，无法分出先后"}}
        return {"status": "auto", "final_value": best["value"],
                "decision": {"type": "auto",
                             "reason": f"按{basis}取最新（来自 {best['source']}）",
                             "source_record_id": best["source_record_id"]}}

    # manual：有分歧一律交人工
    return {"status": "conflict", "final_value": None,
            "decision": {"type": "auto", "reason": "字段规则为人工裁决且来源取值不一致"}}
