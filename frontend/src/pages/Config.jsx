import { useEffect, useState } from "react";
import { api } from "../api";

const STRATEGIES = [
  ["source_priority", "按来源优先级"],
  ["latest_update", "按更新时间"],
  ["manual", "人工裁决"],
];

function RuleEditor({ rule, sources, onSaved }) {
  const [r, setR] = useState(rule);
  const [msg, setMsg] = useState("");
  useEffect(() => setR(rule), [rule]);

  const move = (i, dir) => {
    const p = [...r.priority];
    const j = i + dir;
    if (j < 0 || j >= p.length) return;
    [p[i], p[j]] = [p[j], p[i]];
    setR({ ...r, priority: p });
  };

  const save = async () => {
    await api.putRule(r.field, { strategy: r.strategy, priority: r.priority, null_handling: r.null_handling });
    setMsg("已保存（下次生成草稿时生效）");
    onSaved();
  };

  return (
    <div className="rule-card">
      <div className="rule-head">
        <b>{r.field}</b>
        <select value={r.strategy} onChange={(e) => setR({ ...r, strategy: e.target.value })}>
          {STRATEGIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <label className="dim">
          显式 null：
          <select value={r.null_handling} onChange={(e) => setR({ ...r, null_handling: e.target.value })}>
            <option value="ignore">视为未提供</option>
            <option value="clear">清空该字段</option>
          </select>
        </label>
        <button onClick={save}>保存</button>
        <span className="msg">{msg}</span>
      </div>
      {r.strategy === "source_priority" && (
        <div className="priority-list">
          优先级：
          {r.priority.map((s, i) => (
            <span key={s} className="chip">
              {i + 1}. {s}
              <button onClick={() => move(i, -1)}>↑</button>
              <button onClick={() => move(i, 1)}>↓</button>
            </span>
          ))}
          {sources.filter((s) => !r.priority.includes(s)).map((s) => (
            <button key={s} className="chip add" onClick={() => setR({ ...r, priority: [...r.priority, s] })}>
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Config() {
  const [cfg, setCfg] = useState(null);
  const [rules, setRules] = useState([]);
  const [sources, setSources] = useState([]);
  const [msg, setMsg] = useState("");

  const load = async () => {
    setCfg(await api.getConfig());
    setRules(await api.getRules());
    setSources((await api.getSources()).map((s) => s.name));
  };
  useEffect(() => { load(); }, []);

  if (!cfg) return null;

  const setMapping = (src, field, val) => {
    setCfg({ ...cfg, field_mappings: { ...cfg.field_mappings, [src]: { ...cfg.field_mappings[src], [field]: val } } });
  };

  return (
    <div>
      <section className="card">
        <h2>全局配置</h2>
        <div className="form-row">
          <label>业务主键字段</label>
          <input value={cfg.business_key_field}
            onChange={(e) => setCfg({ ...cfg, business_key_field: e.target.value })} />
        </div>
        <div className="form-row">
          <label>
            <input type="checkbox" checked={cfg.shared_version_scheme}
              onChange={(e) => setCfg({ ...cfg, shared_version_scheme: e.target.checked })} />
            各来源共用同一套业务版本号（勾选后才允许按版本号比较新旧；否则版本号仅展示）
          </label>
        </div>
        <button className="primary" onClick={async () => { await api.putConfig(cfg); setMsg("已保存"); }}>
          保存配置
        </button>
        <span className="msg">{msg}</span>
      </section>

      <section className="card">
        <h2>字段映射（来源字段名 → 规范字段）</h2>
        <table>
          <thead>
            <tr><th>规范字段</th>{sources.map((s) => <th key={s}>{s}</th>)}</tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.field}>
                <td><b>{r.field}</b></td>
                {sources.map((s) => (
                  <td key={s}>
                    <input value={cfg.field_mappings[s]?.[r.field] ?? ""}
                      placeholder="（无映射）"
                      onChange={(e) => setMapping(s, r.field, e.target.value)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2>字段取值规则</h2>
        {rules.map((r) => (
          <RuleEditor key={r.field} rule={r} sources={sources} onSaved={load} />
        ))}
      </section>
    </div>
  );
}
