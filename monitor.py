#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
品牌舆情监控脚本 - 魔形智能
混合抓取策略：搜索引擎 + 社交媒体API + 垂直搜索
覆盖：百度、搜狗微信、B站、搜狗搜索 等国内主流平台
推送方式：飞书机器人富文本卡片
"""

import os
import re
import sys
import json
import time
import hashlib
import logging
import requests
from datetime import datetime
from urllib.parse import quote, unquote, urljoin
from typing import Optional, List, Dict, Any

from bs4 import BeautifulSoup

# ==================== 配置区域 ====================

# 监控关键词
KEYWORDS = ["魔形智能", "徐凌杰", "金琛", "Token超级工厂"]

# 请求超时时间（秒）
REQUEST_TIMEOUT = 15

# 历史记录文件路径
HISTORY_FILE = "history.json"

# 飞书 Webhook 环境变量名
FEISHU_WEBHOOK_ENV = "FEISHU_WEBHOOK"

# 请求头模板
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ==================== 工具函数 ====================


def clean_html(text: str) -> str:
    """清除HTML标签和转义字符"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'")
    text = text.replace('&nbsp;', ' ')
    text = text.strip()
    return text


def find_matched_keywords(text: str) -> List[str]:
    """检查文本中命中了哪些关键词，返回命中的关键词列表"""
    if not text:
        return []
    text_lower = text.lower()
    matched = []
    for keyword in KEYWORDS:
        if keyword.lower() in text_lower:
            matched.append(keyword)
    return matched


def dedup_key(url: str, title: str) -> str:
    """生成去重key"""
    key = f"{url}|{title[:40]}"
    return hashlib.md5(key.encode()).hexdigest()


def format_pub_time(ts: Any) -> str:
    """格式化发布时间"""
    if isinstance(ts, (int, float)) and ts > 1000000000:
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError, OverflowError):
            pass
    if isinstance(ts, str) and ts:
        return ts
    return ""


