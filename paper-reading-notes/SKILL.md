---
name: "paper-reading-notes"
description: "从 arXiv 下载论文→中文全文图文翻译→生成论文速览引述块→上传飞书知识库（按月份归档）。用户提供 arXiv 链接或 ID 时调用。"
---

# 论文阅读笔记一键生成

本技能自包含全部逻辑，不调用任何外部 skill。内部依次执行：
1. 下载论文（PDF + LaTeX 源码）
2. 生成中文图文翻译
3. 生成论文速览引述块（由 Claude 基于论文内容直接撰写）
4. 上传到飞书知识库（官方 lark-cli，按月份归档）

---

## 何时调用

用户提供 arXiv 链接或 ID，希望得到飞书文档形式的中文阅读笔记。

---

## 配置加载

**优先级：配置文件 > 环境变量 > 内置默认值**

配置文件查找顺序（首个存在的文件生效）：
1. 环境变量 `PAPER_NOTES_CONFIG` 指向的路径
2. `~/.paper-reading-notes/config.yaml`
3. `./.paper-reading-notes.yaml`（当前工作目录）

配置文件格式见同目录 `config.example.yaml`。

| 配置文件字段       | 环境变量                    | 用途                                   |
|------------------|-----------------------------|--------------------------------------|
| `cache_dir`      | `PAPER_NOTES_CACHE_DIR`     | 本地论文缓存目录，支持 ~，默认 ./arxiv_papers |
| `lark_app_id`    | `LARK_APP_ID`               | 飞书 App ID                            |
| `lark_app_secret`| `LARK_APP_SECRET`           | 飞书 App Secret                        |
| `lark_space_id`  | `LARK_SPACE_ID`             | 飞书知识库 Space ID                     |

**必须存在：** `lark_app_id`、`lark_app_secret`、`lark_space_id`（缺失则停止）。

---

## 输入解析

从用户输入中用正则 `\d{4}\.\d{4,5}(?:v\d+)?` 提取 `arxiv_id`。
输入可以是：arXiv 链接、arXiv ID、HuggingFace Papers 页面链接（需先访问该页面从 HTML 提取 arXiv ID）。
无法提取则停止并告知用户。

---

## 第一步：下载论文

运行本技能目录下的 `download_paper.py`：

```bash
python skills/paper-reading-notes/download_paper.py \
  --arxiv-id "{arxiv_id}" \
  --output-dir "{cache_dir}"   # 来自配置，支持 ~ 展开
```

脚本输出格式（每行一个键值对）：
```
TITLE=<论文标题>
WORKDIR=<解压目录绝对路径，如 ~/paper_cache/2512.16649>
PDF=<PDF绝对路径，如 ~/paper_cache/2512.16649/2512.16649.pdf>
ARXIV_ID=<arxiv_id>
```

解析 stdout 得到：`title`、`workdir`、`pdf_path`、`arxiv_id`。

---

## 第二步：中文图文翻译

在 `workdir` 中直接执行翻译，输出 `{workdir}/paper_translation.md`。
不调用任何外部工具或 CLI，以下步骤由 Claude 直接完成。

### 2-1. 提取元信息

从论文源文件中提取以下字段：

| 字段 | 来源 | 规则 |
|------|------|------|
| arXiv ID | 目录名或输入 | 直接使用 |
| 论文标题 | `\title{}` 或 arXiv 页面 | 英文原标题 |
| 作者 | `\author{}` 或 arXiv 页面 | 超过5人写"等" |
| 机构 | `\affiliation{}` / `\affil{}` / 脚注 | 去重，逗号分隔 |
| 论文链接 | 构造 | `https://arxiv.org/abs/{arxiv_id}` |
| 开源代码 | 在 `.tex`/README 中搜索 `github.com`、`gitlab.com`、`code available` | 找到给链接，否则"未开源" |
| 资源开销 | 搜索 `GPU`、`A100`、`H100`、`training time`、`compute` | 提取具体信息，否则"未提及" |

### 2-2. 选择主文档

- 有 LaTeX：选包含 `\begin{document}` 的 `.tex` 文件（若多个则选体量最大的）
- 无 LaTeX：基于 `paper_translation.md` 已有内容或 PDF 文本

