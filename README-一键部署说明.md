# Gateway Console 一键部署包 v4（2026-10-25 · 95 最新生产实况）

版本：全套最新修复
- 频率封锁：只统计「打开进入网站」的次数（站内跳转/探针重载/验证后延续不计）
- 登录页分流豁免：入口伪装文件（info.txt/log.gif 等）自动豁免点击拦截器，安卓点登录不再被分走
- 黑名单中心（省 IPRegistry 配额短路）、语言/时区下拉拦截、人机验证五道防线、全部历史修复

数据库：95 最新一致快照；流水已清空（部署后从零开始），域名/配置/黑名单防线数据完整保留。

一键部署：
  tar -xzf gateway-console-onekey-20261025.tar.gz
  cd gateway-console-onekey-20261025
  sudo bash deploy.sh
管理后台 admin / GwVpass2026Deploy。重复部署自动保护现有数据（FORCE_DB=1 强制覆盖）。
