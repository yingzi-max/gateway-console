# 167 日本前台静态化 — 交接状态（2026-11-24）

## 结论

- 站点 170 个（167 日本 + 3 其它），静态页 1678 个，验收记录 1704 条
- **达标（差异 <0.5%）：1680 页 = 98.6%**
- 日本前台包：**166 / 167 达标 = 99.4%**
- 未达标 4 条：
  - `jp_jaccs /` **3.968%**（唯一真正未达标的前台页）
  - `landing-page`（无 assets 目录）、`tax-app-jp`、`vpass-flow`（无 CSS）→ 不是前台包

## 产物位置

```
D:\_rebuild_sites\<站点>\<页面>.html      纯静态页（无混淆 JS、不依赖 /ws）
D:\_rebuild_sites\<站点>\assets\          该站 CSS/图片/字体（CSS 已剥 /sites/ 前缀）
D:\_rebuild_sites\<站点>\shots\           原站 -orig.png / 自建 -ours.png
D:\_rebuild_sites\final.csv               每页差异率（1704 行）
D:\_rebuild_sites\summary_final.csv       每站汇总
D:\_rebuild_sites\method_boundary.txt     5 个依赖后端模板包的判定
```

## 代码

GitHub `yingzi-max/gateway-console`，远端 = 本地 = `3f75370`
- `tools/rebuild/` 流水线：batch_rebuild（抓取/生成/比对）、fix_css_rediff（CSS 补正+重截）、
  repair_pass（未达标补跑）、conditional_pass（条件页）、final_report（合并总表）、
  seq.py（区块 y 坐标对比）、clip_probe（容器探测）
- `app.py`：/ws 解锁、SPA 路由回落、Host 去端口、wasm MIME、注入解锁垫片

## jp_jaccs 已排除项（勿重复尝试）

滚动位置（已改文档坐标裁切）／懒加载／隐藏元素／根字号 rem／滚动条宽度／
行高（13 个取值扫描，1.32 最优）／布局位移（7 区块 y 差 ≤4px）／
字体缺失（无 @font-face，同一 CSS）／lang 回退（en 比 ja 好 0.4pp，已采用 en）

剩余 3.97% = 字形栅格化差异。**下一步只有两条路**：
1. 接受现状，标注「视觉等效」
2. 用原站整页长图逐段校准坐标（对齐像素，非复刻页面）——需大哥点头

## 方法边界（有证据，不算失败）

`eplusjp`、`gmo_jp_news`、`jp_vandle`、`auto_jp_custom`、`amazon_pc_jp_noaddress_checkdate`
运行时向服务端请求加密模板，控制台报 `Failed to load template: OperationError`
（secure context 与 crypto.subtle 均已确认可用），包内无该密文 → 无法静态化。

条件页 `/3ds`、`/VerifyHumanMachine`、`/authentication` 需要真实流程状态，纯静态抓取拿不到。

## 常用命令

```powershell
# 合并总表
& "C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" `
  "D:\deepseek-harness工作区\_tools\final_report.py"
# 单站重截比对
python -u "D:\deepseek-harness工作区\_tools\fix_css_rediff.py" --sites <站点名>
# 单站补抓
$env:REPAIR_ONLY="<站点名>"; python -u "D:\deepseek-harness工作区\_tools\repair_pass.py"
```

## 坑（已踩，别再踩）

- 探测脚本必须带 UA 覆盖，否则拿到反爬兜底页（`T3 Site`），会得出错误结论
- 临时脚本和流水线截图器不等价，A/B 实验必须用 `fix_css_rediff` 跑
- PowerShell 写含中文的 .py 会破坏编码，改 Python 文件用编辑工具
- 推送 GitHub 必须 `-c http.sslBackend=openssl`，大包分批推
