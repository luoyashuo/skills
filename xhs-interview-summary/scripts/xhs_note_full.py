#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "playwright>=1.41.0",
#   "pycryptodome>=3.20.0",
#   "requests>=2.31.0",
# ]
# ///
"""
抓取单条小红书笔记：文本 + 全部图片（轮播每张）+ 全页截图。

图片采集方式：从 __INITIAL_STATE__.imageList 取 URL，在已登录浏览器上下文内
用 fetch() 拿到 base64，逐张保存为 PNG，完全绕过 CDN 防盗链。

输出：
  <out_dir>/<note_id>_img0.png  ... 轮播原图（按顺序）
  <out_dir>/<note_id>_page.png  ... 全页截图（含文字排版）
  JSON → stdout

Auth: XIAOHONGSHU_COOKIE 环境变量 或 CookieCloud
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeoutError
from playwright.sync_api import sync_playwright

from cookiecloud import env_cookiecloud_config, load_cookie_data, resolve_cookie_header

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def cookie_pairs(cookie_header: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if not name:
            continue
        pairs.append((name, value))
    return pairs


def cookies_for_playwright(cookie_header: str) -> list[dict[str, Any]]:
    return [
        {"name": name, "value": value, "domain": ".xiaohongshu.com", "path": "/"}
        for name, value in cookie_pairs(cookie_header)
    ]


def cookiecloud_cookies_for_playwright(domain_suffix: str) -> list[dict[str, Any]] | None:
    cfg = env_cookiecloud_config()
    if not cfg:
        return None
    cookie_data = load_cookie_data(cfg)
    raw_cookies = []
    for domain, cookies in cookie_data.items():
        if not isinstance(domain, str):
            continue
        if not domain.endswith(domain_suffix) and not domain.endswith("." + domain_suffix):
            continue
        if isinstance(cookies, list):
            raw_cookies.extend([c for c in cookies if isinstance(c, dict)])

    out: list[dict[str, Any]] = []
    for c in raw_cookies:
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        value = "" if c.get("value") is None else str(c.get("value"))
        domain = str(c.get("domain") or ".xiaohongshu.com")
        path = str(c.get("path") or "/")
        cookie: dict[str, Any] = {"name": name, "value": value, "domain": domain, "path": path}
        if isinstance(c.get("secure"), bool):
            cookie["secure"] = c.get("secure")
        if isinstance(c.get("httpOnly"), bool):
            cookie["httpOnly"] = c.get("httpOnly")
        exp = c.get("expirationDate") or c.get("expires") or c.get("expiry")
        if isinstance(exp, (int, float)) and exp > 0:
            cookie["expires"] = int(exp)
        out.append(cookie)
    return out


def launch_chromium(p, *, headless: bool, channel: str | None):
    ch = (channel or "").strip()
    try:
        if ch:
            return p.chromium.launch(headless=headless, channel=ch)
        return p.chromium.launch(headless=headless)
    except PWError:
        if ch:
            return p.chromium.launch(headless=headless)
        raise


def parse_note_id_from_url(url: str) -> str | None:
    m = re.search(r"/(?:explore|discovery/item)/([^/?#]+)", url)
    return m.group(1) if m else None


def parse_xsec_token_from_url(url: str) -> str | None:
    try:
        qs = parse_qs(urlparse(url).query)
        token = (qs.get("xsec_token") or [None])[0]
        token = str(token).strip() if token else None
        return token or None
    except Exception:
        return None


def extract_note_data(page, note_id_hint: str | None) -> dict[str, Any] | None:
    """从 __INITIAL_STATE__ 提取笔记数据，支持 4 路 fallback。"""
    return page.evaluate(
        """(noteId) => {
            const state = globalThis.__INITIAL_STATE__;
            // Path A
            const dataA = state?.noteData?.data?.noteData;
            if (dataA) return dataA;
            // Path B
            if (noteId) {
                const byId = state?.note?.noteDetailMap?.[noteId]?.note;
                if (byId) return byId;
            }
            // Path C: 重定向到 /404 但 currentNoteId 仍存在
            const cur = state?.note?.currentNoteId;
            if (cur) {
                const byCur = state?.note?.noteDetailMap?.[cur]?.note;
                if (byCur) return byCur;
            }
            // Path D: 无 note_id 时取任意条目
            if (!noteId) {
                const m = state?.note?.noteDetailMap;
                if (m && typeof m === 'object') {
                    for (const k of Object.keys(m)) {
                        const n = m?.[k]?.note;
                        if (n) return n;
                    }
                }
            }
            return null;
        }""",
        note_id_hint,
    )


def extract_image_urls(page, note_id_hint: str | None) -> list[str]:
    """从 __INITIAL_STATE__ 提取 imageList 中的所有图片 URL。"""
    result = page.evaluate(
        """(noteId) => {
            const state = globalThis.__INITIAL_STATE__;
            let note = null;
            if (noteId) {
                note = state?.note?.noteDetailMap?.[noteId]?.note || null;
            }
            if (!note) {
                note = state?.noteData?.data?.noteData || null;
            }
            if (!note) {
                const cur = state?.note?.currentNoteId;
                if (cur) note = state?.note?.noteDetailMap?.[cur]?.note || null;
            }
            if (!note) {
                const m = state?.note?.noteDetailMap;
                if (m && typeof m === 'object') {
                    for (const k of Object.keys(m)) {
                        const n = m?.[k]?.note;
                        if (n) { note = n; break; }
                    }
                }
            }
            if (!note) return [];
            const list = note.imageList || note.images || [];
            return list
                .map(img => img.urlDefault || img.url || img.urlOriginal || null)
                .filter(Boolean);
        }""",
        note_id_hint,
    )
    return result if isinstance(result, list) else []


def fetch_image_as_b64(page, img_url: str) -> str | None:
    """在已认证的浏览器上下文内 fetch 图片，返回 base64 字符串（不含 data: 前缀）。"""
    try:
        result = page.evaluate(
            """async (url) => {
                try {
                    const resp = await fetch(url, {credentials: 'include'});
                    if (!resp.ok) return null;
                    const blob = await resp.blob();
                    return new Promise(resolve => {
                        const reader = new FileReader();
                        reader.onload = () => {
                            const dataUrl = reader.result;
                            const b64 = dataUrl.split(',')[1];
                            resolve(b64 || null);
                        };
                        reader.onerror = () => resolve(null);
                        reader.readAsDataURL(blob);
                    });
                } catch (e) {
                    return null;
                }
            }""",
            img_url,
        )
        return result if isinstance(result, str) and result else None
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取单条小红书笔记：文本 + 全部图片 + 全页截图")
    parser.add_argument("--url", required=True, help="笔记 URL（建议含 xsec_token）")
    parser.add_argument("--out-dir", default="./xhs_images", help="图片和截图保存目录（默认 ./xhs_images）")
    parser.add_argument("--skip-if-exists", action="store_true", help="_page.png 已存在则跳过（断点续跑）")
    parser.add_argument("--cookie", help="Cookie 字符串（覆盖环境变量/CookieCloud）")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", action="store_false", dest="headless")
    parser.add_argument("--channel", default="chrome")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    url = str(args.url).strip()
    note_id_hint = parse_note_id_from_url(url)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    page_png = out_dir / f"{note_id_hint}_page.png" if note_id_hint else None

    # 如果全页截图已存在且设置了 skip，检查 detail json 是否也存在
    if args.skip_if_exists and page_png and page_png.exists():
        # 尝试从同目录找已有的 detail 信息（由 SKILL.md 编排，此处直接跳过）
        print(f"[skip] {note_id_hint} 已有截图，跳过", file=sys.stderr)
        payload = {
            "note_id": note_id_hint,
            "skipped": True,
            "page_screenshot": str(page_png),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        return 0

    cookie_header = resolve_cookie_header(
        domain_suffix="xiaohongshu.com",
        cookie_arg=args.cookie,
        env_names=["XIAOHONGSHU_COOKIE"],
    )
    cookies = cookiecloud_cookies_for_playwright("xiaohongshu.com") or cookies_for_playwright(cookie_header)

    with sync_playwright() as p:
        browser = launch_chromium(p, headless=bool(args.headless), channel=str(args.channel or ""))
        context = browser.new_context(user_agent=UA, locale="zh-CN")
        context.add_cookies(cookies)
        page = context.new_page()

        # 1. 加载笔记页面
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeoutError:
            pass
        time.sleep(1.0)

        # 2. 提取文本
        note_data = extract_note_data(page, note_id_hint)

        # 3. 提取所有图片 URL
        image_urls = extract_image_urls(page, note_id_hint)
        print(f"[info] {note_id_hint}: 共 {len(image_urls)} 张图片", file=sys.stderr)

        # 4. 逐张 fetch 图片（在已认证的浏览器上下文内，绕过 CDN 防盗链）
        saved_images: list[str] = []
        for idx, img_url in enumerate(image_urls):
            img_path = out_dir / f"{note_id_hint}_img{idx}.png"
            if args.skip_if_exists and img_path.exists():
                saved_images.append(str(img_path))
                print(f"[skip] img{idx} 已存在", file=sys.stderr)
                continue
            b64 = fetch_image_as_b64(page, img_url)
            if b64:
                img_path.write_bytes(base64.b64decode(b64))
                saved_images.append(str(img_path))
                print(f"[img] 保存 {img_path.name}", file=sys.stderr)
            else:
                print(f"[warn] img{idx} fetch 失败: {img_url[:80]}", file=sys.stderr)

        # 5. 滚动触发懒加载，再截全页
        for _ in range(10):
            page.mouse.wheel(0, 800)
            time.sleep(0.4)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)

        page_png_path = out_dir / f"{note_id_hint}_page.png"
        if not (args.skip_if_exists and page_png_path.exists()):
            page.screenshot(path=str(page_png_path), full_page=True)
            print(f"[screenshot] 保存 {page_png_path.name}", file=sys.stderr)

        context.close()
        browser.close()

    # 整理输出
    note_id = note_id_hint
    title = None
    author = None
    desc = None
    note_type = None

    if isinstance(note_data, dict):
        note_id = str(note_data.get("id") or note_data.get("noteId") or note_id_hint or "").strip() or note_id_hint
        title = note_data.get("title") or note_data.get("displayTitle") or note_data.get("name")
        desc = note_data.get("desc") or note_data.get("description")
        note_type = note_data.get("type")
        user = note_data.get("user") if isinstance(note_data.get("user"), dict) else {}
        author = user.get("nickname") or user.get("nickName") or user.get("name")
    else:
        print(f"[warn] {note_id_hint}: 未能提取文本（Cookie 过期或需要 xsec_token）", file=sys.stderr)

    payload = {
        "note_id": note_id,
        "title": title,
        "author": author,
        "desc": desc,
        "note_type": note_type,
        "image_count": len(saved_images),
        "images": saved_images,
        "page_screenshot": str(page_png_path),
        "skipped": False,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    print(f"note_id={note_id}")
    if title:
        print(f"title={title}")
    if desc:
        print(desc[:300])
    print(f"images={len(saved_images)}  page_screenshot={page_png_path.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        try:
            sys.stdout.close()
        finally:
            raise
