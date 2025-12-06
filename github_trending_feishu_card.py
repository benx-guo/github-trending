#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Fetch GitHub Trending, write records into Feishu Bitable,
and send an interactive card to Feishu via webhook.

Env:
    FEISHU_WEBHOOK_URL
    FEISHU_APP_ID
    FEISHU_APP_SECRET
    FEISHU_BITABLE_APP_TOKEN
    FEISHU_BITABLE_TABLE_ID
"""

import os
import sys
import argparse
import textwrap
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 可选：没有 python-dotenv 时直接略过
    pass

TRENDING_BASE_URL = "https://github.com/trending"

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
BITABLE_APP_TOKEN = os.getenv("FEISHU_BITABLE_APP_TOKEN")
BITABLE_TABLE_ID = os.getenv("FEISHU_BITABLE_TABLE_ID")


# ---------------- GitHub Trending ---------------- #

def build_trending_url(language: Optional[str], since: str) -> str:
    """构造 GitHub Trending URL."""
    if language:
        url = f"{TRENDING_BASE_URL}/{language}"
    else:
        url = TRENDING_BASE_URL
    return f"{url}?since={since}"


def fetch_trending(
    language: Optional[str], since: str, timeout: int = 10
) -> List[Dict]:
    """
    抓取并解析 GitHub Trending 页面.

    返回列表，每个元素为：
        {
            "name": "owner/repo",
            "url": "https://github.com/owner/repo",
            "description": "...",
            "language": "Python",
            "stars": 1234,
            "stars_today": 123
        }
    """
    url = build_trending_url(language, since)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GitHubTrendingBot/1.0)"
    }

    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    repo_items = soup.find_all("article", class_="Box-row")

    results: List[Dict] = []

    for item in repo_items:
        # 仓库名
        h2 = item.find("h2")
        if not h2:
            continue
        a = h2.find("a")
        if not a or not a.get("href"):
            continue

        repo_path = a.get("href").strip()  # /owner/repo
        name = repo_path.lstrip("/")
        repo_url = "https://github.com" + repo_path

        # 描述
        desc_tag = item.find("p", class_="col-9")
        if not desc_tag:
            # 有些布局 class 会变化，兜底找第一个 <p>
            desc_tag = item.find("p")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # 语言
        lang_tag = item.find("span", itemprop="programmingLanguage")
        language_name = lang_tag.get_text(strip=True) if lang_tag else ""

        # 总 stars
        star_tag = item.find("a", href=lambda x: x and x.endswith("/stargazers"))
        stars = None
        if star_tag:
            stars_text = star_tag.get_text(strip=True).replace(",", "")
            try:
                stars = int(stars_text)
            except ValueError:
                stars = None

        # today / this week stars
        stars_today_tag = item.find("span", class_="d-inline-block float-sm-right")
        stars_today = None
        if stars_today_tag:
            text = stars_today_tag.get_text(strip=True)
            parts = text.split(" ")
            if parts:
                num_part = parts[0].replace(",", "")
                try:
                    stars_today = int(num_part)
                except ValueError:
                    stars_today = None

        results.append(
            {
                "name": name,
                "url": repo_url,
                "description": description,
                "language": language_name,
                "stars": stars,
                "stars_today": stars_today,
            }
        )

    return results


# ---------------- Feishu Bitable 写入 ---------------- #

def get_tenant_access_token() -> str:
    """使用 app_id + app_secret 获取 tenant_access_token."""
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET not set")

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"get_tenant_access_token failed: {data}")
    return data["tenant_access_token"]


def build_source_tag(since: str, language: Optional[str]) -> str:
    """构造 Source 字段，带时间粒度标签."""
    now = datetime.now(timezone.utc)
    lang_key = (language or "all").lower()

    if since == "weekly":
        year, week, _ = now.isocalendar()
        return f"github-trending:weekly:{year}-W{week:02d}:{lang_key}"
    elif since == "monthly":
        month_tag = now.strftime("%Y-%m")
        return f"github-trending:monthly:{month_tag}:{lang_key}"
    else:  # daily
        day_tag = now.strftime("%Y-%m-%d")
        return f"github-trending:daily:{day_tag}:{lang_key}"


def current_date_ms() -> int:
    """生成当天 00:00:00 UTC 的毫秒级时间戳，作为 Date 字段."""
    today = datetime.now(timezone.utc).date()
    dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def build_bitable_records(
    repos: List[Dict],
    language: Optional[str],
    since: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """
    根据 Trending 列表构造 Bitable records.
    约定字段：
      Rank, Repo, Owner, SpokenLanguage, Language, Stars, TodayStars,
      Description, URL(link/text), Date(ms), Source
    """
    records: List[Dict[str, Any]] = []
    date_ms = current_date_ms()
    source = build_source_tag(since, language)
    spoken_language = "all"  # 你后续如果做 spoken_language_code，可以填真实值

    for idx, repo in enumerate(repos[:limit], start=1):
        full_name = repo["name"]        # owner/repo
        if "/" in full_name:
            owner, _repo_name = full_name.split("/", 1)
        else:
            owner, _repo_name = full_name, ""

        stars_val = repo["stars"] if repo["stars"] is not None else 0
        today_val = repo["stars_today"] if repo["stars_today"] is not None else 0

        fields = {
            "Rank": idx,
            "Repo": full_name,
            "Owner": owner,
            "SpokenLanguage": spoken_language,
            "Language": repo["language"] or "",
            "Stars": stars_val,
            "TodayStars": today_val,
            "Description": repo["description"] or "",
            "URL": {
                "link": repo["url"],
                "text": full_name,
            },
            "Date": date_ms,
            "Source": source,
        }
        records.append({"fields": fields})

    return records


def write_records_to_bitable(records: List[Dict[str, Any]]) -> None:
    """调用 Bitable batch_create 写入多行记录."""
    if not records:
        return

    if not (BITABLE_APP_TOKEN and BITABLE_TABLE_ID):
        raise RuntimeError("BITABLE app_token / table_id not set")

    token = get_tenant_access_token()
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/"
        f"{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records/batch_create"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    payload = {
        "records": records,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Bitable batch_create failed: {data}")
    print(f"[INFO] Wrote {len(records)} records to Feishu Bitable.")


# ---------------- Feishu 卡片 ---------------- #

def build_feishu_card(
    repos: List[Dict],
    language: Optional[str],
    since: str,
    limit: int,
) -> Dict:
    """
    构造飞书 interactive card 的 payload（不含 msg_type）.
    """
    since_label = {
        "daily": "Daily",
        "weekly": "Weekly",
        "monthly": "Monthly",
    }.get(since, since)

    lang_label = language if language else "All Languages"
    header_title = f"📈 GitHub Trending · {since_label}"

    # 顶部信息区（语言、周期、来源）
    elements: List[Dict] = [
        {
            "tag": "markdown",
            "content": (
                f"**Language**: {lang_label}  \n"
                f"**Period**: {since_label}  \n"
                f"**Source**: https://github.com/trending"
            ),
        },
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": f"**Top {limit} Repositories**",
        },
    ]

    # 列表区
    for idx, repo in enumerate(repos[:limit], start=1):
        name = repo["name"]
        url = repo["url"]
        lang = repo["language"] or "Unknown"
        stars = repo["stars"]
        stars_today = repo["stars_today"]

        # 星数展示
        stars_part = []
        if stars is not None:
            stars_part.append(f"⭐ {stars}")
        if stars_today is not None:
            stars_part.append(f"+{stars_today} today")
        stars_str = " · ".join(stars_part) if stars_part else "stars: N/A"

        # 描述太长就截断
        desc = repo["description"] or "(no description)"
        short_desc = textwrap.shorten(desc, width=120, placeholder="…")

        elements.append(
            {
                "tag": "markdown",
                "content": (
                    f"{idx}. **{name}**  \n"
                    f"{stars_str} · {lang}  \n"
                    f"{short_desc}  \n"
                    f"{url}"
                ),
            }
        )

    # 底部按钮
    elements.append({"tag": "hr"})
    elements.append(
        {
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": "🔍 Open GitHub Trending",
            },
            "type": "primary",
            "url": "https://github.com/trending",
        }
    )

    card = {
        "schema": "2.0",
        "header": {
            "title": {
                "tag": "plain_text",
                "content": header_title,
            },
            "template": "blue",
        },
        "body": {
            "elements": elements,
        },
    }
    return card


def send_card_to_feishu(webhook_url: str, card: Dict, timeout: int = 10) -> None:
    """
    通过 webhook 向飞书发送卡片消息.
    """
    payload = {
        "msg_type": "interactive",
        "card": card,
    }
    resp = requests.post(webhook_url, json=payload, timeout=timeout)
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Feishu webhook HTTP error: {e}", file=sys.stderr)
        print(f"[DEBUG] Response: {resp.text}", file=sys.stderr)
        raise

    data = resp.json()
    if data.get("code") != 0:
        print(f"[ERROR] Feishu returned non-zero code: {data}", file=sys.stderr)
        raise RuntimeError(f"Feishu error: {data}")


# ---------------- CLI & main ---------------- #

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch GitHub Trending, write to Feishu Bitable, and send Feishu interactive card."
    )
    parser.add_argument(
        "--lang",
        dest="language",
        default=None,
        help="Programming language, e.g. python, rust, go. Default: all languages.",
    )
    parser.add_argument(
        "--since",
        dest="since",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="Trending period: daily / weekly / monthly. Default: daily.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="How many top repos to include. Default: 10.",
    )
    parser.add_argument(
        "--webhook",
        dest="webhook",
        default=None,
        help="Feishu webhook URL. If omitted, will read FEISHU_WEBHOOK_URL env.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    webhook_url = args.webhook or os.getenv("FEISHU_WEBHOOK_URL")
    if not webhook_url:
        print(
            "ERROR: Feishu webhook URL not provided. "
            "Use --webhook or set FEISHU_WEBHOOK_URL env.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        repos = fetch_trending(args.language, args.since)
    except Exception as e:
        print(f"[ERROR] Failed to fetch GitHub Trending: {e}", file=sys.stderr)
        sys.exit(1)

    if not repos:
        print("[WARN] No trending repositories found.", file=sys.stderr)
        sys.exit(0)

    # 1) 写入多维表格（如果配置齐全）
    bitable_ready = all(
        [FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID]
    )
    if not bitable_ready:
        print(
            "[INFO] Bitable env vars not fully set; skip writing to table.",
            file=sys.stderr,
        )
    else:
        try:
            records = build_bitable_records(
                repos=repos,
                language=args.language,
                since=args.since,
                limit=args.limit,
            )
            write_records_to_bitable(records)
        except Exception as e:
            print(f"[ERROR] Failed to write records to Bitable: {e}", file=sys.stderr)

    # 2) 发送卡片到群
    card = build_feishu_card(
        repos=repos,
        language=args.language,
        since=args.since,
        limit=args.limit,
    )

    try:
        send_card_to_feishu(webhook_url, card)
    except Exception as e:
        print(f"[ERROR] Failed to send card to Feishu: {e}", file=sys.stderr)
        sys.exit(1)

    print("Done: wrote records (if enabled) and sent GitHub Trending card to Feishu.")


if __name__ == "__main__":
    main()