### 2-3. LaTeX → Markdown 结构转换

- `\section` / `\subsection` / `\subsubsection` / `\paragraph` → `#` / `##` / `###` / `####`
- `\textbf{}` → **加粗**，`\textit{}` → *斜体*（Typora 兼容，两侧留空格）
- 去除 `\cite{}`、`\label{}`、`\ref{}`；`\footnote{}` 转为括注
- **图片**：`\includegraphics[]{path}` → `![alt](path)`；完整保留 `figure` 环境（图片 + 标题 + 说明文字）
- 表格、列表按 Markdown 语法重排；复杂表格可简化为段落

### 2-4. 公式处理（KaTeX 兼容）

- 块级公式：`equation` / `align` / `gather` / `eqnarray` → `$$ ... $$`
- 行内公式：保留 `$ ... $`
- **必须**将所有 `<` 替换为 `\lt`，否则 KaTeX 解析报错

### 2-5. 图片处理

- **必须**保留架构图、流程图、实验结果图、对比图等重要图片
- 格式 `pdf`：转换为 `png` 后以相对路径引用；格式 `png`/`jpeg`：直接相对路径引用
- **禁止**输出纯文本翻译，文档必须图文混排

### 2-6. 文本翻译

- 按段落翻译为中文，保留必要英文术语和变量名
- 忠于原文，不扩展评论；附录可择要翻译

### 2-7. 文件生成

将完整 Markdown 写入 `{workdir}/paper_translation.md`，开头必须包含元信息块：

```markdown
# 【中文翻译标题】

## 📋 论文信息

| 项目 | 内容 |
|------|------|
| **原文标题** | Paper Title |
| **作者** | Author1, Author2, Author3, Author4, Author5 等 |
| **机构** | Institution1, Institution2 |
| **arXiv** | [arXiv:XXXX.XXXXX](https://arxiv.org/abs/XXXX.XXXXX) |
| **开源代码** | [GitHub](https://github.com/xxx/xxx) / 未开源 |
| **资源开销** | 8×A100 GPUs, 训练 7 天 / 未提及 |

---
```

---

## 第三步：生成论文速览引述块

由 Claude 直接基于论文内容（LaTeX 源文件或 PDF）撰写，**不调用任何外部 API**。

### 内容要求

引述块必须忠于论文原文，覆盖以下维度（各 1-3 句，语言简练）：

| 维度 | 说明 |
|------|------|
| **研究背景与动机** | 该领域现存的核心问题或痛点，以及本文为何研究这个问题 |
| **核心亮点 / Insight** | 论文提出的关键创新点或核心观察，用论文自己的术语表述 |
| **方法概述** | 主要方法/模型/框架的简要描述，突出区别于已有方案的本质差异 |
| **主要结论** | 最重要的实验结论或理论贡献（如有具体数字请保留） |

**禁止**：不得使用"方法A"、"Baseline1"等无意义占位词；不得添加原文没有的主观评价。

### 输出格式

将以下 Markdown 写入 `{workdir}/paper_quote.md`（将括号内容替换为实际内容）：

```markdown
> **📌 论文速览**
>
> **研究背景与动机：**（1-3 句，说明领域痛点与研究动机）
>
> **核心亮点：**（1-3 句，论文的关键 Insight 或创新角度）
>
> **方法概述：**（1-3 句，主要方法/架构的本质特点）
>
> **主要结论：**（1-3 句，最重要的实验结果或理论贡献，保留具体数值）
```

---

## 第四步：上传到飞书（lark-cli）

从配置文件或环境变量读取飞书凭证，通过 lark-cli 完成所有操作。
**禁止使用** `paper_read_bot/skills/feishu-doc/` 目录下的任何脚本。

### 4a. 确定月份文件夹名

```python
from datetime import datetime
MONTH = datetime.now().strftime("%Y-%m")  # 例如 "2026-05"
```

### 4b. 查找或创建月份文件夹

```bash
# 列出知识库根节点
lark-cli wiki nodes list \
  --space-id "$LARK_SPACE_ID" \
  --parent-node-token "" \
  --format json
```

