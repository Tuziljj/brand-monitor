#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
品牌舆情监控脚本 - 魔形智能
监控关键词：魔形智能、徐凌杰、金琛、Token超级工厂
数据来源：36氪、虎嗅、微博、B站、百度新闻等RSS源
推送方式：飞书机器人富文本卡片
"""

import os
import re
import sys
import json
import time
import logging
from datetime import datetime
from urllib.parse import urlparse
from typing import Optional

import requests
import feedparser

# ==================== 配置区域 ====================

# 监控关键词
KEYWORDS = ["魔形智能", "徐凌杰", "金琛", "Token超级工厂"]

# RSS源列表（硬编码，方便后续手动添加/删除）
RSS_SOURCES = [
    # 新闻/资讯类 - 魔形智能
    "https://rsshub.app/36kr/search/article/%E9%AD%94%E5%BD%A2%E6%99%BA%E8%83%BD",
    "https://rsshub.app/huxiu/search/%E9%AD%94%E5%BD%A2%E6%99%BA%E8%83%BD",
    "https://rsshub.app/sspai/search/%E9%AD%94%E5%BD%A2%E6%99%BA%E8%83%BD",
    "https://rsshub.app/jiemian/search/%E9%AD%94%E5%BD%A2%E6%99%BA%E8%83%BD",
    "https://rsshub.app/baidu/news/%E9%AD%94%E5%BD%A2%E6%99%BA%E8%83%BD",
    "https://rsshub.app/ithome/search/%E9%AD%94%E5%BD%A2%E6%99%BA%E8%83%BD",
    "https://rsshub.app/thepaper/search/%E9%AD%94%E5%BD%A2%E6%99%BA%E8%83%BD",
    # 社交媒体类
    "https://rsshub.app/weibo/keyword/%E9%AD%94%E5%BD%A2%E6%99%BA%E8%83%BD",
    "https://rsshub.app/weibo/keyword/Token%E8%B6%85%E7%BA%A7%E5%B7%A5%E5%8E%82",
    "https://rsshub.app/bilibili/vsearch/%E9%AD%94%E5%BD%A2%E6%99%BA%E8%83%BD",
    # 高管个人舆情 - 徐凌杰
    "https://rsshub.app/36kr/search/article/%E5%BE%90%E5%87%8C%E6%9D%B0",
    "https://rsshub.app/weibo/keyword/%E5%BE%90%E5%87%8C%E6%9D%B0",
    "https://rsshub.app/baidu/news/%E5%BE%90%E5%87%8C%E6%9D%B0",
]

# RSSHub 备用实例列表（主实例失败时依次尝试）
MIRROR_SITES = [
    "https://rsshub.rssforever.com",
    "https://rsshub.pseudoyu.com",
    "https://rsshub.fly.dev",
]

# 请求超时时间（秒）
REQUEST_TIMEOUT = 15

# 历史记录文件路径
HISTORY_FILE = "history.json"

# 飞书 Webhook 环境变量名
FEISHU_WEBHOOK_ENV = "FEISHU_WEBHOOK"

# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ==================== 工具函数 ====================


def get_mirror_url(original_url: str, mirror_base: str) -> str:
    """将原始URL的域名替换为备用实例域名"""
    parsed = urlparse(original_url)
    mirror_parsed = urlparse(mirror_base)
    # 替换协议和域名，保留路径和查询参数
    new_url = original_url.replace(
        f"{parsed.scheme}://{parsed.netloc}",
        f"{mirror_parsed.scheme}://{mirror_parsed.netloc}"
    )
    return new_url


def extract_source_name(url: str) -> str:
    """从RSS URL自动识别来源平台名称"""
    url_lower = url.lower()

    # 按优先级匹配
    source_map = {
        "36kr": "36氪",
        "huxiu": "虎嗅",
        "sspai": "少数派",
        "jiemian": "界面新闻",
        "baidu": "百度新闻",
        "ithome": "IT之家",
        "thepaper": "澎湃新闻",
        "weibo": "微博",
        "bilibili": "B站",
    }

    for key, name in source_map.items():
        if key in url_lower:
            return name

    # 兜底：返回域名
    parsed = urlparse(url)
    return parsed.netloc


def format_time(dt: Optional[datetime]) -> str:
    """格式化时间为可读字符串"""
    if dt is None:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_pub_date(entry) -> Optional[datetime]:
    """从RSS条目中解析发布时间"""
    # 尝试多个可能的字段
    for field in ["published_parsed", "updated_parsed", "created_parsed"]:
        parsed_time = getattr(entry, field, None)
        if parsed_time:
            try:
                return datetime(*parsed_time[:6])
            except (TypeError, ValueError):
                continue

    # 尝试解析字符串格式
    for field in ["published", "updated", "created", "pubDate"]:
        date_str = getattr(entry, field, None)
        if date_str:
            # 尝试多种格式
            formats = [
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue

    return None


def find_matched_keywords(text: str) -> list:
    """检查文本中命中了哪些关键词，返回命中的关键词列表"""
    if not text:
        return []
    text_lower = text.lower()
    matched = []
    for keyword in KEYWORDS:
        if keyword.lower() in text_lower:
            matched.append(keyword)
    return matched


# ==================== RSS 抓取 ====================


def fetch_rss_with_fallback(url: str) -> Optional[dict]:
    """
    抓取RSS源，支持备用实例自动切换
    先尝试主地址，失败则依次尝试备用实例
    """
    urls_to_try = [url]

    # 生成备用URL
    for mirror in MIRROR_SITES:
        urls_to_try.append(get_mirror_url(url, mirror))

    last_error = None

    for try_url in urls_to_try:
        try:
            logger.info(f"正在抓取: {try_url}")
            feed = feedparser.parse(try_url, request_headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/rss+xml, application/xml, text/xml",
            })

            # 检查是否有解析错误
            if hasattr(feed, 'bozo') and feed.bozo:
                if feed.entries:
                    # 有解析警告但有内容，继续处理
                    logger.warning(f"RSS解析警告（但有内容）: {try_url} - {feed.bozo_exception}")
                else:
                    raise Exception(f"RSS解析失败: {feed.bozo_exception}")

            if not feed.entries:
                logger.warning(f"RSS源无内容: {try_url}")
                return None

            logger.info(f"成功获取 {len(feed.entries)} 条: {try_url}")
            return {
                "url": try_url,
                "entries": feed.entries,
                "source_name": extract_source_name(try_url),
            }

        except Exception as e:
            last_error = e
            logger.warning(f"抓取失败，尝试下一个: {try_url} - {e}")
            continue

    # 所有实例都失败
    logger.error(f"所有实例均失败: {url} - 最后错误: {last_error}")
    return None


# ==================== 飞书推送 ====================


def build_feishu_card(title: str, link: str, source: str,
                      matched_keywords: list, pub_time: str, monitor_time: str) -> dict:
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
                        "content": f"**发布时间：**{pub_time}"
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
        # 配置 git（GitHub Actions 环境需要）
        github_actor = os.environ.get("GITHUB_ACTOR", "github-actions")
        github_repository = os.environ.get("GITHUB_REPOSITORY", "")

        os.system(f'git config user.name "{github_actor}"')
        os.system(f'git config user.email "{github_actor}@users.noreply.github.com"')

        # 检查文件是否有变更
        diff_check = os.popen(f"git diff --name-only {HISTORY_FILE}").read().strip()
        if not diff_check:
            # 也检查新文件
            status_check = os.popen(f"git status --porcelain {HISTORY_FILE}").read().strip()
            if not status_check:
                logger.info("history.json 无变更，跳过提交")
                return

        # 添加并提交
        os.system(f"git add {HISTORY_FILE}")
        commit_msg = f"Update history.json - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        exit_code = os.system(f'git commit -m "{commit_msg}"')

        if exit_code != 0:
            logger.warning("Git commit 失败或无变更")
            return

        # 推送（使用 GITHUB_TOKEN 认证）
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
    logger.info("=" * 50)
    logger.info("魔形智能舆情监控启动")
    logger.info(f"监控关键词: {KEYWORDS}")
    logger.info(f"RSS源数量: {len(RSS_SOURCES)}")
    logger.info("=" * 50)

    # 加载历史记录
    history = load_history()
    logger.info(f"已加载历史记录: {len(history)} 条")

    # 当前监控时间
    monitor_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 本次新命中条数
    new_hits_count = 0
    push_success_count = 0
    push_fail_count = 0

    # 遍历所有RSS源
    for idx, rss_url in enumerate(RSS_SOURCES, 1):
        logger.info(f"[{idx}/{len(RSS_SOURCES)}] 处理RSS源: {rss_url}")

        try:
            result = fetch_rss_with_fallback(rss_url)
            if result is None:
                continue

            entries = result["entries"]
            source_name = result["source_name"]

            for entry in entries:
                try:
                    # 获取标题和摘要
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    description = entry.get("description", "") or entry.get("summary", "")

                    if not title or not link:
                        continue

                    # 关键词匹配（标题或摘要）
                    matched_in_title = find_matched_keywords(title)
                    matched_in_desc = find_matched_keywords(description)
                    all_matched = list(set(matched_in_title + matched_in_desc))

                    if not all_matched:
                        continue

                    # 去重检查
                    if link in history:
                        logger.debug(f"已推送过，跳过: {link}")
                        continue

                    # 解析发布时间
                    pub_dt = parse_pub_date(entry)
                    pub_time = format_time(pub_dt)

                    logger.info(f"🎯 命中关键词 {all_matched}: {title}")

                    # 构建飞书卡片并推送
                    card_data = build_feishu_card(
                        title=title,
                        link=link,
                        source=source_name,
                        matched_keywords=all_matched,
                        pub_time=pub_time,
                        monitor_time=monitor_time,
                    )

                    if send_feishu(card_data):
                        push_success_count += 1
                        # 记录到历史
                        history[link] = {
                            "title": title,
                            "time": monitor_time,
                            "source": source_name,
                            "keywords": all_matched,
                        }
                        new_hits_count += 1
                    else:
                        push_fail_count += 1

                    # 避免推送过快，短暂休眠
                    time.sleep(0.5)

                except Exception as e:
                    logger.error(f"处理单条RSS条目异常: {e}")
                    continue

        except Exception as e:
            logger.error(f"处理RSS源异常: {rss_url} - {e}")
            continue

    # 保存历史记录
    save_history(history)

    # Git提交（GitHub Actions环境）
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        commit_history_to_git()

    # 统计报告
    logger.info("=" * 50)
    logger.info("监控运行完成")
    logger.info(f"本次新命中: {new_hits_count} 条")
    logger.info(f"推送成功: {push_success_count} 条")
    logger.info(f"推送失败: {push_fail_count} 条")
    logger.info(f"历史记录总计: {len(history)} 条")
    logger.info("=" * 50)

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
