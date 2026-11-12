import { useEffect, useState } from "react";
import { api } from "../api";

const OUTCOME = {
  won: ["命中", "won"],
  lost: ["未选中", "lost"],
  conflict: ["参与冲突", "conflict"],
  not_provided: ["未提供该字段", "missing"],
};

export default function Sources() {
  const [sources, setSources] = useState([]);
  const [records, setRecords] = useState([]);
  const [impact, setImpact] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.getSources().then(setSources);
    api.getSourceRecords().then(setRecords);
  }, []);

  const showImpact = async (id) => {
    setErr("");
    try {
      const data = await api.getImpact(id);
      if (!data.run_id) setErr("还没有合并运行，请先在“合并工作台”生成草稿");
      setImpact(data);
    } catch (e) { setErr(e.message); }
  };

  return (
    <div>
      <section className="card">
        <h2>来源</h2>
        <div className="src-list">
          {sources.map((s) => (
            <div key={s.id} className="chip big">
              <b>{s.name}</b> · {s.record_count} 条记录
              <div className="dim">{s.description}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h2>原始记录（原样保留，点击行反查影响）</h2>
        {err && <div className="error">{err}</div>}
        <table>
          <thead>
            <tr><th>ID</th><th>来源</th><th>批次文件</th><th>业务键</th><th>版本号</th><th>更新时间</th><th>到达时间</th><th>原始内容</th></tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.id} onClick={() => showImpact(r.id)}
                className={impact?.record.id === r.id ? "selected" : ""}>
                <td>{r.id}</td><td>{r.source}</td><td>{r.batch}</td><td><b>{r.business_key}</b></td>
                <td>{r.version ?? "—"}</td><td>{r.updated_at ?? "—"}</td><td>{r.received_at?.slice(0, 19)}</td>
                <td><code className="payload">{JSON.stringify(r.payload)}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {impact && (
        <section className="card">
          <h2>
            记录 #{impact.record.id}（{impact.record.source} / {impact.record.business_key}）
            在合并运行 #{impact.run_id} 中的影响
          </h2>
          {impact.impacts.length === 0 && <p className="dim">该记录未参与任何字段的合并。</p>}
          <table>
            <thead>
              <tr><th>业务键</th><th>字段</th><th>该记录候选值</th><th>最终值</th><th>结果状态</th><th>影响</th></tr>
            </thead>
            <tbody>
              {impact.impacts.map((im, i) => {
                const [label, cls] = OUTCOME[im.outcome];
                return (
                  <tr key={i}>
                    <td>{im.business_key}</td><td>{im.field}</td>
                    <td>{im.candidate.provided ? JSON.stringify(im.candidate.value) : "（未提供）"}</td>
                    <td>{JSON.stringify(im.final_value)}</td>
                    <td>{im.result_status}</td>
                    <td><span className={`badge ${cls}`}>{label}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
