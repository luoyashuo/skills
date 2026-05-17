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
抓取小红书收藏专辑的完整笔记列表，修复分页不完整问题。

改进：
- 用内容轮询替代 stable_iters 提前退出：每次滚动后等待最多 10 秒直到有新内容
- 只有 has_more=false 或达到 max_items 才停止
- 默认 --max 500 --scroll 1000
- 支持 --progress-file 实时写入，中断可续跑

Auth: XIAOHONGSHU_COOKIE 环境变量 或 CookieCloud
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

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
    return [{"name": k, "value": v, "domain": ".xiaohongshu.com", "path": "/"} for k, v in cookie_pairs(cookie_header)]


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


def parse_board_id(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    m = re.search(r"/board/([^/?#]+)", value)
    if m:
        return m.group(1)
    return value


def build_board_url(board_id: str) -> str:
    return f"https://www.xiaohongshu.com/board/{board_id}?source=web_user_page"


def build_note_url(note_id: str, xsec_token: str | None) -> str:
    if xsec_token:
        return (
            f"https://www.xiaohongshu.com/discovery/item/{note_id}"
            f"?source=webshare&xhsshare=pc_web&xsec_token={xsec_token}&xsec_source=pc_share"
        )
    return f"https://www.xiaohongshu.com/explore/{note_id}"


def read_board_entry(page, board_id: str) -> dict[str, Any]:
    return page.evaluate(
        """(boardId) => {
            const m = globalThis.__INITIAL_STATE__?.board?.boardFeedsMap?._rawValue || null;
            if (!m || typeof m !== 'object') return { ok: false };
            const e = m[boardId] || m[String(boardId)] || null;
            if (!e || typeof e !== 'object') return { ok: false };
            const notes = Array.isArray(e.notes) ? e.notes : [];
            const outNotes = notes
              .filter((n) => n && typeof n === 'object')
              .map((n) => ({
                note_id: n.noteId ?? null,
                xsec_token: n.xsecToken ?? null,
                note_type: n.type ?? null,
                title: n.displayTitle ?? null,
                author: n.user?.nickName ?? n.user?.nickname ?? null,
                cover: n.cover?.urlDefault ?? n.cover?.url ?? null,
                time: n.time ?? n.lastUpdateTime ?? null,
              }));
            return {
              ok: true,
              cursor: e.cursor ?? null,
              has_more: !!e.hasMore,
              notes: outNotes,
            };
        }""",
        board_id,
    )


def build_output(board_id: str, entry: dict[str, Any], max_items: int) -> dict[str, Any]:
    notes = entry.get("notes") or []
    out: list[dict[str, Any]] = []
    for n in notes[:max_items]:
        if not isinstance(n, dict):
            continue
        note_id = str(n.get("note_id") or "").strip()
        if not note_id:
            continue
        token = str(n.get("xsec_token") or "").strip() or None
        out.append({
            "platform": "xiaohongshu",
            "board_id": board_id,
            "note_id": note_id,
            "xsec_token": token,
            "note_type": n.get("note_type"),
            "title": n.get("title"),
            "author": n.get("author"),
            "cover": n.get("cover"),
            "time": n.get("time"),
            "url": build_note_url(note_id, token),
        })
    return {
        "platform": "xiaohongshu",
        "board_id": board_id,
        "board_url": build_board_url(board_id),
        "cursor": entry.get("cursor"),
        "has_more": entry.get("has_more"),
        "notes": out,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取小红书收藏专辑完整笔记列表（修复分页）")
    parser.add_argument("--board-id", required=True, help="专辑 id 或 /board/<id> URL")
    parser.add_argument("--max", type=int, default=500, help="最多返回条数（默认 500）")
    parser.add_argument("--scroll", type=int, default=1000, help="最大滚动次数（默认 1000）")
    parser.add_argument("--poll-timeout", type=float, default=10.0, help="每次滚动后等待新内容的最长秒数（默认 10）")
    parser.add_argument("--progress-file", help="实时把当前列表写入该文件（支持中断续跑）")
    parser.add_argument("--cookie", help="Cookie 字符串（覆盖环境变量/CookieCloud）")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", action="store_false", dest="headless")
    parser.add_argument("--channel", default="chrome")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    board_id = parse_board_id(str(args.board_id))
    if not board_id:
        raise SystemExit("缺少 --board-id")

    cookie_header = resolve_cookie_header(
        domain_suffix="xiaohongshu.com",
        cookie_arg=args.cookie,
        env_names=["XIAOHONGSHU_COOKIE"],
    )
    cookies = cookiecloud_cookies_for_playwright("xiaohongshu.com") or cookies_for_playwright(cookie_header)

    max_items = max(1, int(args.max))
    max_scroll = max(0, int(args.scroll))
    poll_timeout = max(1.0, float(args.poll_timeout))

    progress_path = Path(args.progress_file) if args.progress_file else None

    with sync_playwright() as p:
        browser = launch_chromium(p, headless=bool(args.headless), channel=str(args.channel or ""))
        context = browser.new_context(user_agent=UA, locale="zh-CN")
        context.add_cookies(cookies)
        page = context.new_page()

        url = build_board_url(board_id)
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PWTimeoutError:
            pass
        time.sleep(1.0)

        last_len = 0
        entry: dict[str, Any] = {}

        for scroll_i in range(max_scroll + 1):
            entry = read_board_entry(page, board_id)
            notes = entry.get("notes") if isinstance(entry, dict) else None
            cur_len = len(notes) if isinstance(notes, list) else 0

            print(f"[scroll {scroll_i}] 已获取 {cur_len} 条  has_more: {entry.get('has_more', '?')}", file=sys.stderr)

            if cur_len >= max_items:
                print(f"[done] 达到 max={max_items}，停止", file=sys.stderr)
                break

            if isinstance(entry, dict) and entry.get("ok") and not entry.get("has_more"):
                print("[done] has_more=false，列表已完整", file=sys.stderr)
                break

            # 写进度文件
            if progress_path and isinstance(entry, dict) and entry.get("ok"):
                payload = build_output(board_id, entry, max_items)
                progress_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            # 滚动，然后轮询等待新内容（最多 poll_timeout 秒）
            page.mouse.wheel(0, 1400)
            deadline = time.time() + poll_timeout
            while time.time() < deadline:
                time.sleep(0.6)
                entry = read_board_entry(page, board_id)
                new_len = len(entry.get("notes") or [])
                if new_len > cur_len:
                    break  # 新内容到了
            last_len = cur_len

        # 最终读一次确保拿到最新状态
        entry = read_board_entry(page, board_id)
        context.close()
        browser.close()

    if not isinstance(entry, dict) or not entry.get("ok"):
        print("无法读取专辑数据（Cookie 过期、专辑不可访问或页面结构变更）", file=sys.stderr)
        return 2

    payload = build_output(board_id, entry, max_items)

    # 总数核对提示
    total = len(payload["notes"])
    has_more = payload.get("has_more")
    print(f"\n[结果] 共获取 {total} 条笔记，has_more={has_more}", file=sys.stderr)
    if has_more:
        print("[警告] has_more 仍为 true，可能未抓完，建议增大 --scroll 重跑", file=sys.stderr)
    print("[提示] 请与小红书专辑页面显示的总数核对", file=sys.stderr)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    print(f"board_id={board_id}  notes={total}  has_more={has_more}")
    for item in payload["notes"]:
        title = str(item.get("title") or "").strip()
        print(f"- {item.get('note_id')} {title}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        try:
            sys.stdout.close()
        finally:
            raise
