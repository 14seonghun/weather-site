"""주식·증시 데이터 (Yahoo Finance 공개 차트 API, API 키 불필요)

- 미국 종목: AAPL, TSLA 같은 티커
- 한국 종목: 6자리 종목코드(005930) 또는 아래 별칭(삼성전자)
"""
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request

KST = dt.timezone(dt.timedelta(hours=9))

# 증시 요약에 항상 보여줄 지수
MARKET_INDICES = {
    "미국": [("^GSPC", "S&P 500"), ("^IXIC", "나스닥"), ("^DJI", "다우존스")],
    "한국": [("^KS11", "코스피"), ("^KQ11", "코스닥"), ("KRW=X", "원/달러 환율")],
}

# 처음 접속했을 때 보여줄 관심 종목
DEFAULT_WATCHLIST = "삼성전자, SK하이닉스, AAPL, NVDA, TSLA"

# 한글 이름/별칭 → Yahoo 심볼 (필요하면 여기에 추가하세요)
ALIASES = {
    "삼성전자": "005930.KS", "sk하이닉스": "000660.KS", "하이닉스": "000660.KS",
    "lg에너지솔루션": "373220.KS", "삼성바이오로직스": "207940.KS", "현대차": "005380.KS",
    "기아": "000270.KS", "셀트리온": "068270.KS", "naver": "035420.KS", "네이버": "035420.KS",
    "카카오": "035720.KS", "posco홀딩스": "005490.KS", "포스코홀딩스": "005490.KS",
    "lg화학": "051910.KS", "삼성sdi": "006400.KS", "kb금융": "105560.KS",
    "신한지주": "055550.KS", "한화에어로스페이스": "012450.KS", "현대모비스": "012330.KS",
    "에코프로": "086520.KQ", "에코프로비엠": "247540.KQ", "알테오젠": "196170.KQ",
    "애플": "AAPL", "마이크로소프트": "MSFT", "엔비디아": "NVDA", "테슬라": "TSLA",
    "아마존": "AMZN", "구글": "GOOGL", "알파벳": "GOOGL", "메타": "META",
    "넷플릭스": "NFLX", "브로드컴": "AVGO", "amd": "AMD", "팔란티어": "PLTR",
    "코스피": "^KS11", "코스닥": "^KQ11", "s&p500": "^GSPC", "나스닥": "^IXIC",
    "다우": "^DJI", "환율": "KRW=X",
}

MAX_SYMBOLS = 10
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _fetch_chart(symbol):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(symbol) + "?range=1y&interval=1d")
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            data = json.load(res)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"{symbol} 요청 실패 (HTTP {e.code})") from e
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise RuntimeError(f"{symbol} 요청 실패 ({e})") from e
    result = (data.get("chart") or {}).get("result")
    return result[0] if result else None


def resolve(query):
    """사용자 입력 → 시도해볼 Yahoo 심볼 목록"""
    q = query.strip()
    key = q.lower().replace(" ", "")
    if key in ALIASES:
        return [ALIASES[key]]
    if re.fullmatch(r"\d{6}", q):            # 한국 종목코드: 코스피 먼저, 없으면 코스닥
        return [f"{q}.KS", f"{q}.KQ"]
    return [q.upper()]


def _pct(now, before):
    return None if not before else (now - before) / before * 100


def _price_text(value, currency, symbol):
    if value is None:
        return "-"
    if currency == "KRW" and not symbol.startswith("^") and symbol != "KRW=X":
        return f"{value:,.0f}원"
    if currency == "USD":
        return f"${value:,.2f}"
    return f"{value:,.2f}"


