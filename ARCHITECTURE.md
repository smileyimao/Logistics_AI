# 雄楚速通运单系统 — 架构设计文档

> 更新时间：2026-05-13

---

## 核心技术决策

| 层 | 技术 | 原因 |
|----|------|------|
| 后端 | Flask + SQLite | 现有，保留 |
| 表格 | AG Grid Community 31.x | 冻结列业界标准，纯JS无框架依赖 |
| 图表 | ECharts 5.x | 财务看板 |
| 前端 | 原生JS + 少量Vue实例 | 按需，不强依赖框架 |

---

## 文件结构

```
ShipmentAI/
├── server.py                  # Flask主服务
├── shipments.db               # SQLite数据库
├── static/
│   ├── style.css              # 全局样式
│   └── logo.jpg
└── templates/
    ├── base.html              # 基础布局（侧边栏）
    ├── dashboard.html         # 首页（财务快报 + 集运板块）
    ├── shipments.html         # 运单列表（AG Grid）
    ├── shipment_detail.html   # 运单详情（三Tab）
    ├── finance.html           # 财务看板（admin专属）
    ├── settings.html          # 设置（代理/渠道/收款方式）
    ├── upload.html            # 上传中心
    ├── edit_shipment.html     # 编辑运单
    ├── users.html             # 用户管理
    └── logs.html              # 审计日志
```

---

## 数据库结构

### 现有表（保留）
```sql
TABLE users (id, username, display_name, password_hash, role, active, created_at)
TABLE shipments (id, tracking_no, transfer_no, salesperson, customer, channel,
  destination, postal_code, payment_received, payment_slip, payment_method,
  invoiced, payment_amount, is_paid, misc_fee, remarks, insurance,
  actual_weight, volume, total_weight, pieces, ship_weight, gross_profit,
  profit_rate, agent, wooden_frame, has_docs, ship_date, source,
  created_by, created_at)
TABLE edit_requests (id, shipment_id, field, old_val, new_val, status, ...)
TABLE audit_logs (id, username, action, detail, ip, created_at)
```

### 新增表
```sql
-- 下拉选项管理（代理/渠道/收款方式）
TABLE lookup_values (
  id        INTEGER PRIMARY KEY,
  category  TEXT NOT NULL,   -- 'agent' | 'channel' | 'payment_method'
  value     TEXT NOT NULL,
  sort_order INTEGER DEFAULT 0,
  active    INTEGER DEFAULT 1
)

-- 货物明细（集运/拆货）
TABLE shipment_items (
  id          INTEGER PRIMARY KEY,
  shipment_id INTEGER REFERENCES shipments(id),
  seq         INTEGER,
  actual_kg   REAL,
  length_cm   REAL,
  width_cm    REAL,
  height_cm   REAL,
  vol_weight  REAL,       -- 自动计算：长*宽*高/除数
  bill_weight REAL,       -- 计费重（取大）
  wood_frame  TEXT,
  wood_box    TEXT,
  repair      TEXT,
  extra_json  TEXT        -- 可扩展杂费字段
)

-- 单元格颜色标记（财务标注）
TABLE cell_colors (
  shipment_id INTEGER,
  field       TEXT,
  color       TEXT,       -- 'yellow'|'red'|'green'|'blue'
  updated_by  TEXT,
  updated_at  TEXT,
  PRIMARY KEY (shipment_id, field)
)
```

---

## 页面结构

| 路由 | 页面 | 角色 |
|------|------|------|
| `/app/` | 首页（财务快报 + 集运板块 + 最近运单） | all |
| `/app/shipments` | 运单列表（AG Grid） | all |
| `/app/finance` | 财务看板（月度图表） | admin only |
| `/app/settings` | 设置（代理/渠道/收款方式增删） | admin |
| `/app/upload` | 上传中心 | all |
| `/app/users` | 用户管理 | admin |
| `/app/logs` | 审计日志 | admin |

---

## API 端点

### 现有（保留）
```
GET  /app/shipments              运单列表页
GET  /app/export                 导出Excel
POST /app/shipments/<id>/edit    编辑运单
```

### 新增
```
GET    /api/lookup/<category>         获取代理/渠道/收款方式列表
POST   /api/lookup/<category>         新增选项
DELETE /api/lookup/<category>/<id>    删除选项

PATCH  /api/shipments/<id>/cell       行内编辑单个字段（财务）
POST   /api/shipments/<id>/color      标记单元格颜色

GET    /api/shipments/<id>/items      获取货物明细
POST   /api/shipments/<id>/items      新增/更新货物明细

GET    /api/finance/stats             财务统计（?month=YYYY-MM）
```

---

## AG Grid 运单列表核心配置

```javascript
// 冻结列（pinned: 'left'）
{ field: 'created_at',  headerName: '时间',   pinned: 'left', width: 165 },
{ field: 'tracking_no', headerName: '原单号', pinned: 'left', width: 160 },

// 内置列显示/隐藏面板
sideBar: { toolPanels: ['columns'] }

// 列状态持久化
onColumnVisible: saveColState,
onGridReady: restoreColState,   // 从 localStorage 读取

// 行内编辑（finance/admin）
editable: canEdit,
onCellValueChanged: patchField,

// 点击行 → 右侧详情面板
onRowClicked: showDetail,
```

---

## 运单详情（双击单号弹出）

```
┌─ Tab: 基本信息 ─┐ ┌─ Tab: 货物数据 ─┐ ┌─ Tab: 财务 ──┐
│ 渠道            │ │ 序号│实重│长│宽│高 │ │ 收款金额      │
│ 转单号/运单号   │ │ 材积重│计费重│木架 │ │ 付代理        │
│ 状态            │ │ [+新增行] [导入] │ │ 毛利（自动算）│
│ 备注（可编辑）  │ │ 计费公式：       │ │ 单价（手动）  │
└─────────────────┘ │ 海运÷6000        │ └───────────────┘
                    │ 快递÷5000        │
                    └─────────────────┘
```

---

## 分阶段交付计划

| 阶段 | 内容 | 状态 |
|------|------|------|
| **P1** | AG Grid运单列表（冻结列+列设置+排序+右侧详情面板） | 待开始 |
| **P2** | 代理/渠道/收款方式下拉管理 + 点击筛选 | 待开始 |
| **P3** | 首页财务快报 + 集运板块 | 待开始 |
| **P4** | 财务看板（ECharts月度图表，admin only） | 待开始 |
| **P5** | 运单详情Modal（货物明细+计费重公式） | 待开始 |
| **P6** | 行内编辑 + 单元格颜色标记 | 待开始 |

---

## 竞品分析要点（xj.linkl.com.cn）

- 表格库：VXE-Table 3.4.14 + Vue 2.6.11
- 主色：#4c80f6（蓝）
- 行高：40px，表头：44px
- 边框色：#ebedf5
- 列设置：左侧隐藏字段 + 右侧显示字段 + 上下排序
- 筛选：点击列头 → 快捷筛选（多值勾选 + 数量徽标）
- 详情：右侧抽屉面板，多Tab（基本/费用/单件/申报/轨迹）
