"""날씨 데이터 (Open-Meteo, 무료·API 키 불필요)

- weekly_forecast(): 서울/평택 일주일 예보
- october_comparison(): (기존 기능) 10월 기온 예측 vs 실제
"""
import calendar
import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request

# ===== 설정 =====
LOCATIONS = [
    {"name": "서울", "latitude": 37.5665, "longitude": 126.9780},
    {"name": "평택", "latitude": 36.9921, "longitude": 127.1129},
]
TIMEZONE = "Asia/Seoul"

# 10월 비교 설정 (기존 기능)
OCT_LOCATION = LOCATIONS[0]
TRAIN_YEARS = [2023, 2024, 2025]
TARGET_YEAR = 2026
MONTH = 10
SMOOTH_WINDOW = 5

WEEKDAYS = "월화수목금토일"

# WMO 날씨 코드 → (설명, 아이콘)
WEATHER_CODES = {
    0: ("맑음", "☀️"), 1: ("대체로 맑음", "🌤️"), 2: ("구름 조금", "⛅"), 3: ("흐림", "☁️"),
    45: ("안개", "🌫️"), 48: ("짙은 안개", "🌫️"),
    51: ("약한 이슬비", "🌦️"), 53: ("이슬비", "🌦️"), 55: ("강한 이슬비", "🌧️"),
    56: ("어는 이슬비", "🌧️"), 57: ("어는 이슬비", "🌧️"),
    61: ("약한 비", "🌦️"), 63: ("비", "🌧️"), 65: ("강한 비", "🌧️"),
    66: ("어는 비", "🌧️"), 67: ("강한 어는 비", "🌧️"),
    71: ("약한 눈", "🌨️"), 73: ("눈", "🌨️"), 75: ("많은 눈", "❄️"), 77: ("싸락눈", "🌨️"),
    80: ("약한 소나기", "🌦️"), 81: ("소나기", "🌧️"), 82: ("강한 소나기", "⛈️"),
    85: ("약한 소낙눈", "🌨️"), 86: ("강한 소낙눈", "❄️"),
    95: ("뇌우", "⛈️"), 96: ("우박 동반 뇌우", "⛈️"), 99: ("강한 우박 뇌우", "⛈️"),
}


def _get_json(url, what):
    try:
        with urllib.request.urlopen(url, timeout=20) as res:
            return json.load(res)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise RuntimeError(f"{what} 요청 실패 ({e})") from e


def describe(code):
    return WEATHER_CODES.get(code, ("알 수 없음", "❔"))


# ---------- 1. 일주일 예보 ----------
def _forecast_one(loc):
    params = {
        "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": TIMEZONE,
        "forecast_days": 7,
        "current": "temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,precipitation_sum",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    data = _get_json(url, f"{loc['name']} 예보")
    if "daily" not in data:
        raise RuntimeError(f"{loc['name']} 예보 응답 형식이 예상과 다릅니다: {data.get('reason', data)}")

    d = data["daily"]
    days = []
    for i, date_str in enumerate(d["time"]):
        date = dt.date.fromisoformat(date_str)
        text, icon = describe(d["weather_code"][i])
        days.append({
            "date": date,
            "label": f"{date.month}/{date.day}({WEEKDAYS[date.weekday()]})",
            "is_today": i == 0,
            "text": text, "icon": icon,
            "tmax": d["temperature_2m_max"][i], "tmin": d["temperature_2m_min"][i],
            "pop": d["precipitation_probability_max"][i],   # 강수확률 %
            "rain": d["precipitation_sum"][i],              # 강수량 mm
        })

    cur = data.get("current", {})
    cur_text, cur_icon = describe(cur.get("weather_code"))
    return {
        "name": loc["name"],
        "current": {
            "temp": cur.get("temperature_2m"), "humidity": cur.get("relative_humidity_2m"),
            "wind": cur.get("wind_speed_10m"), "text": cur_text, "icon": cur_icon,
        },
        "days": days,
        "summary": _summarize_week(loc["name"], days),
    }


def _summarize_week(name, days):
    highs = [x["tmax"] for x in days if x["tmax"] is not None]
    lows = [x["tmin"] for x in days if x["tmin"] is not None]
    rainy = [x["label"] for x in days if (x["pop"] or 0) >= 60 or (x["rain"] or 0) >= 1]
    parts = []
    if highs and lows:
        parts.append(f"이번 주 {name}의 기온은 최저 {min(lows):.0f}°C ~ 최고 {max(highs):.0f}°C입니다.")
    parts.append(f"비·눈 소식: {', '.join(rainy)}." if rainy else "뚜렷한 비·눈 소식은 없습니다.")
    if lows and min(lows) <= 0:
        parts.append("영하로 내려가는 날이 있으니 보온에 신경 쓰세요.")
    return " ".join(parts)


def weekly_forecast():
    return [_forecast_one(loc) for loc in LOCATIONS]


# ---------- 2. 10월 기온: 예측 vs 실제 (기존 기능) ----------
def _fetch_month(year):
    last_day = calendar.monthrange(year, MONTH)[1]
    params = {
        "latitude": OCT_LOCATION["latitude"], "longitude": OCT_LOCATION["longitude"],
        "start_date": f"{year}-{MONTH:02d}-01", "end_date": f"{year}-{MONTH:02d}-{last_day:02d}",
        "daily": "temperature_2m_mean", "timezone": TIMEZONE,
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
    data = _get_json(url, f"{year}년 데이터")
    if "daily" not in data:
        raise RuntimeError(f"{year}년 응답 형식이 예상과 다릅니다: {data.get('reason', data)}")
    return data["daily"]["temperature_2m_mean"]


def _mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _moving_average(arr, w):
    half = w // 2
    return [_mean(arr[max(0, i - half): i + half + 1]) for i in range(len(arr))]


def october_comparison():
    history = [_fetch_month(y) for y in TRAIN_YEARS]
    actual = _fetch_month(TARGET_YEAR)
    days = min(len(h) for h in history)
    avg = [_mean([year[d] for year in history]) for d in range(days)]
    predicted = _moving_average(avg, SMOOTH_WINDOW)

    pairs = [(p, a) for p, a in zip(predicted, actual) if p is not None and a is not None]
    if not pairs:
        raise RuntimeError(f"{TARGET_YEAR}년 {MONTH}월 실제 데이터가 아직 없습니다.")
    n = len(pairs)
    stats = {
        "pred_avg": sum(p for p, _ in pairs) / n,
        "actual_avg": sum(a for _, a in pairs) / n,
        "diff_avg": sum(a - p for p, a in pairs) / n,
        "mae": sum(abs(a - p) for p, a in pairs) / n,
    }
    rows = [{"label": f"{MONTH}/{i + 1}", "p": p, "a": a,
             "diff": None if p is None or a is None else a - p}
            for i, (p, a) in enumerate(zip(predicted, actual))]
    return {
        "location": OCT_LOCATION, "train_years": TRAIN_YEARS,
        "target_year": TARGET_YEAR, "month": MONTH,
        "stats": stats, "rows": rows,
        "chart": {"labels": [r["label"] for r in rows], "predicted": predicted,
                  "actual": actual, "actualLabel": f"{TARGET_YEAR}년 실제"},
    }
