# xianyu-mcp

`xianyu-mcp` 是一个面向 MCP 客户端使用者的闲鱼 MCP Server。它通过 Playwright 和闲鱼网页能力，提供登录、商品发布、收藏管理、商品查询、卖家主页读取等能力。

你可以把它接入支持 MCP 的客户端，例如 Codex、Claude Code、MCP Inspector，或任何兼容 `stdio` / `streamable_http` 的 MCP 工具。

## 它能做什么

- 登录闲鱼账号，获取扫码二维码并轮询登录结果
- 登录二维码以 base64 返回，便于客户端直接展示
- 发布商品、下架商品、删除商品
- 添加收藏、取消收藏
- 通过 `resources` / `resource templates` 读取商品、收藏、我的商品、卖家主页等数据
- 通过 `prompt` 生成商品分析提示词

当前项目实际注册了 **9 个 MCP tools**。

## 环境要求

- Python 3.10 或更高版本
- 可正常启动的 Chromium 浏览器环境
- 能访问闲鱼网页

## 安装

下面的安装命令适用于 Windows、macOS 和 Linux：

```sh
python -m pip install .
python -m playwright install chromium
```

如果你想使用虚拟环境，可以先创建，但这不是必须的：

```sh
python -m venv .venv

macOS / Linux：
source .venv/bin/activate

Windows PowerShell：
.venv\Scripts\Activate.ps1

Windows CMD：
.venv\Scripts\activate.bat
```

## 快速开始

### 方式一：作为本地 `stdio` MCP Server 运行

这是大多数本地 MCP 客户端最常见的接法。

```sh
xianyu-mcp
```

如果命令行入口不可用，也可以这样启动：

```sh
python -m xianyu_mcp.server
```

### 方式二：作为 `streamable_http` MCP Server 运行

推荐把配置写入 `.env`，避免依赖不同系统的命令行环境变量写法。

示例：

```env
MCP_TRANSPORT=streamable_http
MCP_HTTP_HOST=127.0.0.1
MCP_HTTP_PORT=18000
MCP_STREAMABLE_HTTP_PATH=/mcp
```

然后启动服务：

```sh
xianyu-mcp
```

启动后默认地址为：

```text
http://127.0.0.1:18000/mcp
```

## Docker 运行

如果你更希望把它作为常驻 MCP 服务运行，可以直接使用 Docker Compose。

项目已提供 [Dockerfile](./Dockerfile) 和 [docker-compose.yml](./docker-compose.yml)。

启动：

```sh
docker compose up -d --build
```

查看日志：

```sh
docker compose logs -f
```

停止：

```sh
docker compose down
```

默认情况下：

- 容器内监听 `0.0.0.0:18000`
- 宿主机访问地址为 `http://127.0.0.1:18000/mcp`
- `./browser_data` 挂载到容器内 `/app/browser_data`
- `./screenshots` 挂载到容器内 `/app/screenshots`
- 自动读取当前目录的 `.env`

## 配置

你可以通过 `.env` 调整运行行为。常用项如下：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HEADLESS` | `true` | 是否使用无头浏览器 |
| `PAGE_TIMEOUT` | `30000` | 页面操作超时，单位毫秒 |
| `SLOW_MO` | `0` | 浏览器慢动作延时，单位毫秒 |
| `COOKIE_AUTO_SYNC_ENABLED` | `true` | 是否开启 Cookie 自动同步 |
| `COOKIE_SYNC_INTERVAL_SECONDS` | `600` | Cookie 同步间隔，单位秒 |
| `COOKIE_SYNC_TIMEOUT_SECONDS` | `30` | 单次 Cookie 同步超时，单位秒 |
| `AUTO_SCREENSHOT` | `false` | 是否自动截图 |
| `SCREENSHOT_DIR` | `./screenshots` | 截图目录 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `MCP_TRANSPORT` | `stdio` | 传输模式：`stdio` 或 `streamable_http` |
| `MCP_TOOL_TIMEOUT_SECONDS` | `10` | 单个工具调用超时，单位秒 |
| `MCP_HTTP_HOST` | `127.0.0.1` | HTTP 模式监听地址 |
| `MCP_HTTP_PORT` | `18000` | HTTP 模式监听端口 |
| `MCP_STREAMABLE_HTTP_PATH` | `/mcp` | HTTP 模式路径 |

例如，如果你想看到浏览器界面，可以在 `.env` 中设置：

```env
HEADLESS=false
```

## 接入 MCP 客户端

### OpenClaw（通过MCPorter）

把以下命令发送给OpenClaw。

```sh
帮我安装这个MCP：npx mcporter config add xianyu http://127.0.0.1:18000/mcp
```

### MCP Inspector

调试本地 `stdio` 服务：

```sh
npx @modelcontextprotocol/inspector python -m xianyu_mcp.server
```

调试 HTTP 服务：

```sh
npx @modelcontextprotocol/inspector
```

然后在 Inspector 页面中选择 `Streamable HTTP`，再填入：

```text
http://127.0.0.1:18000/mcp
```

其他主流客户端暂未测试，有兴趣的可以自己试试。

## Tools 一览

### 账号登录

- `check_login_status`：检查当前是否已登录
- `get_login_qrcode`：获取登录二维码（返回 `qrcode_base64`）
- `check_login_scan_result`：检查扫码结果（人脸验证场景返回 `qrcode_base64`）
- `logout`：退出登录并清理本地会话

### 收藏管理

- `add_favorite`：收藏商品
- `remove_favorite`：取消收藏

### 商品管理

- `publish_goods`：发布商品
- `take_down_goods`：下架商品
- `delete_goods`：删除商品

## Resources / Resource Templates / Prompt

除了 tools，这个服务还暴露了 MCP context 能力。

### Resources

- `xianyu://account/login-status`
- `xianyu://goods/home?page_num=1&page_size=30`
- `xianyu://favorites?page_num=1&page_size=20`
- `xianyu://my-goods?page_num=1&page_size=20`

### Resource Templates

- `xianyu://goods/detail/{item_id}`
- `xianyu://goods/search/{keyword}{?page_num,page_size,price_min,price_max,sort_field,sort_value,quick_filters}`
- `xianyu://goods/home{?page_num,page_size}`
- `xianyu://favorites{?page_num,page_size}`
- `xianyu://seller/{user_id}{?include_items,include_ratings}`
- `xianyu://my-goods{?status,page_num,page_size}`

### Prompt

- `analyze_goods(item_id)`：生成商品风险与价格分析提示词

## 使用建议

- 优先把它作为 `stdio` 服务接入本地 MCP 客户端
- 如果需要给多个客户端或远程网关复用，再改用 `streamable_http`
- 首次启动会拉起 Playwright/Chromium，客户端的启动超时建议适当放宽
- 登录、发布商品这类依赖页面状态的操作，建议先确认账号已登录
- 不考虑制作购买和聊天的工具。
