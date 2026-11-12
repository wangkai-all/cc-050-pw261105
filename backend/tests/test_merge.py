"""合并引擎语义测试：缺失/显式null、时区归一、版本比较限制、冲突保留、裁决沿用。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.merge import build_candidates, fingerprint, parse_ts, resolve

RULES = {
    "priority": {"strategy": "source_priority", "priority": ["crm", "erp", "web"],
                 "null_handling": "ignore"},
    "latest": {"strategy": "latest_update", "priority": [], "null_handling": "ignore"},
    "latest_clear": {"strategy": "latest_update", "priority": [], "null_handling": "clear"},
    "manual": {"strategy": "manual", "priority": [], "null_handling": "ignore"},
}
MAP = {"crm": {"f": "f"}, "erp": {"f": "f"}, "web": {"f": "f"}}


def rec(i, src, payload, updated="2026-11-10T00:00:00Z", version=None):
    return {"id": i, "source": src, "batch": f"{src}.json", "payload": payload,
            "version": version, "updated_at": updated}


def test_timezone_normalization():
    # +08:00 的 10:00 == UTC 02:00，早于 UTC 03:00
    assert parse_ts("2026-11-10T10:00:00+08:00") < parse_ts("2026-11-10T03:00:00Z")


def test_missing_field_is_not_provided():
    cands = build_candidates([rec(1, "crm", {})], "f", MAP, RULES["latest"])
    assert cands[0]["provided"] is False
    r = resolve(cands, RULES["latest"], False)
    assert r["status"] == "auto" and r["final_value"] is None


def test_explicit_null_ignored_by_default():
    cands = build_candidates([rec(1, "crm", {"f": None})], "f", MAP, RULES["latest"])
    assert cands[0]["provided"] is False


def test_explicit_null_clears_when_rule_says_clear():
    recs = [rec(1, "crm", {"f": 1000}, "2026-11-10T02:00:00Z"),
            rec(2, "erp", {"f": None}, "2026-11-10T03:00:00Z")]
    cands = build_candidates(recs, "f", MAP, RULES["latest_clear"])
    r = resolve(cands, RULES["latest_clear"], False)
    assert r["status"] == "auto" and r["final_value"] is None  # 更晚的显式 null 清空生效


def test_late_arriving_old_record_loses():
    # web 版本号 99 但更新时间是旧的 —— 独立编号体系下不得按版本判断新旧
    recs = [rec(1, "erp", {"f": "new"}, "2026-11-10T03:00:00Z", version="7"),
            rec(2, "web", {"f": "old"}, "2026-11-01T00:00:00Z", version="99")]
    cands = build_candidates(recs, "f", MAP, RULES["latest"])
    r = resolve(cands, RULES["latest"], False)
    assert r["final_value"] == "new"


def test_version_used_only_when_shared_scheme():
    recs = [rec(1, "erp", {"f": "v7"}, "2026-11-10T03:00:00Z", version="7"),
            rec(2, "web", {"f": "v99"}, "2026-11-01T00:00:00Z", version="99")]
    cands = build_candidates(recs, "f", MAP, RULES["latest"])
    assert resolve(cands, RULES["latest"], True)["final_value"] == "v99"   # 共用体系：按版本
    assert resolve(cands, RULES["latest"], False)["final_value"] == "v7"   # 独立编号：按时间


def test_same_instant_different_values_conflict():
    recs = [rec(1, "crm", {"f": "a"}, "2026-11-10T10:00:00+08:00"),
            rec(2, "erp", {"f": "b"}, "2026-11-10T02:00:00Z")]  # 同一时刻
    cands = build_candidates(recs, "f", MAP, RULES["latest"])
    r = resolve(cands, RULES["latest"], False)
    assert r["status"] == "conflict"


def test_manual_rule_conflicts_on_disagreement_only():
    recs = [rec(1, "crm", {"f": "x"}), rec(2, "erp", {"f": "y"})]
    cands = build_candidates(recs, "f", MAP, RULES["manual"])
    assert resolve(cands, RULES["manual"], False)["status"] == "conflict"
    recs2 = [rec(1, "crm", {"f": "x"}), rec(2, "erp", {"f": "x"})]
    cands2 = build_candidates(recs2, "f", MAP, RULES["manual"])
    assert resolve(cands2, RULES["manual"], False)["status"] == "auto"


def test_source_priority_picks_highest_providing_source():
    recs = [rec(1, "erp", {"f": "from_erp"}), rec(2, "web", {"f": "from_web"})]
    cands = build_candidates(recs, "f", MAP, RULES["priority"])
    r = resolve(cands, RULES["priority"], False)
    assert r["final_value"] == "from_erp"  # crm 未提供，落到 erp


def test_fingerprint_sensitive_to_candidates_rules_and_basis():
    recs = [rec(1, "crm", {"f": "x"})]
    cands = build_candidates(recs, "f", MAP, RULES["latest"])
    fp = fingerprint(cands, RULES["latest"], False)
    assert fp != fingerprint(cands, RULES["latest"], True)          # 比较依据变
    assert fp != fingerprint(cands, RULES["latest_clear"], False)   # 规则变
    cands2 = build_candidates([rec(1, "crm", {"f": "y"})], "f", MAP, RULES["latest"])
    assert fp != fingerprint(cands2, RULES["latest"], False)        # 候选变
    cands3 = build_candidates([rec(1, "crm", {"f": "x"})], "f", MAP, RULES["latest"])
    assert fp == fingerprint(cands3, RULES["latest"], False)        # 都没变 → 一致
