---
name: xhs-interview-summary
description: "从小红书收藏专辑抓取面经笔记（图+文全量，不遗漏），按用户指定主题生成结构化面经总结。支持增量缓存，每次只下载新增笔记，总结每次重新生成。用于：整理和并行训练有关的面经、整理OPD面经、总结字节番茄面经等。"
---

# xhs-interview-summary

从小红书收藏专辑中抓取面经笔记，读取每条笔记的图+文，按用户指定主题生成结构化面经总结。

## 触发时机

用户提出面经整理需求时调用，例如：
- "整理和并行训练有关的面经"
- "整理和 OPD 有关的面经"
- "整理字节番茄组的面经"
- "总结收藏的大模型算法面经"

## 固定配置

| 配置项 | 值 |
|--------|-----|
| **工作目录** | `C:\Users\91435\Desktop\claw_learning\xhs_cache` |
| **脚本目录** | `C:\Users\91435\Desktop\claw_learning\skills\xhs-interview-summary\scripts` |
| **Cookie 来源** | `XIAOHONGSHU_COOKIE` 环境变量（位于 `C:\Users\91435\Desktop\claw_learning\skills\.env`） |

工作目录结构：
```
xhs_cache/
├── board_notes.json         ← 专辑全量笔记列表
├── details/
│   └── <note_id>.json       ← 每条笔记的文本
├── images/
│   ├── <note_id>_img0.png   ← 轮播第 1 张原图
│   ├── <note_id>_img1.png   ← 轮播第 2 张原图（若有）
│   └── <note_id>_page.png   ← 全页截图
└── summaries/
    └── <topic>_<date>.md    ← 面经总结报告
```

---

## 工作流

### 阶段 A：缓存更新（增量，只下载缺失内容）

#### A-0. 加载 Cookie 并设置编码

```powershell
# 读取 .env 文件中的 XIAOHONGSHU_COOKIE
$envContent = Get-Content "C:\Users\91435\Desktop\claw_learning\skills\.env" -Encoding utf8
foreach ($line in $envContent) {
    if ($line -match '^XIAOHONGSHU_COOKIE=(.+)$') {
        $env:XIAOHONGSHU_COOKIE = $Matches[1]
    }
}
$env:PYTHONIOENCODING = "utf-8"
```

#### A-1. 获取全量笔记列表

检查 `<work_dir>/board_notes.json` 是否存在且 `has_more` 为 `false`：

```python
import json, pathlib
p = pathlib.Path(r"C:\Users\91435\Desktop\claw_learning\xhs_cache\board_notes.json")
if p.exists():
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    need_fetch = data.get("has_more", True)
else:
    need_fetch = True
```

若需要重新抓取：

```powershell
cd "C:\Users\91435\Desktop\claw_learning\skills\xhs-interview-summary\scripts"
python xhs_fetch_all_board.py `
  --board-id "<BOARD_ID>" `
  --max 500 --scroll 1000 `
  --progress-file "C:\Users\91435\Desktop\claw_learning\xhs_cache\board_notes_progress.json" `
  --json | Out-File -Encoding utf8 "C:\Users\91435\Desktop\claw_learning\xhs_cache\board_notes.json"
```

**确认完成：** 检查 stderr 出现 `[done] has_more=false`；对比 XHS 专辑页面显示的总数与 `board_notes.json` 中的 `notes` 数组长度。若 `has_more` 仍为 `true`，增大 `--scroll` 重跑。

> **BOARD_ID 获取方法：** 打开 XHS 收藏专辑页，URL 形如 `https://www.xiaohongshu.com/board/6xxxxxxx`，取最后一段即为 board_id。

#### A-2. 补全缺失笔记

读取 `board_notes.json`，找出 `details/<note_id>.json` **不存在**的笔记，逐条执行：

```python
import json, pathlib, subprocess, sys

work_dir = pathlib.Path(r"C:\Users\91435\Desktop\claw_learning\xhs_cache")
scripts_dir = pathlib.Path(r"C:\Users\91435\Desktop\claw_learning\skills\xhs-interview-summary\scripts")
details_dir = work_dir / "details"
images_dir  = work_dir / "images"
details_dir.mkdir(exist_ok=True)
images_dir.mkdir(exist_ok=True)

notes = json.loads((work_dir / "board_notes.json").read_text(encoding="utf-8-sig"))["notes"]
missing = [n for n in notes if not (details_dir / f"{n['note_id']}.json").exists()]
print(f"需要补全 {len(missing)} / {len(notes)} 条")

for i, note in enumerate(missing):
    note_id = note["note_id"]
    url = note["url"]
    out_file = details_dir / f"{note_id}.json"
    print(f"[{i+1}/{len(missing)}] {note_id} {note.get('title','')[:30]}")
    result = subprocess.run(
        [sys.executable, str(scripts_dir / "xhs_note_full.py"),
         "--url", url,
         "--out-dir", str(images_dir),
         "--skip-if-exists",
         "--json"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(scripts_dir)
    )
    if result.returncode == 0 and result.stdout.strip():
        out_file.write_text(result.stdout.strip(), encoding="utf-8")
    else:
        print(f"  [warn] 失败: {result.stderr[:200]}")
    # 避免限流
    import time; time.sleep(1.5)
```

