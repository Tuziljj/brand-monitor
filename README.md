魔形智能舆情监控系统

基于 GitHub Actions + Python 的自动化品牌舆情监控工具，通过 RSS 源实时抓取互联网信息，关键词命中后自动推送飞书富文本卡片消息。

功能特性

- 多源监控：覆盖 36氪、虎嗅、微博、B站、百度新闻、IT之家、澎湃新闻等 13 个 RSS 源
- 关键词匹配：监控「魔形智能」「徐凌杰」「金琛」「Token超级工厂」四个关键词
- 智能容错：RSSHub 主实例故障时自动切换 3 个备用实例
- 飞书推送：命中后实时推送富文本卡片，包含来源、标题、链接、关键词等信息
- 自动去重：基于 URL 去重，历史记录持久化保存于 `history.json`
- 自动提交：每次运行后自动将历史记录提交回 GitHub 仓库

---

快速开始

1. Fork 本仓库

点击右上角 Fork 按钮，将本仓库复制到你的 GitHub 账号下。

2. 配置飞书机器人 Webhook

创建飞书自定义机器人

1. 打开飞书，进入需要接收告警的群聊
2. 点击群设置（右上角 `...`）→ 群机器人 → 添加机器人
3. 选择 自定义机器人
4. 设置机器人名称（如「舆情监控」）和描述
5. 安全设置建议选择 自定义关键词，添加关键词 `舆情监控提醒`
6. 点击 完成，复制 Webhook 地址

> 保存好 Webhook 地址，格式类似：
`https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

3. 配置 GitHub Secrets

1. 打开你 Fork 的仓库页面
2. 点击 Settings → Secrets and variables → Actions
3. 点击 New repository secret
4. Name 填写：`FEISHU_WEBHOOK`
5. Value 填写：上一步复制的飞书 Webhook 完整地址
6. 点击 Add secret

> `GITHUB_TOKEN` 由 GitHub Actions 自动提供，无需手动配置。

4. 验证运行

手动触发测试

1. 进入仓库的 Actions 标签页
2. 选择左侧的 魔形智能舆情监控 工作流
3. 点击右侧 Run workflow → 选择分支（main）→ Run workflow
4. 等待运行完成，检查飞书群是否收到测试消息

查看运行日志

1. 在 Actions 页面点击具体的运行记录
2. 展开 运行舆情监控 步骤
3. 查看实时日志输出，包括：
   - RSS 源抓取状态（成功/失败/备用切换）
   - 关键词命中记录
   - 飞书推送结果
   - 历史记录更新状态

---

监控数据源

类别	平台	监控对象	
新闻资讯	36氪、虎嗅、少数派、界面新闻、百度新闻、IT之家、澎湃新闻	魔形智能	
社交媒体	微博 × 2、B站	魔形智能 / Token超级工厂	
高管舆情	36氪、微博、百度新闻	徐凌杰	

---

文件说明

```
.
├── monitor.py                  # 主程序：RSS抓取、关键词匹配、飞书推送
├── requirements.txt            # Python 依赖
├── history.json                # 历史记录（自动创建）
├── .github/workflows/monitor.yml   # GitHub Actions 配置
└── README.md                   # 本文件
```

---

自定义配置

添加/删除 RSS 源

编辑 `monitor.py` 文件中的 `RSS_SOURCES` 列表：

```python
RSS_SOURCES = [
    # 添加你的RSS源
    "https://rsshub.app/xxx/xxxx",
]
```

修改监控关键词

编辑 `monitor.py` 文件中的 `KEYWORDS` 列表：

```python
KEYWORDS = ["魔形智能", "徐凌杰", "金琛", "Token超级工厂"]
```

调整运行频率

编辑 `.github/workflows/monitor.yml` 中的 cron 表达式：

```yaml
schedule:
  - cron: '*/30 * * * *'    # 每30分钟（默认）
  - cron: '0 * * * *'       # 每小时
  - cron: '0 */6 * * *'     # 每6小时
```

---

故障排查

问题	排查方法	
飞书未收到消息	检查 Secrets 中 `FEISHU_WEBHOOK` 是否配置正确；查看 Actions 日志中的推送响应	
RSS 全部失败	RSSHub 公共实例可能暂时不可用，系统会自动切换备用实例，等待一段时间后重试	
history.json 未提交	检查仓库的 Actions 权限：Settings → Actions → General → Workflow permissions → 勾选 Read and write permissions	
关键词未命中	确认 RSS 源能正常返回内容；检查关键词大小写不敏感匹配逻辑	

---

技术架构

```
GitHub Actions (Ubuntu)
    │
    ├─ 每30分钟触发
    │
    ▼
Python 3.10
    │
    ├─ feedparser → 解析 RSS 源
    ├─ requests   → HTTP 请求 & 飞书推送
    │
    ▼
关键词匹配引擎
    │
    ├─ 标题匹配
    ├─ 摘要匹配
    │
    ▼
飞书 Webhook
    │
    ▼
富文本卡片推送
```

---

开源协议

MIT License
