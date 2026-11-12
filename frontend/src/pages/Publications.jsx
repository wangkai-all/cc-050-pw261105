import { useEffect, useState } from "react";
import { api } from "../api";

export default function Publications() {
  const [pubs, setPubs] = useState([]);
  const [detail, setDetail] = useState(null);

  useEffect(() => { api.getPublications().then(setPubs); }, []);

  return (
    <div>
      <section className="card">
        <h2>发布历史（旧版本全部保留）</h2>
        {pubs.length === 0 && <p className="dim">尚未发布。请在“合并工作台”处理完冲突后发布。</p>}
        <div className="runs">
          {pubs.map((p) => (
            <button key={p.version_no}
              className={`run-chip ${detail?.version_no === p.version_no ? "active" : ""}`}
              onClick={async () => setDetail(await api.getPublication(p.version_no))}>
              v{p.version_no} · 来自草稿 #{p.run_id} · {p.published_at?.slice(0, 19)}
            </button>
          ))}
        </div>
      </section>
      {detail && (
        <section className="card">
          <h2>版本 v{detail.version_no} 快照</h2>
          <table>
            <thead>
              <tr><th>业务键</th><th>字段</th><th>最终值</th></tr>
            </thead>
            <tbody>
              {Object.entries(detail.snapshot).flatMap(([key, fields]) =>
                Object.entries(fields).map(([f, v], i) => (
                  <tr key={`${key}:${f}`}>
                    {i === 0 && <td rowSpan={Object.keys(fields).length}><b>{key}</b></td>}
                    <td>{f}</td>
                    <td>{v === null ? <span className="null">null</span> : JSON.stringify(v)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
