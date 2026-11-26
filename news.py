"""지역별 테크 기사 + 국내 경제/정치 뉴스 (Google 뉴스 RSS, API 키 불필요)

- 테크: 국내 5 · 미국 5
- 경제/정치: 국내 언론 기사
"""
import datetime as dt
import email.utils
import html
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

KST = dt.timezone(dt.timedelta(hours=9))
_HEADERS = {"User-Agent": "Mozilla/5.0"}

_KR = {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}
_US = {"hl": "en-US", "gl": "US", "ceid": "US:en"}


def _topic(topic, edition):
    return ("https://news.google.com/rss/headlines/section/topic/" + topic + "?"
            + urllib.parse.urlencode(edition))


def _search(query, edition):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, **edition})


# (섹션 이름, 아이콘, 기사 수, 피드 URL)
TECH_SECTIONS = [
    ("국내", "🇰🇷", 5, _search("반도체 OR 인공지능 OR IT기업 OR 빅테크 OR 스타트업 OR 네이버 OR "
                              "카카오 OR 삼성전자 when:1d", _KR)),
    ("미국", "🇺🇸", 5, _search("Apple OR Google OR Microsoft OR Nvidia OR OpenAI OR Meta OR "
                              "Amazon OR Tesla OR startup OR chip when:1d", _US)),
]
OTHER_SECTIONS = [
    ("경제", "💰", 6, _topic("BUSINESS", _KR)),
    ("정치", "🏛️", 6, _search("정치 when:1d", _KR)),
]


def _clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value):
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(KST)


def _fetch_feed(url):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as res:
        root = ET.fromstring(res.read())
    items = []
    for it in root.iter("item"):
        title = _clean(it.findtext("title"))
        source = it.findtext("source") or ""
        if source and title.endswith(" - " + source):   # "제목 - 언론사" 형식 정리
            title = title[: -len(" - " + source)]
        if title:
            items.append({"title": title, "link": it.findtext("link"),
                          "source": source, "date": _parse_date(it.findtext("pubDate"))})
    return items


def _latest_unique(items, count, seen):
    oldest = dt.datetime.min.replace(tzinfo=KST)
    picked = []
    for it in sorted(items, key=lambda x: x["date"] or oldest, reverse=True):
        key = re.sub(r"\W", "", it["title"].lower())[:60]
        if key not in seen:
            seen.add(key)
            picked.append(it)
            if len(picked) == count:
                break
    return picked


def fetch_articles():
    errors, seen = [], set()

    def build(sections):
        out = []
        for name, icon, count, url in sections:
            try:
                items = _latest_unique(_fetch_feed(url), count, seen)
            except (urllib.error.URLError, TimeoutError, ET.ParseError) as e:
                errors.append(f"{name} 기사 불러오기 실패: {e}")
                items = []
            out.append({"name": name, "icon": icon, "articles": items})
        return out

    data = {"tech": build(TECH_SECTIONS), "other": build(OTHER_SECTIONS), "errors": errors}
    if not any(s["articles"] for s in data["tech"] + data["other"]):
        raise RuntimeError("기사를 불러오지 못했습니다. " + " / ".join(errors))
    return data
