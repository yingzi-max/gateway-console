# Gateway Console 后台

一个可直接部署到 Debian/Ubuntu 服务器的轻量后台。使用 Python 标准库和 SQLite，不依赖第三方 Python 包。

## 已实现

- 用户名、密码和一次性数字验证码登录
- 仪表板：今日访问（每天 22:00 开始新周期）、总访问、访问/点击、域名数量
- 数据中心：按域名和事件类型查询编号、时间、IP、UA
- 前台配置：源码列表下载落地页、登记服务器现有源码、配置域名、生成 Nginx 反向代理、申请 Let's Encrypt 证书
- 系统设置：IPRegistry API Key、国家黑白名单、设备拦截、风险 IP 类型和拦截跳转地址
- 公开采集接口和防护判断接口

## 本地运行

```bash
python app.py --host 127.0.0.1 --port 8787
```

打开 `http://127.0.0.1:8787`。本地初始账号为 `admin`，密码为 `admin123456`。服务器安装时会生成随机密码。

## 服务器安装

如果把 `install.sh` 和 `gateway-console.tar.gz` 放在同一个公开目录，也可以直接执行：

```bash
curl -fsSL https://raw.githubusercontent.com/yingzi-max/gateway-console/main/install.sh -o install.sh
chmod 700 install.sh
sudo ./install.sh
```

安装脚本默认从 GitHub Raw 下载源码包，也可以用 `GATEWAY_PACKAGE_URL` 覆盖这个地址。

推荐把整个目录打包为 `tar.gz`，上传到服务器后执行：

```bash
tar -xzf gateway-console.tar.gz
cd gateway-console
sudo CERTBOT_EMAIL=admin@example.com bash install.sh
```

也可以让安装脚本下载发布包：

```bash
curl -fsSLO https://你的下载地址/install.sh
sudo GATEWAY_PACKAGE_URL=https://你的下载地址/gateway-console.tar.gz \
  CERTBOT_EMAIL=admin@example.com bash install.sh
```

支持提前指定管理员账号和密码：

```bash
sudo GATEWAY_ADMIN_USER=admin GATEWAY_ADMIN_PASSWORD='StrongPassword2026!' bash install.sh
```

安装后后台监听 `127.0.0.1:8787`，由 Nginx 对外提供 80 端口。建议再给后台自身绑定一个独立管理域名并启用 HTTPS，同时用防火墙限制管理入口。

## 前台采集与防护

源码列表目前内置一份 `常胜株LINE 落地页` HTML。下载后会复制到数据目录的 `projects/landing-page/index.html` 并登记到“已下载”。该 HTML 还引用 `images/`、`css/` 和 `api.php`，这些配套资源和接口需要后续一起补充。

访问和点击可以使用 GET，也可以用 JSON POST：

```js
fetch('https://后台域名/track/visit?domain=www.example.com&path=/');
fetch('https://后台域名/track/click?domain=www.example.com&path=/buy');
```

防护判断：

```js
const result = await fetch('https://后台域名/guard/check').then(r => r.json());
if (!result.allowed) location.replace(result.redirect_url);
```

`/guard/check` 在后台调用 IPRegistry，不会把 API Key 暴露给前台。

## 证书说明

点击“申请证书”时，后台调用 Certbot 的 Nginx 插件申请 Let's Encrypt 证书并配置 HTTPS。申请前需要确保：

1. 域名 A/AAAA 记录已经指向这台服务器。
2. 公网 80 和 443 端口已放行。
3. 域名没有被 CDN 代理到其他源站，或验证流量能够到达本机。

证书续期由 Certbot 安装的 systemd timer 自动处理。
