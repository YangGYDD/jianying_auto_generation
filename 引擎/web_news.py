# -*- coding: utf-8 -*-
"""对公开新闻网页做保守的通用提取。

不执行登录、验证码、人机校验或付费墙绕过。提取不到可靠正文时返回失败，
避免用不完整内容生成看似真实的新闻文案。
"""
import html
import re
import socket
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser


TRACKING_KEYS = {"spm", "from", "source", "ref", "referrer", "share_token", "shareid"}
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024
BLOCKED_MARKERS = ("验证码", "人机验证", "请完成验证", "登录后查看", "付费阅读", "访问受限")


def normalize_url(url):
    value = (url or "").strip()
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return ""
    if not host:
        return ""
    netloc = host
    if ":" in host and not host.startswith("["):
        netloc = "[" + host + "]"
    if port and not ((parsed.scheme.lower() == "http" and port == 80)
                     or (parsed.scheme.lower() == "https" and port == 443)):
        netloc += ":" + str(port)
    query_items = []
    for key, val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in TRACKING_KEYS:
            continue
        query_items.append((key, val))
    query = urllib.parse.urlencode(sorted(query_items))
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def normalize_title(title):
    text = unicodedata.normalize("NFKC", str(title or "")).lower()
    return re.sub(r"\s+", " ", text).strip()


def news_key(url, title):
    return normalize_url(url) + "\n" + normalize_title(title)


def _clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


class _NewsHTMLParser(HTMLParser):
    BLOCK_TAGS = {"p", "h1", "h2", "h3", "li"}
    SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "canvas"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.article_depth = 0
        self.title_depth = 0
        self.h1_depth = 0
        self.current = None
        self.paragraphs = []
        self.article_paragraphs = []
        self.title_parts = []
        self.h1_parts = []
        self.visible_parts = []
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "meta":
            key = (attr.get("property") or attr.get("name") or attr.get("itemprop") or "").lower()
            val = attr.get("content", "").strip()
            if key and val:
                self.meta.setdefault(key, val)
        if tag == "article":
            self.article_depth += 1
        if tag == "title":
            self.title_depth += 1
        if tag == "h1":
            self.h1_depth += 1
        if tag in self.BLOCK_TAGS and self.current is None:
            self.current = (tag, [], self.article_depth > 0)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in self.BLOCK_TAGS and self.current and self.current[0] == tag:
            _, parts, in_article = self.current
            text = _clean_text("".join(parts))
            if text:
                (self.article_paragraphs if in_article else self.paragraphs).append(text)
            self.current = None
        if tag == "article":
            self.article_depth = max(0, self.article_depth - 1)
        if tag == "title":
            self.title_depth = max(0, self.title_depth - 1)
        if tag == "h1":
            self.h1_depth = max(0, self.h1_depth - 1)

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = data.strip()
        if not text:
            return
        self.visible_parts.append(text)
        if self.current:
            self.current[1].append(data)
        if self.title_depth:
            self.title_parts.append(data)
        if self.h1_depth:
            self.h1_parts.append(data)


def _is_private_host(hostname):
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for item in addresses:
        address = item[4][0]
        try:
            import ipaddress
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
        except ValueError:
            continue
    return False


def fetch_news(url, timeout=30, max_chars=8000):
    normalized = normalize_url(url)
    if not normalized:
        raise ValueError("链接不是有效的 http/https 地址")
    parsed = urllib.parse.urlsplit(normalized)
    if _is_private_host(parsed.hostname or ""):
        raise ValueError("链接指向内网或本机地址, 已跳过")
    request = urllib.request.Request(
        normalized,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NewsDraftBot/1.0",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if content_type and "html" not in content_type and "xhtml" not in content_type:
                raise ValueError("链接不是网页 HTML 内容")
            raw = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(raw) > MAX_DOWNLOAD_BYTES:
                raw = raw[:MAX_DOWNLOAD_BYTES]
            charset = response.headers.get_content_charset() or "utf-8"
            if charset == "utf-8":
                head = raw[:4096].decode("ascii", errors="ignore")
                match = re.search(r"charset\s*=\s*[\"']?([\w-]+)", head, flags=re.I)
                if match:
                    charset = match.group(1)
            final_url = normalize_url(response.geturl()) or normalized
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 407, 429):
            raise ValueError(f"网站拒绝访问(HTTP {exc.code})") from None
        raise ValueError(f"网页抓取失败(HTTP {exc.code})") from None
    except urllib.error.URLError as exc:
        raise ValueError("网页连接失败: " + str(exc.reason or "网络错误")) from None
    except TimeoutError:
        raise ValueError("网页抓取超时") from None
    try:
        text = raw.decode(charset, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    parser = _NewsHTMLParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise ValueError("网页结构无法解析: " + str(exc)) from None

    title = (_clean_text(parser.meta.get("og:title"))
             or _clean_text(parser.meta.get("twitter:title"))
             or _clean_text("".join(parser.title_parts))
             or _clean_text("".join(parser.h1_parts)))
    description = (_clean_text(parser.meta.get("description"))
                   or _clean_text(parser.meta.get("og:description")))
    paragraphs = parser.article_paragraphs or parser.paragraphs
    body = "\n".join(p for p in paragraphs if len(p) >= 8)
    if len(body) < 80:
        fallback = _clean_text(" ".join(parser.visible_parts))
        if len(fallback) > len(body):
            body = fallback
    if len(body) < 40 and len(description) >= 40:
        body = description
    if not title:
        raise ValueError("网页没有提取到标题")
    if len(body) < 40:
        raise ValueError("网页没有提取到足够正文")
    lower_body = body.lower()
    marker_hits = sum(1 for marker in BLOCKED_MARKERS if marker.lower() in lower_body)
    if marker_hits and len(body) < 180:
        raise ValueError("网页疑似需要登录、验证码或付费权限")
    date = (parser.meta.get("article:published_time")
            or parser.meta.get("pubdate")
            or parser.meta.get("date") or "")
    if not date:
        match = re.search(r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)", body[:1500])
        date = match.group(1) if match else ""
    source = urllib.parse.urlsplit(final_url).hostname or ""
    return {
        "title": title,
        "summary": body[:max(1000, int(max_chars))],
        "source": source,
        "date": date[:30],
        "link": final_url,
    }
