#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/gateway-console
DATA_DIR=/var/lib/gateway-console
SERVICE_USER=gateway-console
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_PACKAGE_URL="${GATEWAY_PACKAGE_URL:-https://raw.githubusercontent.com/yingzi-max/gateway-console/main/gateway-console.tar.gz}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run this installer as root: sudo bash install.sh" >&2
  exit 1
fi

# This installer performs a clean rebuild. Remove the previous application and
# its data before downloading/installing the new copy.
systemctl stop gateway-console 2>/dev/null || true
rm -rf -- "$APP_DIR" "$DATA_DIR"

if [[ ! -f "$SOURCE_DIR/app.py" || ! -d "$SOURCE_DIR/static" || ! -d "$SOURCE_DIR/ops" || ! -d "$SOURCE_DIR/sources" ]]; then
  WORK_DIR="$(mktemp -d)"
  trap 'rm -rf "$WORK_DIR"' EXIT
  curl --fail --location --proto '=https' --tlsv1.2 "$GATEWAY_PACKAGE_URL" -o "$WORK_DIR/gateway-console.tar.gz"
  install -d -m 0700 "$WORK_DIR/package"
  tar -xzf "$WORK_DIR/gateway-console.tar.gz" -C "$WORK_DIR/package"
  SOURCE_DIR="$WORK_DIR/package"
fi

for required in app.py static ops sources; do
  if [[ ! -e "$SOURCE_DIR/$required" ]]; then
    echo "Package is incomplete: missing $required" >&2
    exit 2
  fi
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 nginx certbot python3-certbot-nginx sudo ca-certificates curl

# Make the public HTTP/HTTPS challenge ports reachable when UFW is installed.
# Do not enable UFW here, because enabling a pre-existing firewall can lock out SSH.
if command -v ufw >/dev/null 2>&1; then
  ufw allow 80/tcp >/dev/null || true
  ufw allow 443/tcp >/dev/null || true
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o root -g root -m 0755 "$APP_DIR" "$APP_DIR/static" "$APP_DIR/ops" "$APP_DIR/sources"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR"
install -o root -g root -m 0644 "$SOURCE_DIR/app.py" "$APP_DIR/app.py"
install -o root -g root -m 0644 "$SOURCE_DIR/static/index.html" "$APP_DIR/static/index.html"
install -o root -g root -m 0644 "$SOURCE_DIR/static/styles.css" "$APP_DIR/static/styles.css"
install -o root -g root -m 0644 "$SOURCE_DIR/static/app.js" "$APP_DIR/static/app.js"
install -o root -g root -m 0644 "$SOURCE_DIR/ops/nginx-site.conf" "$APP_DIR/ops/nginx-site.conf"
install -o root -g root -m 0644 "$SOURCE_DIR/ops/nginx-static-site.conf" "$APP_DIR/ops/nginx-static-site.conf"
install -o root -g root -m 0644 "$SOURCE_DIR/ops/nginx-static-site-ssl.conf" "$APP_DIR/ops/nginx-static-site-ssl.conf"
install -o root -g root -m 0644 "$SOURCE_DIR/sources/landing-page.html" "$APP_DIR/sources/landing-page.html"
install -o root -g root -m 0755 "$SOURCE_DIR/ops/gateway-domain-helper" /usr/local/sbin/gateway-domain-helper
install -o root -g root -m 0644 "$SOURCE_DIR/ops/gateway-console.service" /etc/systemd/system/gateway-console.service

ADMIN_USER="${GATEWAY_ADMIN_USER:-admin}"
ADMIN_PASSWORD="${GATEWAY_ADMIN_PASSWORD:-$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 18 || true)}"
if [[ ! "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,40}$ ]]; then
  echo "GATEWAY_ADMIN_USER contains unsupported characters" >&2
  exit 2
fi
if [[ ! "$ADMIN_PASSWORD" =~ ^[A-Za-z0-9._@%+=:,/!-]{10,128}$ ]]; then
  echo "GATEWAY_ADMIN_PASSWORD must be 10-128 characters using letters, numbers, or ._@%+=:,/!-" >&2
  exit 2
fi

umask 077
{
  printf 'GATEWAY_DATA_DIR=%s\n' "$DATA_DIR"
  printf 'GATEWAY_ADMIN_USER=%s\n' "$ADMIN_USER"
  printf 'GATEWAY_ADMIN_PASSWORD=%s\n' "$ADMIN_PASSWORD"
  printf 'GATEWAY_DOMAIN_HELPER=/usr/local/sbin/gateway-domain-helper\n'
  printf 'GATEWAY_HELPER_USE_SUDO=1\n'
} > /etc/gateway-console.env
if [[ -n "${CERTBOT_EMAIL:-}" ]] && [[ ! "$CERTBOT_EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]]; then
  echo "CERTBOT_EMAIL format is invalid" >&2
  exit 2
fi
printf 'CERTBOT_EMAIL=%s\n' "${CERTBOT_EMAIL:-}" > /etc/gateway-console-certbot.env
chmod 0600 /etc/gateway-console.env /etc/gateway-console-certbot.env

cat > /etc/sudoers.d/gateway-console <<'SUDOERS'
gateway-console ALL=(root) NOPASSWD: /usr/local/sbin/gateway-domain-helper *
SUDOERS
chmod 0440 /etc/sudoers.d/gateway-console
visudo -cf /etc/sudoers.d/gateway-console

install -o root -g root -m 0644 "$SOURCE_DIR/ops/admin-nginx.conf" /etc/nginx/sites-available/gateway-console-admin.conf
ln -sfn /etc/nginx/sites-available/gateway-console-admin.conf /etc/nginx/sites-enabled/gateway-console-admin.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t

systemctl daemon-reload
systemctl enable --now gateway-console nginx
systemctl reload nginx

SERVER_IP="$(curl -4fsS --max-time 5 https://api.ipify.org 2>/dev/null || curl -4fsS --max-time 5 https://ifconfig.me 2>/dev/null || curl -4fsS --max-time 5 https://api4.my-ip.io/ip 2>/dev/null || true)"
if [[ -z "$SERVER_IP" ]]; then
  SERVER_IP="请在云服务器控制台查看公网IP"
fi
echo
echo "Gateway Console installed successfully."
echo "Address: http://${SERVER_IP:-SERVER_IP}/"
echo "Username: $ADMIN_USER"
echo "Password: $ADMIN_PASSWORD"
echo "Store this password now. It is not printed again."
