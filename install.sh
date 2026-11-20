#!/usr/bin/env bash
#
# Gateway Console 一键安装脚本
#
#   sudo bash install.sh
#
# 环境变量（可选）：
#   GATEWAY_ADMIN_USER      管理员账号，默认 admin
#   GATEWAY_ADMIN_PASSWORD  管理员密码，默认随机生成
#   GATEWAY_DATA_DIR        数据目录，默认 /var/lib/gateway-console
#   GATEWAY_APP_DIR         程序目录，默认 /opt/gateway-console
#   GATEWAY_PRESERVE_DATA   设为 1 时保留已有数据（升级用），默认 0
#   GATEWAY_CAPTCHA_SECRET  人机验证签名密钥（多实例必须统一）
#   CERTBOT_EMAIL           证书通知邮箱
#
set -euo pipefail

APP_DIR="${GATEWAY_APP_DIR:-/opt/gateway-console}"
DATA_DIR="${GATEWAY_DATA_DIR:-/var/lib/gateway-console}"
SERVICE_USER=gateway-console
SERVICE_NAME=gateway-console
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRESERVE_DATA="${GATEWAY_PRESERVE_DATA:-0}"
GENERATED_PASSWORD=""

log()  { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[XX]\033[0m %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
  die "需要 root 权限，请执行：sudo bash install.sh"
fi

# ------------------------------------------------------------------ 自举下载
# 两种用法都支持：
#   1) 已解压安装包：sudo bash install.sh
#   2) 只下脚本（服务器一条命令）：
#        curl -fsSL https://raw.githubusercontent.com/yingzi-max/gateway-console/main/install.sh \
#          -o /tmp/gateway-install.sh && chmod 700 /tmp/gateway-install.sh && sudo /tmp/gateway-install.sh
#      脚本发现同目录没有 app.py，就自己把源码仓库拉到 /tmp 再重新执行。
REPO_URL="${GATEWAY_REPO_URL:-https://github.com/yingzi-max/gateway-console.git}"
REPO_REF="${GATEWAY_REPO_REF:-main}"
if [[ ! -f "$SOURCE_DIR/app.py" ]]; then
  echo
  log "未在 $SOURCE_DIR 找到安装包，进入自动下载模式"
  if ! command -v git >/dev/null 2>&1; then
    log "正在安装 git ..."
    DEBIAN_FRONTEND=noninteractive apt-get update -qq || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends git ca-certificates curl >/dev/null \
      || die "缺少 git 且自动安装失败，请先执行：apt-get install -y git"
  fi
  BOOT_DIR="$(mktemp -d /tmp/gateway-console-src.XXXXXX)"
  log "正在下载源码：$REPO_URL（含日本前台约 155MB，1~3 分钟，别中断）"
  if git clone --depth 1 --branch "$REPO_REF" --progress "$REPO_URL" "$BOOT_DIR"; then
    log "源码下载完成"
  elif [[ -n "${GATEWAY_PACKAGE_URL:-}" ]]; then
    warn "git clone 失败，改用安装包地址：$GATEWAY_PACKAGE_URL"
    curl -fsSL "$GATEWAY_PACKAGE_URL" -o "$BOOT_DIR/pkg.tar.gz" || die "安装包下载失败"
    tar -xzf "$BOOT_DIR/pkg.tar.gz" -C "$BOOT_DIR" || die "安装包解压失败"
    if [[ ! -f "$BOOT_DIR/app.py" ]]; then
      INNER="$(find "$BOOT_DIR" -maxdepth 2 -name app.py -printf '%h\n' 2>/dev/null | head -n 1)"
      [[ -n "$INNER" ]] && BOOT_DIR="$INNER"
    fi
  else
    die "源码下载失败。请确认这台服务器能访问 GitHub；不能的话改用：
    sudo GATEWAY_PACKAGE_URL=<安装包直链> bash /tmp/gateway-install.sh"
  fi
  [[ -f "$BOOT_DIR/app.py" ]] || die "下载内容不完整（缺少 app.py）"
  export GATEWAY_BOOT_DIR="$BOOT_DIR"
  exec bash "$BOOT_DIR/install.sh"
fi

# ---------------------------------------------------------------- 依赖检查
for tool in python3 systemctl; do
  command -v "$tool" >/dev/null 2>&1 || die "缺少 $tool，请先安装后重试"
done

# ------------------------------------------------------- 源码定位（可打包安装）
if [[ ! -f "$SOURCE_DIR/app.py" ]]; then
  die "未在 $SOURCE_DIR 找到 app.py，请确认解压了完整安装包"
fi
for required in app.py static ops sources; do
  [[ -e "$SOURCE_DIR/$required" ]] || die "安装包不完整，缺少 $required"
done
log "安装包检查通过：$SOURCE_DIR"

# --------------------------------------------------------------- 环境信息
echo
echo "  系统      : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -s)"
echo "  Python    : $(python3 --version 2>&1)"
echo "  程序目录  : $APP_DIR"
echo "  数据目录  : $DATA_DIR"
echo

# ------------------------------------------------------ 停止服务并备份数据
EXISTING_DATA=0
if [[ -d "$DATA_DIR" ]]; then
  EXISTING_DATA=1
fi

BACKUP_DIR=""
if [[ "$PRESERVE_DATA" != "1" && "$EXISTING_DATA" == "1" ]]; then
  warn "检测到已有数据目录：$DATA_DIR"
  if [[ -t 0 ]]; then
    read -r -p "  保留已有数据？输入 y 保留（升级），直接回车将清空：" answer
  else
    answer=""
  fi
  if [[ "${answer,,}" == "y" ]]; then
    PRESERVE_DATA=1
  fi
fi

if [[ "$PRESERVE_DATA" == "1" && "$EXISTING_DATA" == "1" ]]; then
  BACKUP_DIR="$(mktemp -d /tmp/gateway-backup-XXXXXX)"
  cp -a "$DATA_DIR" "$BACKUP_DIR/"
  log "已有数据已备份到 $BACKUP_DIR"
fi

systemctl stop "$SERVICE_NAME" 2>/dev/null || true

if [[ "$PRESERVE_DATA" == "1" ]]; then
  # 只替换程序，保留数据
  rm -rf -- "$APP_DIR"
  log "已保留数据目录（升级模式）"
else
  if [[ "$EXISTING_DATA" == "1" ]]; then
    rm -rf -- "$DATA_DIR"
    warn "已有数据已清空"
  fi
  rm -rf -- "$APP_DIR"
fi

# ------------------------------------------------------------------ 依赖安装
echo
log "安装系统依赖（python3 / nginx / certbot）..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 nginx certbot python3-certbot-nginx sudo ca-certificates curl

if command -v ufw >/dev/null 2>&1; then
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  log "已放行 80/443 端口（UFW）"
fi

# ------------------------------------------------------------------ 运行用户
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  log "已创建服务账号：$SERVICE_USER"
fi

# ------------------------------------------------------------------ 目录准备
install -d -m 0755 "$APP_DIR" "$APP_DIR/static" "$APP_DIR/ops"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$DATA_DIR/projects"

# ------------------------------------------------------------- 程序文件同步
install -o root -g root -m 0644 "$SOURCE_DIR/app.py" "$APP_DIR/app.py"

# 根目录下其余 Python 模块（sources_catalog.py 等）必须一起装。
# 漏掉 sources_catalog.py 时后台不会报错，只会退回硬编码的 3 条源码，
# 表现为「源码列表里看不到日本那 167 个站」。
for py_file in "$SOURCE_DIR"/*.py; do
  [[ -e "$py_file" ]] || continue
  [[ "$(basename "$py_file")" == "app.py" ]] && continue
  install -o root -g root -m 0644 "$py_file" "$APP_DIR/$(basename "$py_file")"
  log "已安装模块：$(basename "$py_file")"
done

# 后台静态资源：整目录同步，新增文件无需改脚本
install -d -m 0755 "$APP_DIR/static"
cp -a "$SOURCE_DIR/static/." "$APP_DIR/static/"
find "$APP_DIR/static" -type d -exec chmod 0755 {} +
find "$APP_DIR/static" -type f -exec chmod 0644 {} +
# 人机验证素材必须存在，否则验证页图片 404
if [[ -d "$SOURCE_DIR/static/captcha" ]]; then
  install -d -m 0755 "$APP_DIR/static/captcha"
  cp -a "$SOURCE_DIR/static/captcha/." "$APP_DIR/static/captcha/"
  log "人机验证素材已安装"
fi

# ops 目录
for op_file in "$SOURCE_DIR"/ops/*; do
  [[ -f "$op_file" ]] || continue
  install -o root -g root -m 0755 "$op_file" "$APP_DIR/ops/$(basename "$op_file")"
done

# ------------------------------------------------------------- 模板目录同步
install -d -m 0755 "$APP_DIR/sources"
shopt -s nullglob
template_dirs=("$SOURCE_DIR"/sources/*/)
if [[ ${#template_dirs[@]} -eq 0 ]]; then
  die "安装包不完整：sources/ 下没有模板目录"
fi
for template_dir in "${template_dirs[@]}"; do
  template_name="$(basename "$template_dir")"
  rm -rf "$APP_DIR/sources/$template_name"
  install -d -m 0755 "$APP_DIR/sources/$template_name"
  cp -a "$template_dir." "$APP_DIR/sources/$template_name/"
  find "$APP_DIR/sources/$template_name" -type d -exec chmod 0755 {} +
  find "$APP_DIR/sources/$template_name" -type f -exec chmod 0644 {} +
  # 已安装的项目副本同步更新（保留用户数据目录结构）
  if [[ -d "$DATA_DIR/projects/$template_name" ]]; then
    cp -a "$template_dir." "$DATA_DIR/projects/$template_name/"
    find "$DATA_DIR/projects/$template_name" -type d -exec chmod 0755 {} +
    find "$DATA_DIR/projects/$template_name" -type f -exec chmod 0644 {} +
    # cp -a keeps the source owner (root); the service runs unprivileged, so a
    # root-owned index.html would surface as a bare 403 on the document while
    # assets still loaded fine.
    chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR/projects/$template_name"
  fi
  log "模板已安装：$template_name"
done
shopt -u nullglob

# ------------------------------------------------------------------ 系统组件
install -o root -g root -m 0755 "$SOURCE_DIR/ops/gateway-domain-helper" /usr/local/sbin/gateway-domain-helper

# The unit is a template so a custom APP_DIR/DATA_DIR produces a matching unit.
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@DATA_DIR@|$DATA_DIR|g" \
  "$SOURCE_DIR/ops/gateway-console.service" > /etc/systemd/system/gateway-console.service
chmod 0644 /etc/systemd/system/gateway-console.service

install -o root -g root -m 0644 "$SOURCE_DIR/ops/gateway-certbot-renew.service" /etc/systemd/system/gateway-certbot-renew.service
install -o root -g root -m 0644 "$SOURCE_DIR/ops/gateway-certbot-renew.timer" /etc/systemd/system/gateway-certbot-renew.timer

# --------------------------------------------------------------- 管理员账号
ADMIN_USER="${GATEWAY_ADMIN_USER:-admin}"
if [[ -n "${GATEWAY_ADMIN_PASSWORD:-}" ]]; then
  ADMIN_PASSWORD="$GATEWAY_ADMIN_PASSWORD"
else
  ADMIN_PASSWORD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 18 || true)"
  # 随机生成可能失败或过短，必须给一个合法兜底值，否则下面的格式校验会直接 die
  [[ ${#ADMIN_PASSWORD} -ge 10 ]] || ADMIN_PASSWORD="Gw$(date +%s)"
  GENERATED_PASSWORD="$ADMIN_PASSWORD"
fi
if [[ ! "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,40}$ ]]; then
  die "GATEWAY_ADMIN_USER 含不支持的字符"
fi
if [[ ! "$ADMIN_PASSWORD" =~ ^[A-Za-z0-9._@%+=:,/!-]{10,128}$ ]]; then
  die "GATEWAY_ADMIN_PASSWORD 需为 10-128 位字母数字或 ._@%+=:,/!-"
fi

# 人机验证密钥：多实例部署必须一致
if [[ -n "${GATEWAY_CAPTCHA_SECRET:-}" ]]; then
  CAPTCHA_SECRET="$GATEWAY_CAPTCHA_SECRET"
elif [[ -f /etc/gateway-console.env ]]; then
  # 升级时沿用原密钥，避免已通过验证的访客被重新拦下
  CAPTCHA_SECRET="$(grep '^GATEWAY_CAPTCHA_SECRET=' /etc/gateway-console.env | cut -d= -f2- || true)"
  # 注意：set -euo pipefail 下 `tr ... | head -c N` 会因head 提前关闭管道
  # 让 tr 收到 SIGPIPE(141)，从而把整个安装脚本静默杀掉。必须 || true 兜住。
  [[ -n "$CAPTCHA_SECRET" ]] || CAPTCHA_SECRET="$(tr -dc 'a-f0-9' </dev/urandom | head -c 40 || true)"
else
  CAPTCHA_SECRET="$(tr -dc 'a-f0-9' </dev/urandom | head -c 40 || true)"
  warn "本次生成的 GATEWAY_CAPTCHA_SECRET（多实例请手动统一）"
fi
# 兜底：随机生成失败时不能留下空密钥，否则所有人机验证签名都会失效
[[ -n "$CAPTCHA_SECRET" ]] || CAPTCHA_SECRET="gw$(date +%s)$$"

umask 077
{
  printf 'GATEWAY_DATA_DIR=%s\n' "$DATA_DIR"
  printf 'GATEWAY_ADMIN_USER=%s\n' "$ADMIN_USER"
  printf 'GATEWAY_ADMIN_PASSWORD=%s\n' "$ADMIN_PASSWORD"
  printf 'GATEWAY_DOMAIN_HELPER=/usr/local/sbin/gateway-domain-helper\n'
  printf 'GATEWAY_HELPER_USE_SUDO=1\n'
  printf 'GATEWAY_CAPTCHA_SECRET=%s\n' "$CAPTCHA_SECRET"
} > /etc/gateway-console.env
chmod 0600 /etc/gateway-console.env

if [[ -n "${CERTBOT_EMAIL:-}" ]]; then
  if [[ ! "$CERTBOT_EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]]; then
    die "CERTBOT_EMAIL 格式不正确"
  fi
  printf 'CERTBOT_EMAIL=%s\n' "$CERTBOT_EMAIL" > /etc/gateway-console-certbot.env
else
  printf 'CERTBOT_EMAIL=\n' > /etc/gateway-console-certbot.env
fi
chmod 0600 /etc/gateway-console-certbot.env

cat > /etc/sudoers.d/gateway-console <<'SUDOERS'
gateway-console ALL=(root) NOPASSWD: /usr/local/sbin/gateway-domain-helper *
SUDOERS
chmod 0440 /etc/sudoers.d/gateway-console
visudo -cf /etc/sudoers.d/gateway-console >/dev/null

# ------------------------------------------------------------------ Nginx
rm -f /etc/nginx/sites-enabled/default
find /etc/nginx/sites-enabled -maxdepth 1 -name 'gateway-*.conf' ! -name 'gateway-console-admin.conf' -delete 2>/dev/null || true
find /etc/nginx/sites-available -maxdepth 1 -name 'gateway-*.conf' ! -name 'gateway-console-admin.conf' -delete 2>/dev/null || true
install -o root -g root -m 0644 "$SOURCE_DIR/ops/admin-nginx.conf" /etc/nginx/sites-available/gateway-console-admin.conf
ln -sfn /etc/nginx/sites-available/gateway-console-admin.conf /etc/nginx/sites-enabled/gateway-console-admin.conf
nginx -t

# ------------------------------------------------------------------ 启动服务
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl enable --now gateway-certbot-renew.timer 2>/dev/null || true
systemctl reload nginx

sleep 3
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  warn "服务未正常运行，最近日志："
  journalctl -u "$SERVICE_NAME" --no-pager -n 15
  die "安装失败"
fi

HEALTH_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8787/ 2>/dev/null || true)"
HEALTH_CODE="${HEALTH_CODE:-000}"
if [[ "$HEALTH_CODE" != "200" ]]; then
  warn "健康检查返回 HTTP $HEALTH_CODE，最近日志："
  journalctl -u "$SERVICE_NAME" --no-pager -n 15
  die "安装后自检失败"
fi
log "健康检查通过（HTTP $HEALTH_CODE）"

SERVER_IP="$(curl -4fsS --max-time 5 https://api.ipify.org 2>/dev/null \
  || curl -4fsS --max-time 5 https://ifconfig.me 2>/dev/null || echo "")"
[[ -n "$SERVER_IP" ]] || SERVER_IP="<服务器公网IP>"

cat <<SUMMARY

════════════════════════════════════════════════════════
  Gateway Console 安装完成
════════════════════════════════════════════════════════
  访问地址 : http://${SERVER_IP}/
  管理账号 : ${ADMIN_USER}
  管理密码 : ${ADMIN_PASSWORD}
  程序目录 : ${APP_DIR}
  数据目录 : ${DATA_DIR}
  服务状态 : $(systemctl is-active "$SERVICE_NAME")
  健康检查 : HTTP ${HEALTH_CODE}
════════════════════════════════════════════════════════

  常用命令：
    systemctl status gateway-console      查看状态
    systemctl restart gateway-console     重启
    journalctl -u gateway-console -n 50  查看日志

SUMMARY

if [[ -n "$GENERATED_PASSWORD" ]]; then
  warn "管理员密码是随机生成的，请立即保存！仅显示这一次。"
fi
if [[ -n "$BACKUP_DIR" ]]; then
  echo "  原数据备份 : $BACKUP_DIR"
fi

# 自举下载的临时源码目录，装完就删（省 633MB 磁盘）
if [[ -n "${GATEWAY_BOOT_DIR:-}" && -d "${GATEWAY_BOOT_DIR}" ]]; then
  rm -rf -- "$GATEWAY_BOOT_DIR"
  log "已清理临时下载目录：$GATEWAY_BOOT_DIR"
fi