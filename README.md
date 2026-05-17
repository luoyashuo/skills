# 个人 Skills

个人使用的 Claude Code Skills 集合。

## 环境依赖（无 Docker 直接运行）

xiaohongshu-favorites、bilibili-favorites、zhihu-favorites 等收藏夹 skill 的脚本可直接用 Python 运行（无需 Docker）。

**安装 Python 依赖：**

```bash
pip install playwright pycryptodome requests
```

**安装浏览器（国内网络说明）：**

`playwright install chromium` 会从 Google 下载 Chromium，国内网络通常超时失败。  
推荐直接复用系统已安装的 Chrome（无需额外下载），脚本默认使用 `--channel chrome`，只要 Chrome 安装在标准路径即可：
- Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe`

若一定需要独立 Chromium，可通过代理或镜像安装：
```bash
# 设置代理后再安装
set HTTPS_PROXY=http://127.0.0.1:7890
playwright install chromium
```

## Cookie 配置

各平台 Cookie 统一存放在 `skills/.env`（已加入 `.gitignore`，不会提交到 git）：

```
# skills/.env
XIAOHONGSHU_COOKIE=...
# BILIBILI_COOKIE=...
# ZHIHU_COOKIE=...
```

脚本只读 `os.environ`，不会自动加载 `.env` 文件。运行脚本前先在终端执行一次（PowerShell）：

```powershell
# 加载 skills/.env 到当前会话（在 skills/ 目录下执行）
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}
```

或者一次性写入 Windows 用户环境变量（重启终端后永久生效，无需每次加载）：

```powershell
Get-Content skills/.env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'User')
    }
}
```

## Installation

所有 skill 依赖 `lark-cli`，安装 skill 前需先完成以下步骤：

```bash
# 安装 lark-cli
npm install -g @larksuite/cli
npx skills add larksuite/cli -y -g

# 初始化配置（一次性）
lark-cli config init
lark-cli auth login --recommend
```

## Skills

**论文阅读（自建）**

- **paper-reading-notes** — 从 arXiv 下载论文，生成中文翻译并上传飞书知识库
- **paper-summary-images** — 为论文生成 AI 摘要图并插入飞书文档（需先运行 paper-reading-notes）

**收藏夹管理（来自 [hc-tec/my-collection-skills](https://github.com/hc-tec/my-collection-skills)）**

- **favorites-harvester** — 多平台收藏夹路由，统一入口查看 B站/知乎/小红书收藏内容
- **bilibili-favorites** — 查看 B站收藏夹及视频字幕/逐字稿
- **zhihu-favorites** — 查看知乎收藏夹及回答/文章全文
- **xiaohongshu-favorites** — 查看小红书收藏笔记及内容详情
- **media-audio-download** — 通过 Docker 下载视频音频（供转写使用）
- **whisper-transcribe-docker** — 通过 Docker 本地运行 faster-whisper 生成逐字稿
