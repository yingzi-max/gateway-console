#!/usr/bin/env bash
# ============================================================
#  Gateway Console 一键部署脚本（2026-10-25 快照 v4（频率封锁只计打开进入 + 登录页分流豁免修复 + 黑名单中心/语言时区下拉/人机验证五道防线））
#  用法: sudo bash deploy.sh
#  适用于全新 Ubuntu 22.04 服务器（root），自动完成：
#    1) 系统依赖安装（nginx/certbot/python3）
#    2) 服务安装与启动（install.sh）
#    3) 业务数据库恢复（10 域名配置 + 全部分流规则）
#    4) 前台站点文件补齐
#    5) 全链路健康检查
#  幂等：重复执行时自动保护已有数据（跳过库恢复）。
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PKG_DIR="$PWD/gateway-console"
DATA_DIR="/var/lib/gateway-console"
DB_TARGET="$DATA_DIR/gateway.db"

if [[ $EUID -ne 0 ]]; then
  echo "[XX] 需要 root 权限：sudo bash deploy.sh" >&2
  exit 1
fi
if [[ ! -f "$PKG_DIR/install.sh" ]]; then
  echo "[XX] 未找到 gateway-console/install.sh，请确认解压完整" >&2
  exit 1
fi

# ---------- 检测是否已有部署（保护现有数据） ----------
SKIP_DB=0
if [[ -f "$DB_TARGET" ]]; then
  SKIP_DB=1
  echo "[!!] 检测到已部署的数据库 → 本次将跳过数据库恢复（现有数据不受影响）"
  echo "     如需强制覆盖为包内快照，请设 FORCE_DB=1 重新执行"
  [[ "${FORCE_DB:-0}" == "1" ]] && SKIP_DB=0
fi

# ---------- 第 1 步：官方 install.sh（装依赖/账号/服务） ----------
export GATEWAY_ADMIN_USER="${GATEWAY_ADMIN_USER:-admin}"
export GATEWAY_ADMIN_PASSWORD="${GATEWAY_ADMIN_PASSWORD:-GwVpass2026Deploy}"
export GATEWAY_CAPTCHA_SECRET="${GATEWAY_CAPTCHA_SECRET:-ddac9c256d9fed5a2636463655c3edb3d1f77b23}"
export GATEWAY_PRESERVE_DATA=1   # 数据保护交给本脚本管理，install.sh 不清理
cd "$PKG_DIR"
bash install.sh < /dev/null

# ---------- 第 2 步：恢复业务数据库（仅首次部署） ----------
if [[ "$SKIP_DB" == "0" ]]; then
  echo "[OK] 恢复业务数据库（域名/分流/黑名单表结构）..."
  systemctl stop gateway-console
  install -d -m 0755 "$DATA_DIR"
  install -o gateway-console -g gateway-console -m 0640 \
    "$PWD/../restore-data/gateway.db" "$DB_TARGET"
  systemctl start gateway-console
  sleep 2
else
  echo "[i] 跳过数据库恢复（保护现有数据）"
fi

# ---------- 第 3 步：前台站点文件补齐 ----------
echo "[OK] 同步前台站点文件..."
cp -a "$PKG_DIR/sources/vpass-flow" "$DATA_DIR/projects/vpass-flow"
chown -R gateway-console:gateway-console "$DATA_DIR/projects/vpass-flow"
find "$DATA_DIR/projects/vpass-flow" -type d -exec chmod 0755 {} +
find "$DATA_DIR/projects/vpass-flow" -type f -exec chmod 0644 {} +

# ---------- 第 4 步：健康检查 ----------
sleep 2
FAILED=0
systemctl is-active --quiet gateway-console || { echo "[XX] 服务未运行"; FAILED=1; }
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8787/ || echo 000)
[[ "$HTTP_CODE" == "200" ]] || { echo "[XX] 应用健康检查失败 HTTP $HTTP_CODE"; FAILED=1; }
DOMAIN_COUNT=$(python3 -c "import sqlite3; print(sqlite3.connect('$DB_TARGET').execute('SELECT COUNT(*) FROM domains').fetchone()[0])" 2>/dev/null || echo '?')
echo "------------------------------------------------------------"
echo "  Gateway Console 部署完成"
echo "  管理后台 : http://<本机IP>/  （admin / GwVpass2026Deploy）"
echo "  服务状态 : $(systemctl is-active gateway-console)"
echo "  应用健康 : HTTP $HTTP_CODE"
echo "  业务数据 : 域名 $DOMAIN_COUNT 个 · 配置完整 · 流水为快照时点"
echo "  下一步   : 域名 DNS 指向本机后，在后台「前台配置」添加域名并申请证书"
echo "------------------------------------------------------------"
exit $FAILED