def http_get(url: str, params: dict = None, extra_headers: dict = None,
             timeout: int = None, session: requests.Session = None) -> Optional[requests.Response]:
    """发送HTTP GET请求"""
    headers = dict(HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    
    req_session = session or requests
    try:
        resp = req_session.get(url, params=params, headers=headers,
                               timeout=timeout or REQUEST_TIMEOUT)
        return resp
    except requests.exceptions.Timeout:
        logger.warning(f"请求超时: {url}")
    except requests.exceptions.ConnectionError:
        logger.warning(f"连接失败: {url}")
    except Exception as e:
        logger.warning(f"请求异常: {url} - {e}")
    return None


# ==================== 数据源抓取函数 ====================


def _extract_baidu_sdata(div) -> Dict[str, str]:
    """从百度结果div的s-data注释中提取JSON数据"""
    try:
        # 从div的原始HTML中提取（避免BeautifulSoup解析<em>标签破坏JSON）
        div_html = str(div)
        json_match = re.search(r's-data:\s*({.+?})\s*-->', div_html, re.DOTALL)
        if not json_match:
            json_match = re.search(r's-data:\s*({.+})', div_html, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            # 移除HTML标签（如<em>）
            json_str = re.sub(r'</?[a-zA-Z][^>]*>', '', json_str)
            data = json.loads(json_str)
            return {
                "source_name": data.get("sourceName", ""),
                "disp_time": data.get("dispTime", ""),
                "title": data.get("title", ""),
                "url": data.get("titleUrl", ""),
                "summary": data.get("summary", ""),
            }
    except Exception:
        pass
    return {}


def fetch_baidu_news(keyword: str) -> List[Dict]:
    """
    抓取百度新闻搜索结果
    需要先访问百度首页获取Cookie，再搜索
    """
    session = requests.Session()
    
    # 第一步：访问百度首页获取Cookie
    home = http_get("https://www.baidu.com/", session=session, timeout=10)
    if not home:
        return []
    time.sleep(1)
    
    # 第二步：搜索新闻
    resp = http_get(
        "https://www.baidu.com/s",
        params={"wd": keyword, "tn": "news", "rn": "20"},
        extra_headers={"Referer": "https://www.baidu.com/"},
        session=session,
    )
    if not resp or resp.status_code != 200 or len(resp.text) < 5000:
        logger.debug(f"[百度新闻] 响应异常: status={resp.status_code if resp else 'None'}, len={len(resp.text) if resp else 0}")
        return []

    results = []
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # 百度新闻结果在 div.result-op 或 div.c-container 中
    divs = soup.find_all('div', class_=re.compile(r'result-op|c-container'))
    
    for div in divs:
        try:
            title_tag = div.select_one('h3 a')
            if not title_tag:
                continue
            title = clean_html(title_tag.get_text(strip=True))
            href = title_tag.get('href', '')

            if not title or len(title) < 5 or not href:
                continue
            # 过滤无关内容
            if any(x in title for x in ['', '登录', '注册', '习近平', '总书记']):
                continue

            summary_tag = div.select_one('.content-right_8Zs40, .c-color-text, .content-right')
            summary = clean_html(summary_tag.get_text(strip=True)) if summary_tag else ''

            # 从s-data注释中提取来源名和发布时间
            sdata = _extract_baidu_sdata(div)
            source_name = sdata.get("source_name", "")
            pub_time = sdata.get("disp_time", "")

            # 备用：从span.c-color-gray提取来源名（仅来源名，不含时间）
            if not source_name:
                source_tag = div.select_one('.c-color-gray, .c-gap-right')
                if source_tag:
                    source_name = source_tag.get_text(strip=True)

            results.append({
                "title": title,
                "url": href if href.startswith('http') else f"https://www.baidu.com{href}",
                "summary": summary,
                "source": source_name or "百度新闻",
                "pub_time": pub_time,
                "keyword": keyword,
            })
        except Exception as e:
            logger.debug(f"解析百度新闻条目异常: {e}")
            continue

    logger.info(f"[百度新闻] '{keyword}' 获取 {len(results)} 条")
    return results


def fetch_baidu_web(keyword: str) -> List[Dict]:
    """
    抓取百度搜索网页结果
    """
    session = requests.Session()
    
    # 先访问首页
    home = http_get("https://www.baidu.com/", session=session, timeout=10)
    if not home:
        return []
    time.sleep(1)
    
    resp = http_get(
        "https://www.baidu.com/s",
        params={"wd": keyword, "rn": "20"},
        extra_headers={"Referer": "https://www.baidu.com/"},
        session=session,
    )
    if not resp or resp.status_code != 200 or len(resp.text) < 5000:
        return []

    results = []
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    divs = soup.find_all('div', class_=re.compile(r'result-op|c-container'))
    
    for div in divs:
        try:
            title_tag = div.select_one('h3 a')
            if not title_tag:
                continue
            title = clean_html(title_tag.get_text(strip=True))
            href = title_tag.get('href', '')

            if not title or len(title) < 5 or not href:
                continue
            if any(x in title for x in ['', '登录', '注册', '习近平', '总书记']):
                continue

            abstract_tag = div.select_one('.c-abstract, .content-right_8Zs40, .c-color-text')
            summary = clean_html(abstract_tag.get_text(strip=True)) if abstract_tag else ''

            # 提取发布时间：span[class*="prefix-time_"] 包含日期
            pub_time = ""
            time_tag = div.select_one('span[class*="prefix-time"]')
            if time_tag:
                pub_time = time_tag.get_text(strip=True)

            # 提取来源：cite标签
            source_name = "百度搜索"
            cite_tag = div.select_one('cite, .c-showurl')
            if cite_tag:
                cite_text = cite_tag.get_text(strip=True)
                # cite通常是URL，取域名部分作为来源
                if cite_text and not cite_text.startswith('http'):
                    source_name = f"百度搜索-{cite_text[:30]}"

            results.append({
                "title": title,
                "url": href if href.startswith('http') else f"https://www.baidu.com{href}",
                "summary": summary,
                "source": source_name,
                "pub_time": pub_time,
                "keyword": keyword,
            })
        except Exception as e:
            logger.debug(f"解析百度搜索条目异常: {e}")
            continue

    logger.info(f"[百度搜索] '{keyword}' 获取 {len(results)} 条")
    return results


def fetch_wechat_sogou(keyword: str) -> List[Dict]:
    """
    抓取搜狗微信搜索结果（公众号文章）
    URL: https://weixin.sogou.com/weixin?type=2&query=KEYWORD
    """
    resp = http_get(
        "https://weixin.sogou.com/weixin",
        params={"type": "2", "query": keyword},
        extra_headers={"Referer": "https://weixin.sogou.com/"},
    )
    if not resp or resp.status_code != 200:
        return []

    results = []
    soup = BeautifulSoup(resp.text, 'html.parser')
    items = soup.select('.news-list li')

    for item in items:
        try:
            title_tag = item.select_one('h3 a')
            if not title_tag:
                continue
            title = clean_html(title_tag.get_text(strip=True))
            href = title_tag.get('href', '')
            if not title or not href:
                continue

            if href.startswith('/'):
                href = f"https://weixin.sogou.com{href}"
            elif not href.startswith('http'):
                href = f"https://weixin.sogou.com/{href}"

            summary_tag = item.select_one('p.txt-info, .txt-info, p')
            summary = clean_html(summary_tag.get_text(strip=True)) if summary_tag else ''

            source_tag = item.select_one('.account, .s-p a')
            account = source_tag.get_text(strip=True) if source_tag else ''

            # 时间：在.s-p区域内的script标签中
            pub_time = ''
            sp_tag = item.select_one('.s-p')
            if sp_tag:
                script = sp_tag.find('script')
                if script:
                    time_text = str(script.string or '')
                    time_match = re.search(r"timeConvert\('(\d+)'\)", time_text)
                    if time_match:
                        try:
                            ts = int(time_match.group(1))
                            pub_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                        except (ValueError, OSError):
                            pass

            results.append({
                "title": title,
                "url": href,
                "summary": summary,
                "source": f"微信公众号-{account}" if account else "微信公众号",
                "pub_time": pub_time,
                "keyword": keyword,
            })
        except Exception as e:
            logger.debug(f"解析搜狗微信条目异常: {e}")
            continue

    logger.info(f"[搜狗微信] '{keyword}' 获取 {len(results)} 条")
    return results


def fetch_bilibili(keyword: str) -> List[Dict]:
    """
    抓取B站视频搜索结果
    API: https://api.bilibili.com/x/web-interface/search/type
    """
    resp = http_get(
        "https://api.bilibili.com/x/web-interface/search/type",
        params={
            "keyword": keyword,
            "search_type": "video",
            "page": 1,
            "pagesize": 20,
        },
        extra_headers={
            "Referer": "https://search.bilibili.com/",
            "Accept": "application/json, text/plain, */*",
        },
    )
    if not resp or resp.status_code != 200:
        return []

    results = []
    try:
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"[B站] API错误: {data.get('message', 'unknown')}")
            return []

        items = data.get("data", {}).get("result", [])
        for item in items:
            try:
                title = clean_html(item.get("title", ""))
                bvid = item.get("bvid", "")
                if not title or not bvid:
                    continue

                description = item.get("description", "")
                author = item.get("author", "")
                pubdate_ts = item.get("pubdate", 0)

                results.append({
                    "title": title,
                    "url": f"https://www.bilibili.com/video/{bvid}",
                    "summary": description,
                    "source": f"B站-{author}" if author else "B站",
                    "pub_time": format_pub_time(pubdate_ts),
                    "keyword": keyword,
                })
            except Exception as e:
                logger.debug(f"解析B站条目异常: {e}")
                continue

    except Exception as e:
        logger.warning(f"[B站] JSON解析异常: {e}")

    logger.info(f"[B站] '{keyword}' 获取 {len(results)} 条")
    return results


def fetch_sogou(keyword: str) -> List[Dict]:
    """
    抓取搜狗网页搜索结果
    URL: https://www.sogou.com/web?query=KEYWORD
    """
    resp = http_get(
        "https://www.sogou.com/web",
        params={"query": keyword, "page": "1"},
        extra_headers={"Referer": "https://www.sogou.com/"},
    )
    if not resp or resp.status_code != 200:
        return []

    results = []
    soup = BeautifulSoup(resp.text, 'html.parser')
    items = soup.select('.vrwrap, .rb')

    for item in items:
        try:
            title_tag = item.select_one('h3 a, h3.vr-title a')
            if not title_tag:
                continue
            title = clean_html(title_tag.get_text(strip=True))
            href = title_tag.get('href', '')
            if not title or len(title) < 5 or not href:
                continue

            summary_tag = item.select_one('.str-text, .vr-brief, .abstract')
            summary = clean_html(summary_tag.get_text(strip=True)) if summary_tag else ''

            # 提取发布时间：span.cite-date 或包含日期的span
            pub_time = ""
            cite_date = item.select_one('span.cite-date')
            if cite_date:
                pub_time = cite_date.get_text(strip=True)
            else:
                # 备用：查找包含日期格式的span
                for sp in item.find_all('span'):
                    txt = sp.get_text(strip=True)
                    if re.match(r'\d{4}[-/年]\d{1,2}[-/月]', txt):
                        pub_time = txt
                        break
            # 清理时间中的噪音
            pub_time = pub_time.lstrip('-').strip()

            # 提取来源：cite标签（取域名部分，避免混入时间）
            source_name = "搜狗搜索"
            cite_tag = item.select_one('.citeurl, cite')
            if cite_tag:
                cite_text = cite_tag.get_text(strip=True)
                # 移除时间部分，只保留URL/域名
                cite_text = re.split(r'\s*[-–]\s*\d{4}', cite_text)[0]
                if cite_text and len(cite_text) < 40:
                    source_name = f"搜狗搜索-{cite_text[:25]}"

            results.append({
                "title": title,
                "url": href if href.startswith('http') else f"https://www.sogou.com{href}",
                "summary": summary,
                "source": source_name,
                "pub_time": pub_time,
                "keyword": keyword,
            })
        except Exception as e:
            logger.debug(f"解析搜狗条目异常: {e}")
            continue

    logger.info(f"[搜狗搜索] '{keyword}' 获取 {len(results)} 条")
    return results


# ==================== 数据源注册表 ====================

# 数据源配置：名称、抓取函数、要搜索的关键词列表
DATA_SOURCES = [
    # 百度新闻搜索 - 核心来源
    {"name": "百度新闻", "fetcher": fetch_baidu_news,
     "keywords": ["魔形智能", "徐凌杰", "Token超级工厂"], "delay": 3},

    # 百度搜索（网页）- 补充
    {"name": "百度搜索", "fetcher": fetch_baidu_web,
     "keywords": ["魔形智能", "徐凌杰", "金琛", "Token超级工厂"], "delay": 3},

    # 搜狗微信搜索 - 公众号文章
    {"name": "搜狗微信", "fetcher": fetch_wechat_sogou,
     "keywords": ["魔形智能", "徐凌杰", "Token超级工厂"], "delay": 2},

    # B站视频搜索
    {"name": "B站", "fetcher": fetch_bilibili,
     "keywords": ["魔形智能", "徐凌杰", "Token超级工厂"], "delay": 2},

    # 搜狗网页搜索
    {"name": "搜狗搜索", "fetcher": fetch_sogou,
     "keywords": ["魔形智能", "徐凌杰", "Token超级工厂"], "delay": 2},
]


# ==================== 飞书推送 ====================


def build_feishu_card(title: str, link: str, source: str,
                      matched_keywords: List[str], pub_time: str, monitor_time: str) -> dict:
    """构建飞书富文本卡片消息"""
    keywords_str = "、".join([f"`{kw}`" for kw in matched_keywords])

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "🚨 舆情监控提醒"
                },
                "template": "red"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**来源平台：**【{source}】"
                    }
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**文章标题：**{title}"
                    }
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**文章链接：**[{link}]({link})"
                    }
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**命中关键词：**{keywords_str}"
                    }
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**发布时间：**{pub_time if pub_time else '未知'}"
                    }
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**监控时间：**{monitor_time}"
                    }
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "🤖 本消息由魔形智能舆情监控系统自动发送"
                        }
                    ]
                }
            ]
        }
    }

    return card


