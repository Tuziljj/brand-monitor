魔形智能舆情监控系统

基于 GitHub Actions + Python 的自动化品牌舆情监控工具，采用混合抓取策略覆盖国内主流互联网平台的公开信息，关键词命中后自动推送飞书富文本卡片消息。

监控覆盖范围

平台类别	数据源	类型	覆盖内容	
搜索引擎	百度新闻	新闻聚合	全网新闻报道	
搜索引擎	百度搜索	网页搜索	全网网页、百科、企业信息	
社交媒体	B站	视频搜索	视频内容、UP主发布	
社交媒体	搜狗微信	公众号搜索	微信公众号文章	
搜索引擎	搜狗搜索	网页搜索	全网网页内容补充	

监控关键词

- `魔形智能` — 品牌名
- `徐凌杰` — CEO/创始人
- `金琛` — 联合创始人
- `Token超级工厂` — 产品/技术概念

项目结构

```
.
├── monitor.py                  # 主程序（混合抓取策略）
├── requirements.txt            # Python 依赖
├── history.json                # 推送历史记录（自动创建/更新）
├── .github/workflows/
│   └── monitor.yml             # GitHub Actions 工作流
└── README.md                   # 本文件
```

---

快速开始

1. 创建 GitHub 仓库

新建一个私有仓库（建议私有，避免暴露关键词），将本项目的文件上传到仓库中。

2. 配置飞书机器人

1. 在飞书中打开目标群聊
2. 群设置 → 群机器人 → 添加机器人
3. 选择「自定义机器人」
4. 安全设置：添加关键词 `舆情监控提醒`
5. 保存 Webhook 地址（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/xxxx`）

3. 配置 GitHub Secrets

进入仓库 → Settings → Secrets and variables → Actions → New repository secret：

Name	Value	
`FEISHU_WEBHOOK`	飞书机器人的 Webhook 完整地址	

> `GITHUB_TOKEN` 由 GitHub Actions 自动注入，无需手动配置。

4. 开启 Actions 写权限

Settings → Actions → General → Workflow permissions → 勾选 Read and write permissions

5. 测试运行

进入 Actions 标签页 → 选择 魔形智能舆情监控 → Run workflow → 等待执行完成 → 检查飞书群是否收到消息。

---

工作原理

混合抓取策略

由于 RSSHub 公共实例在国内网络环境下不稳定，本系统采用直接抓取各平台搜索页面的混合策略：

1. 百度新闻搜索 — 使用 Session 机制获取 Cookie 后搜索，覆盖全网新闻报道
2. 百度搜索 — 补充网页、百科、企业信息等非新闻内容
3. 搜狗微信搜索 — 覆盖微信公众号文章（重要自媒体渠道）
4. B站视频搜索 — 调用官方 API 获取视频内容
5. 搜狗网页搜索 — 作为百度的补充，覆盖不同索引范围

关键词匹配

- 标题和摘要同时进行大小写不敏感匹配
- 命中任意一个关键词即触发推送
- 消息卡片中会显示具体命中了哪些关键词

去重机制

- 基于 URL + 标题前缀的 MD5 哈希去重
- 历史记录保存在 `history.json`，每次运行后自动更新
- 已推送过的内容不会重复推送

---

自定义配置

修改监控关键词

编辑 `monitor.py` 中的 `KEYWORDS` 列表：

```python
KEYWORDS = ["魔形智能", "徐凌杰", "金琛", "Token超级工厂"]
```

添加/删除数据源

编辑 `monitor.py` 末尾的 `DATA_SOURCES` 列表：

```python
DATA_SOURCES = [
    {"name": "百度新闻", "fetcher": fetch_baidu_news,
     "keywords": ["魔形智能", "徐凌杰"], "delay": 3},
    # 添加你的数据源...
]
```

每个数据源配置字段：
- `name` — 显示名称
- `fetcher` — 抓取函数（需返回 `List[Dict]`）
- `keywords` — 该数据源要搜索的关键词列表
- `delay` — 抓取间隔（秒），避免请求过快被封

调整运行频率

编辑 `.github/workflows/monitor.yml`：

```yaml
schedule:
  - cron: '*/30 * * * *'   # 每30分钟（默认）
  - cron: '0 * * * *'      # 每小时
  - cron: '0 */6 * * *'    # 每6小时
```

---

数据源抓取函数说明

若需扩展新数据源，抓取函数需遵循以下接口：

```python
def fetch_example(keyword: str) -> List[Dict]:
    """
    抓取函数模板
    
    Args:
        keyword: 搜索关键词
        
    Returns:
        [{"title": "标题", "url": "链接", "summary": "摘要",
          "source": "来源名", "pub_time": "发布时间"}, ...]
    """
    results = []
    # ... 抓取逻辑 ...
    return results
```

---

故障排查

问题	解决方法	
飞书未收到消息	检查 `FEISHU_WEBHOOK` Secret 是否配置正确；查看 Actions 日志中的错误信息	
百度数据源返回0条	百度的反爬机制可能触发，系统会自动处理，如持续失败请增加 `delay` 值	
history.json 未提交	检查 Workflow permissions 是否设置为 Read and write	
某些关键词无结果	该关键词可能在对应平台无公开内容，属于正常现象	
推送过于频繁	增加 `.github/workflows/monitor.yml` 中的 cron 间隔	

---

技术架构

```
GitHub Actions (Ubuntu)
    │
    ├─ cron 定时触发 / 手动触发
    │
    ▼
Python 3.10
    │
    ├─ requests + BeautifulSoup4 → HTML 页面抓取
    ├─ requests → B站 API 调用
    │
    ▼
关键词匹配引擎
    │
    ├─ 标题匹配 + 摘要匹配
    ├─ 大小写不敏感
    │
    ▼
飞书 Webhook → 富文本卡片推送
    │
    ▼
history.json 更新 + git 自动提交
```

---

License

MIT License