def quote(query, display_name=None):
    """한 종목/지수를 가져와 숫자 지표와 한 줄 요약을 만든다."""
    chart, symbol = None, None
    for symbol in resolve(query):
        chart = _fetch_chart(symbol)
        if chart:
            break
    if not chart:
        return {"query": query, "error": f"'{query}' 종목을 찾을 수 없습니다."}

    meta = chart["meta"]
    times = chart.get("timestamp") or []
    closes_raw = chart["indicators"]["quote"][0].get("close") or []
    points = [(t, c) for t, c in zip(times, closes_raw) if c is not None]
    if len(points) < 2:
        return {"query": query, "error": f"'{query}' 가격 데이터가 부족합니다."}
    closes = [c for _, c in points]

    price = meta.get("regularMarketPrice") or closes[-1]
    prev = closes[-2]
    currency = meta.get("currency", "")
    name = display_name or meta.get("shortName") or meta.get("longName") or symbol
    if not display_name and query.strip().lower().replace(" ", "") in ALIASES:
        name = query.strip()  # 별칭(삼성전자 등)으로 검색했다면 그 이름으로 표시

    high52, low52 = max(closes), min(closes)
    ma20 = sum(closes[-20:]) / min(20, len(closes))
    info = {
        "query": query, "symbol": symbol, "name": name, "currency": currency,
        "exchange": meta.get("exchangeName", ""),
        "price": price, "price_text": _price_text(price, currency, symbol),
        "change": price - prev, "change_pct": _pct(price, prev),
        "ret_1m": _pct(price, closes[-22]) if len(closes) > 22 else None,
        "ret_3m": _pct(price, closes[-64]) if len(closes) > 64 else None,
        "ret_1y": _pct(price, closes[0]),
        "high52": high52, "low52": low52,
        "high52_text": _price_text(high52, currency, symbol),
        "low52_text": _price_text(low52, currency, symbol),
        "from_high": _pct(price, high52),
        "ma20": ma20,
        "updated": dt.datetime.fromtimestamp(meta.get("regularMarketTime", points[-1][0]), KST)
                     .strftime("%m/%d %H:%M"),
        "spark": closes[-66:],   # 최근 약 3개월
        "error": None,
    }
    info["summary"] = _summarize(info)
    return info


def _summarize(s):
    def updown(p):
        return "상승" if p > 0 else ("하락" if p < 0 else "보합")

    lines = [f"{s['name']}의 현재가는 {s['price_text']}이며, 전일 대비 {s['change_pct']:+.2f}% {updown(s['change_pct'])}했습니다."]
    trend = [f"{label} {v:+.1f}%" for label, v in
             (("1개월", s["ret_1m"]), ("3개월", s["ret_3m"]), ("1년", s["ret_1y"])) if v is not None]
    if trend:
        lines.append("수익률은 " + ", ".join(trend) + "입니다.")

    if s["from_high"] > -3:
        lines.append("52주 최고가 부근에서 거래되고 있습니다.")
    elif s["price"] <= s["low52"] * 1.03:
        lines.append("52주 최저가 부근에서 거래되고 있습니다.")
    else:
        lines.append(f"52주 최고가 대비 {abs(s['from_high']):.1f}% 낮은 수준입니다.")

    lines.append("20일 이동평균 " + ("위에 있어 단기 흐름이 강한 편입니다." if s["price"] >= s["ma20"]
                                 else "아래에 있어 단기 흐름이 약한 편입니다."))
    return " ".join(lines)


def market_overview():
    groups = {}
    for region, items in MARKET_INDICES.items():
        groups[region] = [quote(sym, name) for sym, name in items]

    headline = []
    for region, items in groups.items():
        ok = [i for i in items if not i["error"] and i["symbol"] != "KRW=X"]
        if ok:
            avg = sum(i["change_pct"] for i in ok) / len(ok)
            mood = "강세" if avg > 0.3 else ("약세" if avg < -0.3 else "혼조/보합")
            detail = ", ".join(f"{i['name']} {i['change_pct']:+.2f}%" for i in ok)
            headline.append(f"{region} 증시는 {mood}입니다 ({detail}).")
    return {"groups": groups, "headline": " ".join(headline)}


def parse_watchlist(text):
    items = [t.strip() for t in re.split(r"[,\n]+", text or "") if t.strip()]
    seen, unique = set(), []
    for t in items:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    return unique[:MAX_SYMBOLS]
