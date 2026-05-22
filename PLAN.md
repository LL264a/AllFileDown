# Allfiledown — 项目计划 (v4)

> 去中心化多服务器协同下载系统 · 动态节点 · 角色分工

---

## 一、节点角色系统

现在不是"所有节点都一样"了，而是灵活的三种角色：

### 🔵 上下节点（Full Node）
| 能力 | 说明 |
|:--|:--|
| Web UI | ✅ 有浏览器界面，可操作 |
| 下载 | ✅ aria2 拉文件 |
| 上传/共享 | ✅ 下完即做种，给其他节点当源 |
| 管理 | ✅ 可增删节点、管理全集群 |

> 典型：你的主用节点，比如 S.K.（高带宽）或 V.V.（大内存），当管理入口

### 🟢 只有下载（Download-Only）
| 能力 | 说明 |
|:--|:--|
| Web UI | ❌ 没有，通过其他 Full Node 管理 |
| 下载 | ✅ 接受任务，aria2 拉文件 |
| 上传/共享 | ❌ 不下完不做种 |
| 资源占用 | 最轻量 |

> 用途：一台只想拿文件、不想费上传带宽的机器。
> 比如家里的 NAS 服务器，只管收文件，但上行带宽留给别的事情。

### 🟠 只有上传（Upload-Only）
| 能力 | 说明 |
|:--|:--|
| Web UI | ❌ 没有 |
| 下载 | ❌ 不主动下载 |
| 上传/共享 | ✅ 存放已完成文件，作为内部源给其他节点拉取 |

> 用途：一台专门做"仓库"的机器，不下新东西，但存着历史文件给其他节点当源。
> 相当于一个**内部文件缓存/CDN 节点**。

### 组合示例

```
你有一个大文件要下发到所有服务器：

  1️⃣ 在 S.K.（Full Node）的 UI 提交下载
  2️⃣ S.K. + V.V. + K.K. + C.C.（Full Node）同时开始下载官方源
  3️⃣ 仓库服务器（Upload-Only）不动，它已经有旧版本了
  4️⃣ 家里 NAS（Download-Only）开始下载，但不贡献上传
  5️⃣ S.K. 第一个下完 → 变源
  6️⃣ 其他还没下完的 Full Node + Download-Only 节点从 S.K. 拉
  7️⃣ 最终：所有节点都有文件了 ✅
```

## 二、节点管理 — 在 UI 上动态增删

不再写在 config.json 里，而是在页面上管理：

```
┌────────────────────────────────────────────┐
│  📡 节点管理                                │
│                                            │
│  + 添加节点                                 │
│  ┌──────┬────────┬────────┬──────┬───────┐ │
│  │ 节点   │ 地址    │ 类型    │ 状态  │ 操作   │ │
│  ├──────┼────────┼────────┼──────┼───────┤ │
│  │ S.K. │ 43...  │ 上下    │ 🟢在线 │ [编辑][删除]│
│  │ V.V. │ 43...  │ 上下    │ 🟢在线 │        │
│  │ C.C. │ 49...  │ 上下    │ 🟢在线 │        │
│  │ K.K. │ 103... │ 上下    │ 🟠离线 │        │
│  │ NAS  │ 192... │ 仅下载  │ 🟢在线 │        │
│  │ 仓库  │ 172... │ 仅上传  │ 🟢在线 │        │
│  └──────┴────────┴────────┴──────┴───────┘ │
│                                            │
│  添加节点：                                  │
│  [节点名称___] [IP:端口___________]          │
│  [类型: ▼] (上下 / 仅下载 / 仅上传)           │
│  [Auth Token________________]               │
│  [ 确认添加 ]                                │
└────────────────────────────────────────────┘
```

### 节点发现机制

