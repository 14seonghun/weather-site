"""개인 대시보드 — 날씨(서울/평택) · 주식/증시 요약 · 10월 기온 비교

로컬 실행:  python app.py   →  http://localhost:8000
배포(Render): Start Command = gunicorn app:app
  Render 환경변수(Environment)에 꼭 설정하세요:
    pw         = 접속 비밀번호
    SECRET_KEY = (선택) 아무 긴 랜덤 문자열 (로그인 쿠키 서명용)
"""
import datetime as dt
import hashlib
import hmac
import os
import threading
import time
from functools import wraps

from flask import Flask, redirect, render_template, request, session, url_for

import stocks
import weather


def _load_dotenv(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    """로컬 실행용: .env 파일(깃에 올라가지 않음)의 KEY=VALUE 를 환경변수로 읽어옴"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# ===== 설정 =====
# 비밀번호는 코드에 적지 않고 환경변수 pw 에서 읽습니다.
#   Render: Environment 에 key=pw / value=비밀번호
#   로컬:   이 폴더의 .env 파일에  pw=비밀번호
APP_PASSWORD = os.environ.get("pw", "")
WEATHER_CACHE_SECONDS = 30 * 60      # 예보: 30분마다 갱신
STOCK_CACHE_SECONDS = 5 * 60         # 주가: 5분마다 갱신
OCTOBER_CACHE_SECONDS = 6 * 60 * 60  # 10월 비교: 6시간마다 갱신
ERROR_CACHE_SECONDS = 60             # 실패했을 때 1분간은 다시 요청하지 않음

app = Flask(__name__)
# SECRET_KEY 가 없으면 비밀번호에서 만든 값을 사용 (gunicorn 워커끼리 같은 값이 되도록)
app.secret_key = os.environ.get("SECRET_KEY") or hashlib.sha256(
    ("weather-site:" + APP_PASSWORD).encode()).hexdigest()
app.config.update(
    PERMANENT_SESSION_LIFETIME=dt.timedelta(days=7),  # 7일 동안 로그인 유지
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),  # Render(https)에서는 보안 쿠키
)


# ---------- 캐시: 접속할 때마다 외부 API를 부르지 않도록 ----------
_cache = {}
_locks = {}
_locks_guard = threading.Lock()


def cached(key, seconds, fn):
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        entry = _cache.get(key)
        if entry and time.time() < entry["expires"]:
            if entry["error"]:
                raise RuntimeError(entry["error"])
            return entry["value"]
        try:
            value = fn()
        except Exception as e:
            _cache[key] = {"value": None, "error": str(e), "expires": time.time() + ERROR_CACHE_SECONDS}
            raise
        _cache[key] = {"value": value, "error": None, "expires": time.time() + seconds}
        return value


# ---------- 로그인 ----------
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            target = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=target))
        return view(*args, **kwargs)
    return wrapper


def _safe_next(target):
    # 외부 사이트로 튕겨나가지 않도록 내부 경로만 허용
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("weather_page")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if not APP_PASSWORD:
            error = "서버에 비밀번호(pw 환경변수)가 설정되지 않았습니다."
            return render_template("login.html", error=error), 503
        if hmac.compare_digest(password.encode(), APP_PASSWORD.encode()):
            session.clear()
            session["authed"] = True
            session.permanent = True
            return redirect(_safe_next(request.args.get("next")))
        time.sleep(1)  # 비밀번호 무작위 대입을 느리게
        error = "비밀번호가 올바르지 않습니다."
    return render_template("login.html", error=error), (401 if error else 200)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- 템플릿 숫자 형식 ----------
@app.template_filter("num")
def num(n, digits=1):
    return "-" if n is None else f"{n:.{digits}f}"


@app.template_filter("signed")
def signed(n, digits=1):
    return "-" if n is None else f"{n:+.{digits}f}"


@app.template_filter("updown")
def updown(n):
    if n is None or n == 0:
        return ""
    return "up" if n > 0 else "down"


# ---------- 페이지 ----------
@app.route("/")
@login_required
def weather_page():
    try:
        cities = cached("weather", WEATHER_CACHE_SECONDS, weather.weekly_forecast)
        return render_template("weather.html", page="weather", cities=cities, error=None)
    except Exception as e:
        return render_template("weather.html", page="weather", cities=[], error=str(e)), 500


@app.route("/stocks")
@login_required
def stocks_page():
    # ?q=삼성전자, AAPL 처럼 요청. 마지막으로 조회한 목록은 기억해 둠
    if "q" in request.args:
        session["watchlist"] = request.args["q"]
    text = session.get("watchlist", stocks.DEFAULT_WATCHLIST)
    symbols = stocks.parse_watchlist(text)

    try:
        market = cached("market", STOCK_CACHE_SECONDS, stocks.market_overview)
        market_error = None
    except Exception as e:
        market, market_error = None, str(e)

    quotes = []
    for s in symbols:
        try:
            quotes.append(cached(f"quote:{s.lower()}", STOCK_CACHE_SECONDS, lambda s=s: stocks.quote(s)))
        except Exception as e:
            quotes.append({"query": s, "error": str(e)})

    return render_template("stocks.html", page="stocks", query=text, market=market,
                           market_error=market_error, quotes=quotes,
                           max_symbols=stocks.MAX_SYMBOLS)


@app.route("/october")
@login_required
def october_page():
    try:
        result = cached("october", OCTOBER_CACHE_SECONDS, weather.october_comparison)
        return render_template("october.html", page="october", error=None, **result)
    except Exception as e:
        return render_template("october.html", page="october", error=str(e),
                               month=weather.MONTH), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
