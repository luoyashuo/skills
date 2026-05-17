#!/usr/bin/env python3
"""
generate_paper_images.py
Generate 2 AI summary images for a research paper PDF using gpt-image-2.

Outputs:
  summary_image_1_background.png  — background / motivation / insights
  summary_image_2_methods.png     — methods / experiments / conclusions

Config priority: config file > env vars > built-in defaults
Config file search order:
  1. PAPER_NOTES_CONFIG env var
  2. ~/.paper-reading-notes/config.yaml
  3. ./.paper-reading-notes.yaml (cwd)
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import subprocess
import importlib.util


# ---------- dependency auto-install ----------

def _install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _ensure(pkg_name, import_name=None):
    if importlib.util.find_spec(import_name or pkg_name) is None:
        print(f"Installing {pkg_name}...")
        _install(pkg_name)

try:
    _ensure("requests")
    _ensure("Pillow", "PIL")
    _ensure("pyyaml", "yaml")
except Exception as e:
    print(f"Warning: dependency auto-install failed: {e}. "
          "Run: pip install requests Pillow pyyaml", file=sys.stderr)

import requests
from PIL import Image
import yaml


# ---------- config ----------

def load_config() -> dict:
    candidates = [
        os.environ.get("PAPER_NOTES_CONFIG"),
        os.path.expanduser("~/.paper-reading-notes/config.yaml"),
        os.path.join(os.getcwd(), ".paper-reading-notes.yaml"),
    ]
    file_cfg = {}
    for path in candidates:
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                file_cfg = yaml.safe_load(f) or {}
            print(f"Loaded config from: {path}")
            break

    def get(file_key, env_key, default=None):
        # config file takes priority over env vars
        v = file_cfg.get(file_key)
        if v is not None:
            return str(v)
        v = os.environ.get(env_key)
        if v:
            return v
        return default

    return {
        "api_key":      get("api_key",      "PAPER_NOTES_API_KEY",
                            "sk-yqKEbgKStkTzkqMK7cA8B84975E94699B51b5fC511055330"),
        "api_base_url": get("api_base_url", "PAPER_NOTES_API_BASE_URL",
                            "https://api.v3.cm/v1"),
        "model":        get("image_model",  "PAPER_NOTES_IMAGE_MODEL",
                            "gpt-image-2-c"),
    }


# ---------- prompts ----------

PROMPT_1 = (
    "请根据这篇论文PDF，生成一张专业的学术摘要图（1024x1024像素）。\n"
    "图片主题：论文背景、研究动机与核心Insight。\n"
    "要求：\n"
    "- 可视化呈现该领域现有问题与挑战\n"
    "- 展示本文研究的核心动机（为什么做这项研究）\n"
    "- 突出论文的关键Insight或创新角度\n"
    "- 不可随意修改论文中的学术词汇，或者自行用无意义的词概括（如方法A,Baseline1等，看了也不知道什么意思)\n"
    "风格：学术简洁，可使用流程图、对比图、思维导图等形式。"
    "配色清晰，文字优先中文，关键术语可保留英文。"
)

PROMPT_2 = (
    "请根据这篇论文PDF，生成一张专业的学术摘要图（1024x1024像素）。\n"
    "图片主题：论文方法、实验设计与核心结论。\n"
    "要求：\n"
    "- 可视化呈现论文提出的核心方法或模型架构\n"
    "- 展示主要实验设置和关键实验结果（如有数值请标注）\n"
    "- 突出论文得出的核心结论与贡献\n"
    "- 不可随意修改论文中的学术词汇，或者自行用无意义的词概括（如方法A,Baseline1等，看了也不知道什么意思)\n"
    "风格：学术简洁，可使用架构图、对比表格、折线图等形式。"
    "配色清晰，文字优先中文，关键术语可保留英文。"
)

IMAGE_CONFIGS = [
    ("summary_image_1_background.png", PROMPT_1),
    ("summary_image_2_methods.png",    PROMPT_2),
]


# ---------- API ----------

def encode_pdf(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def call_api(prompt: str, pdf_b64: str, cfg: dict) -> requests.Response:
    api_url = cfg["api_base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:application/pdf;base64,{pdf_b64}"
                }},
            ],
        }],
    }
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    return requests.post(api_url, json=payload, headers=headers, timeout=120)


def parse_image_bytes(resp: requests.Response) -> bytes:
    """Robust multi-format response parser — handles several possible shapes."""

    # Case C: API returned raw binary image
    ct = resp.headers.get("Content-Type", "")
    if ct.startswith("image/"):
        return resp.content

    # Try to parse JSON
    try:
        data = resp.json()
    except Exception:
        raise ValueError(f"Response is not JSON and not a binary image. "
                         f"Content-Type: {ct}, body[:200]: {resp.text[:200]}")

    # Case A: OpenAI images API shape  {"data": [{"url":...} | {"b64_json":...}]}
    if "data" in data and isinstance(data["data"], list) and data["data"]:
        item = data["data"][0]
        if "url" in item:
            r = requests.get(item["url"], timeout=30)
            r.raise_for_status()
            return r.content
        if "b64_json" in item:
            return base64.b64decode(item["b64_json"])

    # Case B: chat completions shape  {"choices": [...]}
    if "choices" in data and data["choices"]:
        msg = data["choices"][0].get("message", {})
        content = msg.get("content", "")

        if isinstance(content, str):
            # B1: direct URL ending with image extension
            m = re.search(r'https?://\S+\.(?:png|jpg|jpeg|webp)(\?\S*)?', content)
            if m:
                r = requests.get(m.group(0), timeout=30)
                r.raise_for_status()
                return r.content

            # B2: data URI
            if content.startswith("data:image"):
                return base64.b64decode(content.split(",", 1)[1])

            # B3: raw base64 blob — validate with magic bytes
            try:
                raw = base64.b64decode(content)
                if raw[:4] in (b'\x89PNG', b'\xff\xd8\xff') or raw[:4] == b'RIFF':
                    return raw
            except Exception:
                pass

        elif isinstance(content, list):
            # B4: list of content items
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "image_url":
                    url = item["image_url"]["url"]
                    if url.startswith("data:image"):
                        return base64.b64decode(url.split(",", 1)[1])
                    r = requests.get(url, timeout=30)
                    r.raise_for_status()
                    return r.content
                if item.get("type") == "text":
                    text = item.get("text", "")
                    m = re.search(r'https?://\S+\.(?:png|jpg|jpeg|webp)(\?\S*)?', text)
                    if m:
                        r = requests.get(m.group(0), timeout=30)
                        r.raise_for_status()
                        return r.content

    raise ValueError(
        f"Unrecognized response format. body[:500]: {json.dumps(data)[:500]}"
    )


def save_image(image_bytes: bytes, output_path: str) -> None:
    img = Image.open(io.BytesIO(image_bytes))
    img.save(output_path, format="PNG")
    size_kb = os.path.getsize(output_path) // 1024
    print(f"  Saved: {output_path} ({size_kb} KB)")


# ---------- main ----------

def parse_args():
    p = argparse.ArgumentParser(description="Generate paper summary images via gpt-image-2")
    p.add_argument("--pdf-path",   required=True, help="Path to the paper PDF")
    p.add_argument("--output-dir", required=True, help="Directory to save output images")
    return p.parse_args()


def main():
    args = parse_args()

    pdf_path   = os.path.abspath(args.pdf_path)
    output_dir = os.path.abspath(args.output_dir)

    if not os.path.isfile(pdf_path):
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)

    cfg = load_config()
    print(f"Using model: {cfg['model']}  base: {cfg['api_base_url']}")

    print("Encoding PDF...")
    pdf_b64 = encode_pdf(pdf_path)

    results: dict[str, str | None] = {}
    for filename, prompt in IMAGE_CONFIGS:
        output_path = os.path.join(output_dir, filename)
        label = filename.replace("summary_image_", "Image ").replace(".png", "")
        print(f"\nGenerating {label}...")
        try:
            resp = call_api(prompt, pdf_b64, cfg)
            resp.raise_for_status()
            image_bytes = parse_image_bytes(resp)
            save_image(image_bytes, output_path)
            results[filename] = output_path
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            results[filename] = None

    print("\n--- Summary ---")
    for fname, path in results.items():
        print(f"  {fname}: {'OK' if path else 'FAILED'}")

    if all(v is None for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
