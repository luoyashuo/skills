---
name: "paper-summary-images"
description: "为已下载的 arXiv 论文生成 2 张 AI 摘要图（背景·动机·Insight / 方法·实验·结论），并上传到指定飞书文档顶部。需先用 paper-reading-notes 完成论文下载和翻译。"
---

# 论文 AI 摘要图生成

本技能使用 gpt-image-2 为论文 PDF 生成 2 张可视化摘要图，并插入到指定飞书文档顶部。
**前置条件**：需先通过 `paper-reading-notes` 技能完成论文下载，获得 `pdf_path`、`workdir`、`obj_token`。

---

## 何时调用

用户希望为已有的飞书论文文档补充 AI 摘要图，或在使用 `paper-reading-notes` 之后追加图解。

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
| `api_key`        | `PAPER_NOTES_API_KEY`       | gpt-image-2 API Key（必填）             |
| `api_base_url`   | `PAPER_NOTES_API_BASE_URL`  | API 基础地址，默认 https://api.v3.cm/v1 |
| `image_model`    | `PAPER_NOTES_IMAGE_MODEL`   | 图片生成模型，默认 gpt-image-2           |

**必须存在：** `api_key`（缺失则停止，告知用户配置 API Key）。

---

## 输入解析

从用户输入或上下文中获取：

| 参数 | 来源 | 说明 |
|------|------|------|
| `pdf_path` | paper-reading-notes 输出 / 用户指定 | 论文 PDF 绝对路径 |
| `workdir` | paper-reading-notes 输出 / 用户指定 | 论文工作目录（图片输出到此） |
| `obj_token` | paper-reading-notes 输出 / 用户指定 | 飞书文档 OBJ_TOKEN（裸 token） |

若用户提供的是飞书 wiki URL（如 `https://xxx.feishu.cn/wiki/TOKEN`），需先解析出 `node_token`，再通过 lark-cli 查询对应的 `obj_token`：

```bash
lark-cli wiki nodes get --node-token "$NODE_TOKEN" --format json
# 从响应 data.node.obj_token 读取 OBJ_TOKEN
```

---

## 第一步：生成摘要图

运行本技能目录下的 `generate_paper_images.py`：

```bash
python skills/paper-summary-images/generate_paper_images.py \
  --pdf-path "{pdf_path}" \
  --output-dir "{workdir}"
```

脚本自动从标准位置加载配置（API Key、model 等），无需命令行传参。

输出到 `workdir`：
- `summary_image_1_background.png` — 背景、动机、Insight
- `summary_image_2_methods.png`    — 方法、实验、核心结论

**图片生成失败为非致命错误**：记录警告，跳过对应图片，不中止整体流程。

---

## 第二步：插入图片到飞书文档顶部

图片区插入到文档最前面，方便飞书快速预览。

```bash
# 1. 插入图片区标题
lark-cli docs +update --api-version v2 \
  --doc "$OBJ_TOKEN" \
  --command append \
  --content '<h2>📊 论文图解</h2>'

# 2. 插入图1（仅当文件存在时执行）
lark-cli docs +media-insert --api-version v2 \
  --doc "$OBJ_TOKEN" \
  --file "{workdir}/summary_image_1_background.png"

# 3. 插入图2（仅当文件存在时执行）
lark-cli docs +media-insert --api-version v2 \
  --doc "$OBJ_TOKEN" \
  --file "{workdir}/summary_image_2_methods.png"
```

> **注意**：`--doc` 必须使用 `OBJ_TOKEN`（裸 token），不能使用 `/wiki/...` URL，否则 `docs +media-insert` 会报错。

---

## 输出

```
✅ 摘要图已插入：
   图1（背景·动机·Insight）: {workdir}/summary_image_1_background.png
   图2（方法·实验·结论）   : {workdir}/summary_image_2_methods.png
   已上传至文档 : https://DOMAIN/docx/{OBJ_TOKEN}
```

若 API Key 缺失：
```
❌ 缺少 API Key，请在配置文件中设置 api_key 或设置环境变量 PAPER_NOTES_API_KEY。
```

---

## 错误处理

| 步骤 | 可能的错误 | 处理方式 |
|------|-----------|----------|
| 配置加载 | `api_key` 缺失 | 停止并告知用户配置方式 |
| 图片生成 | API 错误 / 超时 / 格式未知 | 记录警告，跳过该图片，继续插入其他图片 |
| 两张图均失败 | 全部生成失败 | 告知用户错误原因，建议检查 API Key 或网络 |
| 插入图片 | `OBJ_TOKEN` 无效 / 权限不足 | 提示用户检查 token 和飞书应用权限 |

---

## 技能文件

```
skills/paper-summary-images/
  SKILL.md                  ← 本文件
  generate_paper_images.py  ← gpt-image-2 摘要图生成脚本
  config.example.yaml       ← 配置文件模板
```
