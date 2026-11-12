# 多源逐字段合并（Pointwise Delivery）

同一条业务记录从多个来源送达，**逐字段**决定取哪个来源的值：名称可以信 A、地址可以信 B，不必整条选同一来源。

## 快速开始

```bash
# 后端（首次启动自动建库、写入默认配置并导入 seed_data/ 下三个源文件）
cd backend
pip install -r requirements.txt          # 或使用已建好的 /workspace/.venv
uvicorn app.main:app --port 8000

# 前端开发模式（可选，代理到 8000）
cd frontend && npm install && npm run dev

# 或构建后由后端直接托管（已构建好，直接访问 http://localhost:8000）
cd frontend && npm run build
```

测试：`cd backend && python -m pytest tests/`

## 核心语义

- **缺失 ≠ 清空**：源记录缺字段表示未提供；显式 `null` 是否清空由字段规则
  `null_handling`（`ignore` / `clear`）决定。
- **时间比较**：各来源时间戳统一归一到 UTC 后比较（`app/merge.py: parse_ts`）。
- **版本号比较**：仅当全局配置明确"各来源共用同一套业务版本号"时，才按版本号判断新旧；
  否则版本号只展示、不参与比较——两套独立编号不能比大小。
- **冲突保留**：按所选规则（来源优先级 / 更新时间 / 人工）仍分不出先后的不同值，
  保留为冲突，必须人工裁决后才能发布。
- **裁决沿用**：重算草稿时，仅当某字段的**候选值 + 字段规则 + 比较依据**三者都未变
  （SHA-256 指纹一致），才沿用上轮人工裁决；任一变化则重新计算。
- **发布留痕**：发布生成不可变快照版本，旧版本与原始来源记录全部保留。

## 种子数据（三个来源，覆盖全部边界情形）

| 情形 | 位置 |
|---|---|
| 缺失字段 | crm 的 C003 只有 name/email |
| 显式 null 主动清空 | erp 的 C001 `credit: null`（规则为 clear，且时间最新 → 清空生效） |
| 晚到旧记录 | web 的 C001 `phone 999-9`（版本号 99 但更新时间是 11-01，到达时间 11-12） |
| 同级冲突 | C002 的 phone：crm 与 erp 同一时刻（时区归一后）给出不同值 |
| 人工裁决字段 | status 规则为 manual，C001（active/vip）、C002（active/gold）产生冲突 |

## 页面

- **合并工作台**：生成草稿 → 展开业务键查看每字段全部候选与最终选择 →
  冲突字段选候选值或填修正值（必填原因）→ 无冲突后发布。
- **字段规则配置**：业务主键、版本体系开关、字段映射、每字段取值规则与 null 处理。
- **来源数据**：原始记录列表，点击行反查该记录影响了哪些合并结果（命中/未选中/参与冲突）。
- **发布版本**：历史版本列表与快照查看。

## API 摘要

```
GET/PUT /api/config            全局配置（主键、版本体系、字段映射）
GET/PUT /api/rules/{field}     字段规则
GET  /api/sources              来源列表
GET  /api/source-records       原始记录
GET  /api/source-records/{id}/impact   源记录反查影响
POST /api/runs                 生成合并草稿（自动沿用未失效的人工裁决）
GET  /api/runs/{id}            按业务键展开候选与最终选择
POST /api/runs/{id}/decide     人工裁决（必填原因）
POST /api/runs/{id}/publish    发布（有冲突则拒绝）
GET  /api/publications[/{v}]   发布历史与快照
POST /api/reset                重置为种子状态
```
