# GitHub Trending → 飞书自动推送系统

一个用于自动抓取 **GitHub Trending 榜单**，并同步到 **飞书多维表格（Bitable）**、同时通过 **飞书 Webhook 推送交互式卡片消息到群聊** 的自动化系统。  

当前已部署运行在 [PythonAnywhere](https://www.pythonanywhere.com/)，支持长期无人值守定时运行。

---

## 功能特性

- ✅ 抓取 GitHub Trending 榜单  
  - 支持：**全部语言 / 指定语言**
  - 支持：**daily / weekly / monthly**
- ✅ 通过 Webhook 推送 **飞书交互式卡片**
- ✅ 榜单数据自动写入 **飞书多维表格（Bitable）**
- ✅ 支持 CLI 参数：
  - `--lang`：语言过滤（如 python、rust）
  - `--since`：周期（daily / weekly / monthly）
  - `--limit`：榜单条数
- ✅ 适配 **PythonAnywhere 定时任务**
- ✅ 可作为长期运行的数据采集与信息播报服务

---

## 系统架构

```text
GitHub Trending
        ↓
   Python 抓取脚本
        ↓
+--------------------------+
| 飞书 Webhook 推送卡片消息 | → 群聊通知
+--------------------------+
| 飞书多维表格 API           | → 榜单数据存储
+--------------------------+
```
---

## 配置环境变量

```env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx

FEISHU_APP_ID=cli_xxxxxx
FEISHU_APP_SECRET=xxxxxxxx
FEISHU_BITABLE_APP_TOKEN=bascnxxxxxxxx
FEISHU_BITABLE_TABLE_ID=tblxxxxxxxx
```
---

## 运行脚本

```bash
python github_trending_feishu_card.py --lang python --since daily --limit 10
```
---