1. **Full Node** 上添加新节点后，广播给所有其他 Full Node
2. **Download-Only** 节点定期 ping 所有 Full Node 领取任务
3. **Upload-Only** 节点注册自己到 Full Node，告诉它们"我有这些文件"
4. 断开连接的节点标记为离线，不影响其他节点工作

## 三、安全机制细化

不同类型的节点需要不同级别的信任：

| 通信方向 | 安全措施 |
|:--|:--|
| Full ↔ Full | 双向 Token 验证，消息签名 |
| Full → Download | Full 推任务，Download 单向验证 |
| Download → Full | Download 报告进度，需 Token |
| Upload → Full | Upload 注册自己的文件列表 |
| Upload → All | 文件共享使用随机 token 路径 |

## 四、完整架构回顾

```
                      ┌──────────────────┐
                      │    Full Node     │
                      │  (Web UI + 管理)  │ ← 你在任意一台 Full 浏览器操作
                      └────────┬─────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │  Full Node    │   │ Download-Only│   │ Upload-Only  │
   │  S.K./V.V./.. │   │  NAS/其他    │   │  仓库服务器    │
   │  下载+上传+UI  │   │  只下载不上传  │   │  只上传不下载  │
   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
          │                  │                  │
     ┌────▼────┐        ┌───▼────┐         ┌───▼────┐
     │  aria2  │        │  aria2 │         │  HTTP  │
     │ 下载+BT  │        │  只下载  │         │ 文件服务 │
     │  做种    │        │        │         │(已有文件)│
     └─────────┘        └────────┘         └────────┘
```

## 五、数据库设计（简化版）

每个节点本地记录：

```sql
-- 节点表（本地已知的所有节点）
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,        -- sk, vv, cc, kk...
    name TEXT,                  -- 显示名称
    host TEXT,                  -- IP
    port INTEGER,               -- API 端口
    type TEXT,                  -- full / download / upload
    auth_token TEXT,            -- 验证令牌
    status TEXT,                -- online / offline
    last_seen TIMESTAMP         -- 最后心跳时间
);

-- 任务表
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    url TEXT,                   -- 原始下载链接
    filename TEXT,              -- 文件名
    total_size INTEGER,         -- 总大小
    created_at TIMESTAMP,
    status TEXT                 -- pending / downloading / completed / failed
);

-- 节点-任务状态表（每个节点在每个任务上的状态）
CREATE TABLE task_nodes (
    task_id TEXT,
    node_id TEXT,
    progress REAL,              -- 0.0 ~ 1.0
    status TEXT,                -- waiting / downloading / seeding / completed / failed
    local_path TEXT,            -- 本机文件路径
    internal_url TEXT,          -- 内部源 URL（下完才有）
    PRIMARY KEY (task_id, node_id)
);
```

---

## 六、开发策略

还是 **单机验证 → 双机联动 → 全量部署** 的策略。

```
Phase 0: 单机验证版
  ├── Full Node 一套（就在 S.K. 上跑）
  ├── Web UI：输入 URL → 本地 aria2 下载 → 看进度
  ├── 本地模拟第2个节点（验证通信逻辑）
  └── 核心代码都是可复用的

Phase 1: 双机 Full Node
  ├── S.K. + V.V.
  ├── 节点发现 + 任务广播
  ├── 下载完成自动变源
  └── 跨服务器验证

Phase 2: 引入 Download-Only / Upload-Only
  ├── 角色区分逻辑
  ├── Download 节点加入集群
  ├── Upload 节点注册为源
  └── 动态增删节点 UI

Phase 3: 全量部署 + 生产化
  ├── 所有节点部署
  ├── nginx + SSL
  ├── systemd 服务
  └── 文档
```

---

## 七、等你确认

1. **服务器列表** — MEMORY.md 里只记了 S.K./V.V./C.C./K.K. 四台，还有两台是？
2. **开发起点** — 还是先在本机（S.K.）做单机验证版？还是你想直接上多机？
3. **UI 风格偏好** — 极简实用风还是稍微好看点？
