import { useEffect, useState } from "react";
import { api } from "../api";

const fmtVal = (v) => (v === null || v === undefined ? <span className="null">null</span> : JSON.stringify(v));

function StatusBadge({ status }) {
  const label = { auto: "自动", conflict: "冲突", resolved: "已裁决" }[status];
  return <span className={`badge ${status}`}>{label}</span>;
}

function FieldRow({ runId, runStatus, bizKey, field, onDecided }) {
  const [open, setOpen] = useState(field.status === "conflict");
  const [choice, setChoice] = useState(""); // candidate index 或 "custom"
  const [custom, setCustom] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");

  const submit = async () => {
    setErr("");
    let value, source_record_id;
    if (choice === "custom") {
      if (custom.trim() === "") return setErr("请填写修正值");
      try { value = JSON.parse(custom); } catch { value = custom; }
    } else if (choice !== "") {
      const c = field.candidates[Number(choice)];
      value = c.value;
      source_record_id = c.source_record_id;
    } else {
      return setErr("请选择一个候选值或填写修正值");
    }
    if (!reason.trim()) return setErr("必须填写裁决原因");
    try {
      await api.decide(runId, { business_key: bizKey, field: field.field, final_value: value, reason, source_record_id });
      onDecided();
    } catch (e) { setErr(e.message); }
  };

  return (
    <div className={`field-row ${field.status}`}>
      <div className="field-head" onClick={() => setOpen(!open)}>
        <span className="caret">{open ? "▾" : "▸"}</span>
        <b className="field-name">{field.field}</b>
        <StatusBadge status={field.status} />
        <span className="final">最终值：{fmtVal(field.final_value)}</span>
        <span className="reason">
          {field.decision?.reason}
          {field.decision?.reused && <em className="reused">（沿用上次人工裁决）</em>}
        </span>
      </div>
      {open && (
        <div className="field-body">
          <table className="cands">
            <thead>
              <tr><th></th><th>来源</th><th>批次</th><th>候选值</th><th>更新时间(UTC)</th><th>版本号</th><th>状态</th></tr>
            </thead>
            <tbody>
              {field.candidates.map((c, i) => (
                <tr key={i} className={c.provided ? "" : "missing"}>
                  <td>
                    {c.provided && runStatus === "draft" && (
                      <input type="radio" name={`${bizKey}:${field.field}`}
                        checked={choice === String(i)} onChange={() => setChoice(String(i))} />
                    )}
                  </td>
                  <td>{c.source}</td>
                  <td>{c.batch}</td>
                  <td>{c.provided ? fmtVal(c.value) : <span className="null">（未提供）</span>}</td>
                  <td>{c.updated_at_utc || "—"}</td>
                  <td>{c.version ?? "—"}</td>
                  <td>{c.provided ? "已提供" : "缺失"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {runStatus === "draft" && (
            <div className="decide-form">
              <label>
                <input type="radio" checked={choice === "custom"} onChange={() => setChoice("custom")} />
                修正值：
              </label>
              <input value={custom} placeholder='直接填文本，或 JSON（如 null / 123）'
                onFocus={() => setChoice("custom")} onChange={(e) => setCustom(e.target.value)} />
              <input value={reason} placeholder="裁决原因（必填）" className="reason-input"
                onChange={(e) => setReason(e.target.value)} />
              <button onClick={submit}>提交裁决</button>
              {err && <span className="error">{err}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Workbench() {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [openKeys, setOpenKeys] = useState({});
  const [msg, setMsg] = useState("");

  const loadRuns = async () => setRuns(await api.getRuns());
  const loadDetail = async (id) => {
    const d = await api.getRun(id);
    setDetail(d);
    setRunId(id);
  };
  useEffect(() => { loadRuns(); }, []);
  useEffect(() => { if (runs.length && runId == null) loadDetail(runs[0].id); }, [runs]);

  const newRun = async () => {
    const { run_id } = await api.createRun();
    await loadRuns();
    await loadDetail(run_id);
    setMsg(`已生成草稿 #${run_id}（候选/规则/比较依据未变的人工裁决会自动沿用）`);
  };

  const publish = async () => {
    try {
      const { version_no } = await api.publish(runId);
      setMsg(`已发布为版本 v${version_no}，旧版本与原始来源均保留`);
      await loadRuns();
      await loadDetail(runId);
    } catch (e) { setMsg(`发布失败：${e.message}`); }
  };

  const run = detail?.run;
  const conflicts = detail
    ? Object.values(detail.keys).flat().filter((f) => f.status === "conflict").length
    : 0;

  return (
    <div>
      <div className="toolbar">
        <button className="primary" onClick={newRun}>生成合并草稿</button>
        {run && run.status === "draft" && (
          <button className="primary" disabled={conflicts > 0} onClick={publish}>
            发布{conflicts > 0 ? `（还有 ${conflicts} 个冲突）` : ""}
          </button>
        )}
        {msg && <span className="msg">{msg}</span>}
      </div>
      <div className="runs">
        {runs.map((r) => (
          <button key={r.id} className={`run-chip ${r.id === runId ? "active" : ""}`}
            onClick={() => loadDetail(r.id)}>
            #{r.id} {r.status === "published" ? "已发布" : "草稿"} · 冲突 {r.conflicts ?? 0} · {r.created_at?.slice(0, 19)}
          </button>
        ))}
      </div>
      {detail && Object.entries(detail.keys).map(([key, fields]) => {
        const nConflict = fields.filter((f) => f.status === "conflict").length;
        const open = openKeys[key] ?? nConflict > 0;
        return (
          <div key={key} className="key-card">
            <div className="key-head" onClick={() => setOpenKeys({ ...openKeys, [key]: !open })}>
              <span className="caret">{open ? "▾" : "▸"}</span>
              <b>业务键 {key}</b>
              {nConflict > 0 && <span className="badge conflict">{nConflict} 个冲突</span>}
              <span className="dim">{fields.length} 个字段</span>
            </div>
            {open && fields.map((f) => (
              <FieldRow key={f.field} runId={runId} runStatus={run.status} bizKey={key}
                field={f} onDecided={() => { loadDetail(runId); loadRuns(); }} />
            ))}
          </div>
        );
      })}
    </div>
  );
}