将以上代码写入临时文件 `_batch_fetch.py` 再执行，避免 PowerShell 字符串转义问题：

```powershell
# 把上面代码写入文件后执行
python "C:\Users\91435\Desktop\claw_learning\_batch_fetch.py"
```

---

### 阶段 B：按主题总结（每次都执行）

#### B-1. 提取用户主题关键词

根据用户输入提取 1-3 个核心关键词（中文和英文均可），例如：
- "并行训练" → `["并行", "parallel", "分布式"]`
- "OPD" → `["OPD", "opd"]`
- "字节番茄" → `["番茄", "字节", "bytedance"]`

#### B-2. 过滤相关笔记（宽松匹配）

```python
import json, pathlib

work_dir = pathlib.Path(r"C:\Users\91435\Desktop\claw_learning\xhs_cache")
keywords = ["并行", "parallel"]  # 替换为实际关键词（大小写不敏感）

details_dir = work_dir / "details"
matched = []
for f in details_dir.glob("*.json"):
    d = json.loads(f.read_text(encoding="utf-8-sig"))
    text = " ".join([str(d.get("title") or ""), str(d.get("desc") or "")]).lower()
    if any(kw.lower() in text for kw in keywords):
        matched.append(d)
print(f"命中 {len(matched)} 条笔记")
```

#### B-3. 逐条读图+读文

对筛选出的每条笔记，Claude **必须**：

1. 读 `details/<note_id>.json` 获取 title、desc 文本
2. 读 `images/<note_id>_img0.png`、`_img1.png` … 逐张图片（用 Read 工具，Claude 视觉识别）
3. 若无独立图片（image_count=0），读 `images/<note_id>_page.png` 全页截图

**不能跳过任何一条命中笔记，不能跳过任何一张图片。**

#### B-4. 生成 Q&A 格式面经总结

从筛选出的笔记中提炼真实被问过的问题，每个问题独立成一个 Q&A 条目：

```markdown
# Q: <面试中被问到的具体问题>?

<综合多条笔记的答案，要点式或段落式均可，尽量完整>

来源：<笔记标题1>、<笔记标题2>（可选）

---

# Q: <下一个问题>?

<答案>

---
```

**提炼原则：**
- 每个 `# Q:` 对应一个具体、独立的面试问题（而非笼统的主题）
- 优先提炼被多条笔记反复出现的高频问题
- 答案综合所有相关笔记的信息，不重复堆叠原文
- 手撕题单独列出题目描述 + 解法思路
- 问题粒度：宁细勿粗，"GRPO 和 PPO 的区别是什么？" 优于 "RL 算法"

报告保存至：

```python
import pathlib, datetime, re
work_dir = pathlib.Path(r"C:\Users\91435\Desktop\claw_learning\xhs_cache")
summaries_dir = work_dir / "summaries"
summaries_dir.mkdir(exist_ok=True)
topic_slug = re.sub(r"[^\w\-]", "_", topic_text)[:30]
date_str = datetime.date.today().strftime("%Y%m%d")
out_path = summaries_dir / f"{topic_slug}_{date_str}.md"
out_path.write_text(report_content, encoding="utf-8")
```

---

## 注意事项

1. **编码**：所有 Python 脚本输出先设置 `$env:PYTHONIOENCODING = "utf-8"`；读 JSON 文件用 `encoding="utf-8-sig"` 兼容 PowerShell 写出的 BOM。

2. **多行 Python**：避免用 `-c` 传多行代码，统一写入 `.py` 文件再执行。

3. **断点续跑**：`xhs_note_full.py` 的 `--skip-if-exists` 保证中断后重跑不重复下载；`xhs_fetch_all_board.py` 的 `--progress-file` 实时保存进度。

4. **限流**：每条笔记之间 sleep 1.5 秒，避免被 XHS 封禁。

5. **图片缺失**：若某条笔记 `image_count=0` 且 `_page.png` 也不存在，记录为异常，在总结末尾附上异常列表供人工检查。