def send_feishu(card_data: dict) -> bool:
    """发送飞书卡片消息"""
    webhook_url = os.environ.get(FEISHU_WEBHOOK_ENV, "").strip()
    if not webhook_url:
        logger.error(f"环境变量 {FEISHU_WEBHOOK_ENV} 未设置，无法推送飞书消息")
        return False

    try:
        response = requests.post(
            webhook_url,
            json=card_data,
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            resp_json = response.json()
            if resp_json.get("code") == 0:
                logger.info("飞书消息推送成功")
                return True
            else:
                logger.error(f"飞书推送返回错误: code={resp_json.get('code')}, msg={resp_json.get('msg')}")
                logger.error(f"完整响应: {response.text}")
                return False
        else:
            logger.error(f"飞书推送HTTP错误: status={response.status_code}, body={response.text}")
            return False

    except Exception as e:
        logger.error(f"飞书推送请求异常: {e}")
        return False


# ==================== 历史记录管理 ====================


def load_history() -> dict:
    """加载历史记录"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"历史记录文件读取失败，将创建新文件: {e}")
            return {}
    return {}


def save_history(history: dict):
    """保存历史记录到文件"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        logger.info(f"历史记录已保存到 {HISTORY_FILE}，共 {len(history)} 条")
    except IOError as e:
        logger.error(f"历史记录保存失败: {e}")


def commit_history_to_git():
    """将 history.json 提交回 GitHub 仓库"""
    try:
        github_actor = os.environ.get("GITHUB_ACTOR", "github-actions")
        github_repository = os.environ.get("GITHUB_REPOSITORY", "")

        os.system(f'git config user.name "{github_actor}"')
        os.system(f'git config user.email "{github_actor}@users.noreply.github.com"')

        diff_check = os.popen(f"git diff --name-only {HISTORY_FILE}").read().strip()
        if not diff_check:
            status_check = os.popen(f"git status --porcelain {HISTORY_FILE}").read().strip()
            if not status_check:
                logger.info("history.json 无变更，跳过提交")
                return

        os.system(f"git add {HISTORY_FILE}")
        commit_msg = f"Update history.json - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        exit_code = os.system(f'git commit -m "{commit_msg}"')

        if exit_code != 0:
            logger.warning("Git commit 失败或无变更")
            return

        github_token = os.environ.get("GITHUB_TOKEN", "")
        if github_token and github_repository:
            remote_url = f"https://x-access-token:{github_token}@github.com/{github_repository}.git"
            os.system(f"git push {remote_url} HEAD:$(git rev-parse --abbrev-ref HEAD)")
            logger.info("history.json 已成功提交到 GitHub")
        else:
            logger.warning("GITHUB_TOKEN 或 GITHUB_REPOSITORY 未设置，跳过自动推送")

    except Exception as e:
        logger.error(f"Git 提交失败: {e}")


# ==================== 主程序 ====================


def main():
    """主入口函数"""
    logger.info("=" * 60)
    logger.info("魔形智能舆情监控启动 (混合抓取模式)")
    logger.info(f"监控关键词: {KEYWORDS}")
    logger.info(f"数据源: {len(DATA_SOURCES)} 个平台")
    logger.info("=" * 60)

    # 加载历史记录
    history = load_history()
    logger.info(f"已加载历史记录: {len(history)} 条")

    # 当前监控时间
    monitor_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 统计数据
    stats = {
        "total_checked": 0,
        "total_fetched": 0,
        "new_hits": 0,
        "push_success": 0,
        "push_fail": 0,
        "errors": 0,
    }

    # 遍历所有数据源
    for source_idx, source_config in enumerate(DATA_SOURCES, 1):
        source_name = source_config["name"]
        fetcher = source_config["fetcher"]
        keywords = source_config["keywords"]
        delay = source_config.get("delay", 2)

        logger.info(f"[{source_idx}/{len(DATA_SOURCES)}] 数据源: {source_name}")

        for keyword in keywords:
            try:
                items = fetcher(keyword)
                stats["total_fetched"] += len(items)

                if not items:
                    continue

                for item in items:
                    try:
                        title = item.get("title", "")
                        url = item.get("url", "")
                        summary = item.get("summary", "")
                        source = item.get("source", source_name)
                        pub_time = item.get("pub_time", "")

                        if not title or not url:
                            continue

                        stats["total_checked"] += 1

                        # 关键词匹配（标题或摘要）
                        matched_in_title = find_matched_keywords(title)
                        matched_in_desc = find_matched_keywords(summary)
                        all_matched = list(set(matched_in_title + matched_in_desc))

                        if not all_matched:
                            continue

                        # 去重检查
                        key = dedup_key(url, title)
                        if key in history:
                            continue

                        logger.info(f"🎯 [{source}] 命中 {all_matched}: {title[:60]}")

                        # 构建飞书卡片并推送
                        card_data = build_feishu_card(
                            title=title,
                            link=url,
                            source=source,
                            matched_keywords=all_matched,
                            pub_time=pub_time,
                            monitor_time=monitor_time,
                        )

                        if send_feishu(card_data):
                            stats["push_success"] += 1
                            history[key] = {
                                "title": title,
                                "url": url,
                                "time": monitor_time,
                                "source": source,
                                "keywords": all_matched,
                            }
                            stats["new_hits"] += 1
                        else:
                            stats["push_fail"] += 1

                        time.sleep(0.5)

                    except Exception as e:
                        logger.error(f"处理单条内容异常: {e}")
                        continue

                # 关键词之间延迟
                time.sleep(delay)

            except Exception as e:
                logger.error(f"数据源异常 [{source_name}/{keyword}]: {e}")
                stats["errors"] += 1
                continue

        # 数据源之间延迟
        time.sleep(delay)

    # 保存历史记录
    save_history(history)

    # Git提交
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        commit_history_to_git()

    # 统计报告
    logger.info("=" * 60)
    logger.info("监控运行完成")
    logger.info(f"总检查: {stats['total_checked']} | 新命中: {stats['new_hits']} | "
                f"推送成功: {stats['push_success']} | 失败: {stats['push_fail']} | 错误: {stats['errors']}")
    logger.info(f"历史记录总计: {len(history)} 条")
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("用户中断")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"程序异常退出: {e}", exc_info=True)
        sys.exit(1)