解析 `data.items`：找到 `obj_type=="folder"` 且 `title==MONTH` → 取其 `node_token` 作为 `FOLDER_TOKEN`。

未找到则创建：

```bash
lark-cli wiki nodes create \
  --space-id "$LARK_SPACE_ID" \
  --data "{\"obj_type\":\"folder\",\"node_type\":\"origin\",\"parent_node_token\":\"\",\"title\":\"$MONTH\"}"
# 从响应 data.node.node_token 读取 FOLDER_TOKEN
```

### 4c. 重复文档检测

```bash
lark-cli wiki nodes list \
  --space-id "$LARK_SPACE_ID" \
  --parent-node-token "$FOLDER_TOKEN" \
  --format json
```

若存在 `obj_type=="docx"` 且 `title==paper_title` 的节点 → 输出现有文档 wiki URL，**跳过后续步骤**。

### 4d. 创建文档节点

```bash
lark-cli wiki +node-create \
  --space-id "$LARK_SPACE_ID" \
  --parent-node-token "$FOLDER_TOKEN" \
  --title "$PAPER_TITLE"
# 提取: obj_token → OBJ_TOKEN（文档 ID），node_token → NODE_TOKEN
```

### 4e. 先插入论文速览引述块（文档最前面）

引述块放在文档顶部，方便快速了解论文要点。

**Windows (PowerShell)：**
```powershell
lark-cli docs +update --api-version v2 `
  --doc "$OBJ_TOKEN" `
  --command append `
  --doc-format markdown `
  --content (Get-Content -Raw "{workdir}/paper_quote.md")
```

**Linux / macOS (Bash)：**
```bash
lark-cli docs +update --api-version v2 \
  --doc "$OBJ_TOKEN" \
  --command append \
  --doc-format markdown \
  --content "$(cat '{workdir}/paper_quote.md')"
```

### 4f. 追加中文翻译全文

**Windows (PowerShell)：**
```powershell
lark-cli docs +update --api-version v2 `
  --doc "$OBJ_TOKEN" `
  --command append `
  --doc-format markdown `
  --content (Get-Content -Raw "{workdir}/paper_translation.md")
```

**Linux / macOS (Bash)：**
```bash
lark-cli docs +update --api-version v2 \
  --doc "$OBJ_TOKEN" \
  --command append \
  --doc-format markdown \
  --content "$(cat '{workdir}/paper_translation.md')"
```

**最终文档结构：**
```
[📌 论文速览（引述块：背景·动机·亮点·方法·结论）]
[中文翻译全文（元信息表格 + 图文正文）]
```

---

## 输出

```
✅ 飞书文档已创建：
   Wiki URL : https://DOMAIN/wiki/{NODE_TOKEN}
   Doc  URL : https://DOMAIN/docx/{OBJ_TOKEN}
   月份文件夹: 2026-05
   本地缓存  : {workdir}
```

若触发重复检测：
```
⚠️  文档已存在，跳过上传：
   Wiki URL : https://DOMAIN/wiki/{node_token}
```

---

## 错误处理

| 步骤 | 可能的错误 | 处理方式 |
|------|-----------|----------|
| 1. 下载 | 网络错误 / arXiv ID 无效 | 重试一次；仍失败则告知用户检查链接 |
| 2. 翻译 | 无 LaTeX 源码 | 退回基于 PDF 文本的翻译 |
| 3. 速览生成 | 论文内容无法读取 | 退回基于摘要的简短引述块，标注"基于摘要" |
| 4b. 创建文件夹 | 权限不足 | 检查凭证；提示用户在飞书开放平台添加 `wiki:node:create` 权限 |
| 4c. 重复检测 | 同名文档已存在 | 返回现有链接，停止 |
| 4e. 插入引述块 | `paper_quote.md` 不存在 | 跳过引述块，不中止上传 |

---

## 技能文件

```
skills/paper-reading-notes/
  SKILL.md                  ← 本文件
  download_paper.py         ← arXiv 下载脚本（PDF + LaTeX）
  config.example.yaml       ← 配置文件模板
```

> AI 摘要图生成（gpt-image-2）已独立为 `paper-summary-images` 技能，见 `skills/paper-summary-images/`。
