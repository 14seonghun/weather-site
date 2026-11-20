"""10월 기온: 예측 vs 실제 — Flask 웹사이트

로컬 실행:  python app.py   →  http://localhost:8000
배포(Render): Start Command = gunicorn app:app
"""
import calendar
import json
import threading
import time
import urllib.error
import urllib.request

from flask import Flask, render_template

# ===== 설정 (여기만 바꾸면 됩니다) =====
LOCATION = {"name": "서울", "latitude": 37.5665, "longitude": 126.978}
TRAIN_YEARS = [2023, 2024, 2025]  # 예측에 사용할 과거 연도
TARGET_YEAR = 2026                # 비교할 올해
MONTH = 10                        # 10월
SMOOTH_WINDOW = 5                 # 이동평균 일수 (홀수)
CACHE_SECONDS = 6 * 60 * 60       # 데이터를 다시 받아오는 주기 (6시간)

app = Flask(__name__)


# 1. 가져오기: Open-Meteo에서 해당 연도 10월의 일평균 기온
def fetch_month(year):
    last_day = calendar.monthrange(year, MONTH)[1]
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LOCATION['latitude']}&longitude={LOCATION['longitude']}"
        f"&start_date={year}-{MONTH:02d}-01&end_date={year}-{MONTH:02d}-{last_day:02d}"
        "&daily=temperature_2m_mean&timezone=Asia%2FSeoul"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as res:
            data = json.load(res)
    except urllib.error.URLError as e:
        raise RuntimeError(f"{year}년 데이터 요청 실패 ({e})") from e
    return data["daily"]["temperature_2m_mean"]  # index 0 = 1일


# 2. 가공하기
def mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def moving_average(arr, w):
    half = w // 2
    return [mean(arr[max(0, i - half): i + half + 1]) for i in range(len(arr))]


def predict(history):
    """과거 여러 해의 같은 날짜 평균 → 이동평균으로 부드럽게"""
    days = len(history[0])
    avg = [mean([year[d] for year in history]) for d in range(days)]
    return moving_average(avg, SMOOTH_WINDOW)


def compare(predicted, actual):
    pairs = [(p, a) for p, a in zip(predicted, actual) if p is not None and a is not None]
    if not pairs:
        raise RuntimeError(f"{TARGET_YEAR}년 {MONTH}월 실제 데이터가 아직 없습니다.")
    n = len(pairs)
    return {
        "pred_avg": sum(p for p, _ in pairs) / n,
        "actual_avg": sum(a for _, a in pairs) / n,
        "diff_avg": sum(a - p for p, a in pairs) / n,
        "mae": sum(abs(a - p) for p, a in pairs) / n,
    }


def build_result():
    history = [fetch_month(y) for y in TRAIN_YEARS]
    actual = fetch_month(TARGET_YEAR)
    predicted = predict(history)
    stats = compare(predicted, actual)

    rows = []
    for i, (p, a) in enumerate(zip(predicted, actual)):
        diff = None if p is None or a is None else a - p
        rows.append({"label": f"{MONTH}/{i + 1}", "p": p, "a": a, "diff": diff})

    return {
        "stats": stats,
        "rows": rows,
        "chart": {
            "labels": [r["label"] for r in rows],
            "predicted": predicted,
            "actual": actual,
            "actualLabel": f"{TARGET_YEAR}년 실제",
        },
    }


# 데이터 캐시: 접속할 때마다 API를 부르지 않도록 일정 시간 저장
_cache = {"time": 0, "result": None}
_lock = threading.Lock()


def get_result():
    with _lock:
        if _cache["result"] is None or time.time() - _cache["time"] > CACHE_SECONDS:
            _cache["result"] = build_result()
            _cache["time"] = time.time()
        return _cache["result"]


# 템플릿에서 쓰는 숫자 형식
@app.template_filter("num")
def num(n):
    return "-" if n is None else f"{n:.1f}"


@app.template_filter("signed")
def signed(n):
    return "-" if n is None else f"{n:+.1f}"


# 3. 보여주기
@app.route("/")
def index():
    common = {"location": LOCATION, "train_years": TRAIN_YEARS,
              "target_year": TARGET_YEAR, "month": MONTH}
    try:
        return render_template("index.html", **common, **get_result(), error=None)
    except Exception as e:  # 오류도 웹페이지로 보여줌
        return render_template("index.html", **common, error=str(e)), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
