import { useState } from "react";
import Workbench from "./pages/Workbench";
import Config from "./pages/Config";
import Sources from "./pages/Sources";
import Publications from "./pages/Publications";

const TABS = [
  ["workbench", "合并工作台"],
  ["config", "字段规则配置"],
  ["sources", "来源数据"],
  ["publications", "发布版本"],
];

export default function App() {
  const [tab, setTab] = useState("workbench");
  return (
    <div className="app">
      <header>
        <h1>多源逐字段合并</h1>
        <nav>
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
              {label}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === "workbench" && <Workbench />}
        {tab === "config" && <Config />}
        {tab === "sources" && <Sources />}
        {tab === "publications" && <Publications />}
      </main>
    </div>
  );
}
