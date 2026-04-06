#!/usr/bin/env python3
"""Daily Stock Market Report Generator — Pro Edition
yfinance + Finnhub + CNN Fear&Greed + Gemini AI + Gmail SMTP"""

import os
import json
import re
import smtplib
import feedparser
import yfinance as yf
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from google import genai

# --- Configuration ---
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = re.sub(r"[^\x20-\x7E]", " ", os.environ["GMAIL_APP_PASSWORD"]).strip()
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
RECIPIENT_EMAILS = ["alsltar94@gmail.com", "k30027@gmail.com"]

KST = timezone(timedelta(hours=9))

# =====================================================
# DATA SOURCES
# =====================================================

# --- 1. US Major Indices ---
US_INDICES = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "Dow Jones": "^DJI",
    "Russell 2000": "^RUT",
    "VIX (공포지수)": "^VIX",
}

# --- 2. US Futures (Pre-market direction) ---
US_FUTURES = {
    "S&P 500 Futures": "ES=F",
    "Nasdaq 100 Futures": "NQ=F",
    "Dow Futures": "YM=F",
}

# --- 3. Sector ETFs (Sector Rotation) ---
SECTOR_ETFS = {
    "XLK (Tech)": "XLK",
    "XLF (Financials)": "XLF",
    "XLE (Energy)": "XLE",
    "XLV (Healthcare)": "XLV",
    "XLI (Industrials)": "XLI",
    "XLY (Consumer Disc.)": "XLY",
    "XLP (Consumer Staples)": "XLP",
    "XLU (Utilities)": "XLU",
    "XLRE (Real Estate)": "XLRE",
    "XLB (Materials)": "XLB",
    "XLC (Communication)": "XLC",
}

# --- 4. Bond Yields & Spread ---
BOND_TICKERS = {
    "US 10Y Treasury": "^TNX",
    "US 2Y Treasury": "^IRX",
    "US 30Y Treasury": "^TYX",
}

# --- 5. FX ---
FX_TICKERS = {
    "USD/KRW": "KRW=X",
    "USD/JPY": "JPY=X",
    "EUR/USD": "EURUSD=X",
    "DXY (달러인덱스)": "DX-Y.NYB",
}

# --- 6. Commodities ---
COMMODITY_TICKERS = {
    "Gold": "GC=F",
    "WTI Oil": "CL=F",
    "Silver": "SI=F",
    "Copper": "HG=F",
    "Natural Gas": "NG=F",
}

# --- 7. Crypto ---
CRYPTO_TICKERS = {
    "Bitcoin": "BTC-USD",
    "Ethereum": "ETH-USD",
}

# --- 8. Watchlist (Key Stocks) ---
WATCHLIST = {
    "Mag 7": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
    "Semicon": ["TSM", "AVGO", "AMD", "INTC", "QCOM", "ASML", "MU"],
    "Finance": ["JPM", "GS", "BAC", "V", "MA"],
    "KR Major": ["005930.KS", "000660.KS", "373220.KS", "035420.KS", "035720.KS"],
}

KR_STOCK_NAMES = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "373220.KS": "LG에너지솔루션",
    "035420.KS": "NAVER",
    "035720.KS": "카카오",
}

# --- 9. News RSS (upgraded) ---
MARKET_NEWS_FEEDS = [
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
    "https://feeds.benzinga.com/benzinga",
    "https://seekingalpha.com/market_currents.xml",
]


# =====================================================
# DATA FETCHERS
# =====================================================

def fetch_market_data(tickers: dict[str, str]) -> list[dict]:
    """Fetch current price, change, change% for given tickers via yfinance."""
    results = []
    for name, symbol in tickers.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if len(hist) < 2:
                continue
            current = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2]
            change = current - prev
            change_pct = (change / prev) * 100
            results.append({
                "name": name,
                "symbol": symbol,
                "price": round(current, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
            })
        except Exception as e:
            print(f"  Warning: could not fetch {name} ({symbol}): {e}")
    return results


def fetch_watchlist_data() -> dict[str, list[dict]]:
    """Fetch watchlist stocks data grouped by category."""
    watchlist_data = {}
    for category, symbols in WATCHLIST.items():
        stocks = []
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d")
                if len(hist) < 2:
                    continue
                current = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-2]
                change = current - prev
                change_pct = (change / prev) * 100
                info = ticker.info
                display_name = KR_STOCK_NAMES.get(symbol, info.get("shortName", symbol))
                stocks.append({
                    "name": display_name,
                    "symbol": symbol,
                    "price": round(current, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": hist["Volume"].iloc[-1],
                    "market_cap": info.get("marketCap", 0),
                })
            except Exception as e:
                print(f"  Warning: could not fetch {symbol}: {e}")
        watchlist_data[category] = stocks
    return watchlist_data


def fetch_fear_greed_index() -> dict:
    """Fetch CNN Fear & Greed Index."""
    urls = [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2025-01-01",
    ]
    for url in urls:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"  Fear & Greed: HTTP {resp.status_code} from {url}")
                continue
            data = resp.json()
            fgi = data.get("fear_and_greed", {})
            if not fgi:
                continue
            return {
                "score": round(fgi.get("score", 0)),
                "rating": fgi.get("rating", "N/A"),
                "previous_close": round(fgi.get("previous_close", 0)),
                "previous_1_week": round(fgi.get("previous_1_week", 0)),
                "previous_1_month": round(fgi.get("previous_1_month", 0)),
                "previous_1_year": round(fgi.get("previous_1_year", 0)),
            }
        except Exception as e:
            print(f"  Fear & Greed warning ({url}): {e}")
    print("  Warning: all Fear & Greed sources failed")
    return {}


def fetch_yield_curve(bond_data: list[dict]) -> dict:
    """Calculate yield curve spread from bond data."""
    ten_y = next((b for b in bond_data if "10Y" in b["name"]), None)
    two_y = next((b for b in bond_data if "2Y" in b["name"]), None)
    if ten_y and two_y:
        spread = round(ten_y["price"] - two_y["price"], 2)
        return {
            "ten_y": ten_y["price"],
            "two_y": two_y["price"],
            "spread": spread,
            "inverted": spread < 0,
        }
    return {}


def fetch_economic_calendar() -> list[dict]:
    """Fetch upcoming economic events from Finnhub."""
    if not FINNHUB_API_KEY:
        print("  Warning: FINNHUB_API_KEY not set, skipping economic calendar")
        return []
    try:
        now = datetime.now(KST)
        from_date = now.strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/calendar/economic?from={from_date}&to={to_date}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        events = data.get("economicCalendar", [])
        # Filter for US events (impact >= 1 to catch more events)
        important = [
            e for e in events
            if e.get("country", "") == "US"
            and e.get("impact", 0) >= 1
        ]
        # Sort by impact descending
        important.sort(key=lambda x: x.get("impact", 0), reverse=True)
        return [
            {
                "event": e.get("event", ""),
                "date": e.get("time", ""),
                "impact": e.get("impact", 0),
                "actual": e.get("actual"),
                "estimate": e.get("estimate"),
                "prev": e.get("prev"),
                "unit": e.get("unit", ""),
            }
            for e in important[:15]
        ]
    except Exception as e:
        print(f"  Warning: could not fetch economic calendar: {e}")
        return []


def fetch_earnings_calendar() -> list[dict]:
    """Fetch upcoming earnings from Finnhub."""
    if not FINNHUB_API_KEY:
        print("  Warning: FINNHUB_API_KEY not set, skipping earnings calendar")
        return []
    try:
        now = datetime.now(KST)
        from_date = now.strftime("%Y-%m-%d")
        to_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_date}&to={to_date}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        earnings = data.get("earningsCalendar", [])
        # Filter for major companies (those in our watchlist or large cap)
        watchlist_symbols = set()
        for symbols in WATCHLIST.values():
            watchlist_symbols.update(symbols)
        major = [
            e for e in earnings
            if e.get("symbol", "") in watchlist_symbols
        ]
        # Also add top earnings by revenue estimate
        other = sorted(
            [e for e in earnings if e.get("symbol", "") not in watchlist_symbols],
            key=lambda x: x.get("revenueEstimate") or 0,
            reverse=True,
        )[:10]
        all_earnings = major + other
        return [
            {
                "symbol": e.get("symbol", ""),
                "date": e.get("date", ""),
                "hour": e.get("hour", ""),
                "eps_estimate": e.get("epsEstimate"),
                "eps_actual": e.get("epsActual"),
                "revenue_estimate": e.get("revenueEstimate"),
                "revenue_actual": e.get("revenueActual"),
            }
            for e in all_earnings[:15]
        ]
    except Exception as e:
        print(f"  Warning: could not fetch earnings calendar: {e}")
        return []


def fetch_market_news(count: int = 20) -> list[dict]:
    """Fetch recent market news from RSS feeds."""
    articles = []
    for feed_url in MARKET_NEWS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                raw_summary = entry.get("summary", entry.get("description", "")).strip()
                summary = re.sub(r"<[^>]+>", " ", raw_summary)
                summary = re.sub(r"\s+", " ", summary).strip()[:500]
                source = feed.feed.get("title", feed_url)
                if title:
                    articles.append({"title": title, "summary": summary, "source": source})
        except Exception as e:
            print(f"  Warning: could not fetch {feed_url}: {e}")
    # Deduplicate by title similarity
    seen_titles = set()
    unique = []
    for a in articles:
        short = a["title"][:50].lower()
        if short not in seen_titles:
            seen_titles.add(short)
            unique.append(a)
    return unique[:count]


# =====================================================
# AI ANALYSIS (Gemini)
# =====================================================

def generate_ai_analysis(
    us_indices: list[dict],
    us_futures: list[dict],
    sector_etfs: list[dict],
    bond_data: list[dict],
    yield_curve: dict,
    fx_data: list[dict],
    commodity_data: list[dict],
    crypto_data: list[dict],
    watchlist: dict[str, list[dict]],
    fear_greed: dict,
    economic_cal: list[dict],
    earnings_cal: list[dict],
    news: list[dict],
) -> dict:
    """Use Gemini to generate comprehensive market analysis."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    def fmt(data_list):
        return "\n".join(
            f"  - {d['name']}: {d['price']:,} ({'+' if d['change'] >= 0 else ''}{d['change']}, {'+' if d['change_pct'] >= 0 else ''}{d['change_pct']}%)"
            for d in data_list
        )

    watchlist_text = ""
    for cat, stocks in watchlist.items():
        watchlist_text += f"\n[{cat}]\n" + fmt(stocks)

    news_text = "\n".join(
        f"  [{i+1}] {a['source']}: {a['title']}"
        for i, a in enumerate(news[:12])
    )

    # Fear & Greed
    fg_text = "데이터 없음"
    if fear_greed:
        fg_text = (
            f"현재: {fear_greed.get('score', 'N/A')} ({fear_greed.get('rating', 'N/A')})\n"
            f"  전일: {fear_greed.get('previous_close', 'N/A')}, "
            f"1주전: {fear_greed.get('previous_1_week', 'N/A')}, "
            f"1개월전: {fear_greed.get('previous_1_month', 'N/A')}, "
            f"1년전: {fear_greed.get('previous_1_year', 'N/A')}"
        )

    # Yield Curve
    yc_text = "데이터 없음"
    if yield_curve:
        yc_text = (
            f"10Y: {yield_curve['ten_y']}%, 2Y: {yield_curve['two_y']}%, "
            f"스프레드: {yield_curve['spread']}bp "
            f"({'⚠️ 역전(경기침체 시그널)' if yield_curve['inverted'] else '정상'})"
        )

    # Economic Calendar
    econ_text = "데이터 없음"
    if economic_cal:
        econ_text = "\n".join(
            f"  - [{e['date']}] {e['event']} (예상: {e['estimate']}, 이전: {e['prev']})"
            for e in economic_cal
        )

    # Earnings Calendar
    earn_text = "데이터 없음"
    if earnings_cal:
        earn_text = "\n".join(
            f"  - [{e['date']} {e['hour']}] {e['symbol']} (EPS 예상: {e['eps_estimate']})"
            for e in earnings_cal
        )

    prompt = f"""당신은 골드만삭스 출신 시니어 글로벌 매크로 전략가입니다.
아래 실시간 데이터를 바탕으로 한국 개인 투자자를 위한 프로급 모닝 브리핑을 작성하세요.

=== 미국 주요 지수 (전일 종가) ===
{fmt(us_indices)}

=== 미국 선물 (프리마켓) ===
{fmt(us_futures)}

=== 섹터 ETF 등락 ===
{fmt(sector_etfs)}

=== 채권 금리 & 수익률 곡선 ===
{fmt(bond_data)}
수익률 곡선: {yc_text}

=== CNN Fear & Greed Index ===
{fg_text}

=== 환율 ===
{fmt(fx_data)}

=== 원자재 ===
{fmt(commodity_data)}

=== 암호화폐 ===
{fmt(crypto_data)}

=== 주요 종목 ===
{watchlist_text}

=== 이번 주 경제 지표 일정 ===
{econ_text}

=== 이번 주 실적 발표 일정 ===
{earn_text}

=== 시장 뉴스 ===
{news_text}

Return ONLY valid JSON — no markdown fences, no extra text:
{{
  "market_summary": {{
    "title": "한줄 헤드라인 (예: '나스닥 2% 급등, AI 랠리 2주 연속')",
    "overview": "전체 시장 흐름 4-5문장. 지수 움직임, 매크로 테마, 자금 흐름 포함.",
    "sentiment": "Bullish / Bearish / Neutral",
    "sentiment_score": 1~10,
    "sentiment_reason": "판단 근거 2-3문장. Fear&Greed, VIX, 선물 방향 등 종합."
  }},
  "overnight_recap": {{
    "us_session": "미국장 마감 요약 3-4문장. 주요 이벤트, 섹터 움직임.",
    "futures_direction": "선물 방향 요약 1-2문장. 오늘 장 방향 시사점.",
    "global_cues": "글로벌 시장 영향 요인 1-2문장. 유럽/아시아 시장, 지정학적 이슈."
  }},
  "key_highlights": [
    {{
      "emoji": "이모지",
      "title": "핵심 포인트",
      "description": "2-3문장. 구체적 수치 포함.",
      "impact": "투자자 영향 1문장",
      "action": "대응 방향 1문장"
    }}
  ],
  "sector_rotation": {{
    "leaders": "상승 주도 섹터와 이유 2문장",
    "laggards": "하락 섹터와 이유 2문장",
    "rotation_signal": "자금 흐름/로테이션 시그널 1-2문장",
    "sectors": [
      {{
        "name": "섹터명",
        "trend": "강세 / 약세 / 보합",
        "analysis": "1-2문장 분석",
        "key_stocks": "주요 종목과 등락률"
      }}
    ]
  }},
  "macro_pulse": {{
    "yield_curve_analysis": "수익률 곡선 분석 2문장. 역전 여부, 경기 시사점.",
    "dollar_analysis": "달러 방향 분석 1-2문장. 원/달러 영향.",
    "fed_watch": "연준 관련 시사점 1-2문장.",
    "upcoming_events": "이번 주 주요 경제 지표/이벤트 중 가장 중요한 것 2-3개 설명."
  }},
  "earnings_watch": {{
    "summary": "이번 주 실적 발표 요약 2-3문장.",
    "key_reports": [
      {{
        "company": "기업명",
        "date": "날짜",
        "expectation": "시장 기대 1문장",
        "impact": "영향도 1문장"
      }}
    ]
  }},
  "kr_market_outlook": {{
    "summary": "한국 시장 전망 3-4문장. 미국장 영향, 환율, 외인 수급 등.",
    "kospi_direction": "코스피 방향 예상 1문장",
    "watch_points": ["체크포인트 1", "체크포인트 2", "체크포인트 3"]
  }},
  "risk_radar": [
    {{
      "level": "HIGH / MEDIUM / LOW",
      "factor": "리스크 요인",
      "description": "설명 1-2문장",
      "hedge": "대응 방법 1문장"
    }}
  ],
  "trading_ideas": [
    {{
      "type": "주목 / 매수관심 / 리스크관리 / 숏관심",
      "stock": "종목명 (티커)",
      "timeframe": "단기 / 중기 / 장기",
      "reason": "근거 2문장",
      "risk": "리스크 1문장"
    }}
  ]
}}

Rules:
- 모든 내용 한국어
- key_highlights: 4-6개
- sector_rotation.sectors: 상위 3-4개 섹터
- risk_radar: 3-4개
- trading_ideas: 4-6개
- earnings_watch.key_reports: 최대 5개
- 구체적 수치(가격, 등락률, 날짜) 반드시 포함
- 뉴스 기반 팩트 위주, 근거 없는 추측 배제
- Fear & Greed 점수 변화 추이를 심리 분석에 반영
- 수익률 곡선 분석 반드시 포함"""

    import time
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash", contents=prompt
            )
            text = response.text.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"  JSON parse error (attempt {attempt+1}): {e}")
            print(f"  Raw response (first 300 chars): {response.text[:300]}")
            if attempt < 2:
                time.sleep(3)
        except Exception as e:
            print(f"  Gemini API error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(5)
    print("  All Gemini attempts failed")
    return {}


# =====================================================
# HTML EMAIL BUILDER
# =====================================================

def build_html_email(
    analysis: dict,
    us_indices: list[dict],
    us_futures: list[dict],
    sector_etfs: list[dict],
    bond_data: list[dict],
    yield_curve: dict,
    fx_data: list[dict],
    commodity_data: list[dict],
    crypto_data: list[dict],
    watchlist: dict[str, list[dict]],
    fear_greed: dict,
    economic_cal: list[dict],
    earnings_cal: list[dict],
    date_str: str,
) -> str:
    """Build styled HTML email for the pro stock report."""

    def c(val):
        if val > 0: return "#e74c3c"
        if val < 0: return "#2980b9"
        return "#666"

    def arr(val):
        if val > 0: return "▲"
        if val < 0: return "▼"
        return "−"

    def fp(price, symbol=""):
        if symbol.endswith(".KS") or symbol in ("KRW=X",):
            return f"{price:,.0f}"
        return f"{price:,.2f}"

    # === Section Builder ===
    def section_header(emoji, title, color="#1a1a2e"):
        return f"""<div style="background:{color};color:white;padding:10px 16px;border-radius:6px;font-size:15px;font-weight:bold;margin-bottom:14px;">{emoji} {title}</div>"""

    def data_table(title, emoji, data_list):
        rows = ""
        for d in data_list:
            rows += f"""<tr style="border-bottom:1px solid #f0f0f0;">
                <td style="padding:8px 12px;font-weight:600;color:#2c3e50;font-size:13px;">{d['name']}</td>
                <td style="padding:8px 12px;text-align:right;font-size:13px;font-family:monospace;">{fp(d['price'], d.get('symbol',''))}</td>
                <td style="padding:8px 12px;text-align:right;color:{c(d['change_pct'])};font-size:13px;font-family:monospace;font-weight:600;">
                  {arr(d['change_pct'])} {abs(d['change_pct'])}%</td></tr>"""
        return f"""<div style="margin-bottom:16px;">
          <div style="font-size:13px;font-weight:bold;color:#2c3e50;margin-bottom:6px;">{emoji} {title}</div>
          <table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:6px;overflow:hidden;">
            <thead><tr style="background:#f0f0f0;">
              <th style="padding:6px 12px;text-align:left;font-size:11px;color:#888;">Name</th>
              <th style="padding:6px 12px;text-align:right;font-size:11px;color:#888;">Price</th>
              <th style="padding:6px 12px;text-align:right;font-size:11px;color:#888;">Change</th>
            </tr></thead><tbody>{rows}</tbody></table></div>"""

    # === Market Summary ===
    ms = analysis.get("market_summary", {})
    sentiment = ms.get("sentiment", "Neutral")
    score = ms.get("sentiment_score", 5)
    s_map = {"Bullish": ("#27ae60", "#e8f8f5", "🟢"), "Bearish": ("#e74c3c", "#fdedec", "🔴"), "Neutral": ("#f39c12", "#fef9e7", "🟡")}
    s_color, s_bg, s_icon = s_map.get(sentiment, s_map["Neutral"])

    summary_html = f"""
    <div style="background:{s_bg};border-left:4px solid {s_color};padding:16px 20px;border-radius:0 8px 8px 0;margin-bottom:24px;">
      <div style="font-size:20px;font-weight:bold;color:#1a1a2e;margin-bottom:8px;">{s_icon} {ms.get('title', '')}</div>
      <div style="font-size:14px;color:#444;line-height:1.8;margin-bottom:10px;">{ms.get('overview', '')}</div>
      <div style="display:inline-block;background:{s_color};color:white;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:bold;">
        {sentiment} · Score {score}/10</div>
      <div style="font-size:12px;color:#666;margin-top:6px;">{ms.get('sentiment_reason', '')}</div>
    </div>"""

    # === Fear & Greed Gauge ===
    fg_html = ""
    if fear_greed:
        score_val = fear_greed.get("score", 0)
        rating = fear_greed.get("rating", "N/A")
        fg_color = "#e74c3c" if score_val < 25 else "#e67e22" if score_val < 45 else "#f1c40f" if score_val < 55 else "#2ecc71" if score_val < 75 else "#27ae60"
        fg_html = f"""
        <div style="background:#f8f9fa;padding:14px 20px;border-radius:8px;margin-bottom:20px;border-left:4px solid {fg_color};">
          <div style="font-size:14px;font-weight:bold;color:#2c3e50;margin-bottom:8px;">😱 CNN Fear & Greed Index</div>
          <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
            <div style="font-size:36px;font-weight:bold;color:{fg_color};">{score_val}</div>
            <div style="font-size:14px;font-weight:bold;color:{fg_color};">{rating}</div>
          </div>
          <div style="font-size:12px;color:#888;margin-top:8px;">
            전일: {fear_greed.get('previous_close', '-')} · 1주전: {fear_greed.get('previous_1_week', '-')} · 1개월전: {fear_greed.get('previous_1_month', '-')} · 1년전: {fear_greed.get('previous_1_year', '-')}
          </div>
        </div>"""

    # === Overnight Recap ===
    recap = analysis.get("overnight_recap", {})
    recap_html = ""
    if recap:
        recap_html = f"""
        <div style="background:#eef2f7;padding:16px 20px;border-radius:8px;margin-bottom:20px;">
          <div style="font-size:14px;font-weight:bold;color:#2c3e50;margin-bottom:10px;">🌙 오버나이트 리캡</div>
          <div style="font-size:13px;color:#444;line-height:1.8;margin-bottom:8px;">
            <strong>미국장:</strong> {recap.get('us_session', '')}</div>
          <div style="font-size:13px;color:#444;line-height:1.8;margin-bottom:8px;">
            <strong>선물:</strong> {recap.get('futures_direction', '')}</div>
          <div style="font-size:13px;color:#444;line-height:1.8;">
            <strong>글로벌:</strong> {recap.get('global_cues', '')}</div>
        </div>"""

    # === Market Data Tables ===
    market_tables = data_table("미국 주요 지수", "🇺🇸", us_indices)
    market_tables += data_table("선물 (프리마켓)", "⏰", us_futures)
    market_tables += data_table("채권 금리", "📊", bond_data)

    # Yield Curve
    if yield_curve:
        inv_color = "#e74c3c" if yield_curve["inverted"] else "#27ae60"
        inv_text = "역전 ⚠️" if yield_curve["inverted"] else "정상"
        market_tables += f"""<div style="background:#f8f9fa;padding:10px 16px;border-radius:6px;margin-bottom:16px;font-size:13px;">
          <strong>수익률 곡선 (10Y-2Y):</strong>
          <span style="color:{inv_color};font-weight:bold;"> {yield_curve['spread']}bp ({inv_text})</span>
        </div>"""

    market_tables += data_table("환율", "💱", fx_data)
    market_tables += data_table("원자재", "🛢️", commodity_data)
    market_tables += data_table("암호화폐", "₿", crypto_data)

    # === Sector ETF Heatmap Style ===
    sorted_sectors = sorted(sector_etfs, key=lambda x: x["change_pct"], reverse=True)
    sector_cells = ""
    for s in sorted_sectors:
        bg = "#dcf5dc" if s["change_pct"] > 0.5 else "#fddcdc" if s["change_pct"] < -0.5 else "#f5f5f5"
        tc = c(s["change_pct"])
        sector_cells += f"""<div style="display:inline-block;background:{bg};padding:8px 12px;border-radius:6px;margin:3px;min-width:120px;text-align:center;">
          <div style="font-size:11px;color:#666;font-weight:bold;">{s['name']}</div>
          <div style="font-size:14px;color:{tc};font-weight:bold;">{arr(s['change_pct'])} {abs(s['change_pct'])}%</div>
        </div>"""
    sector_etf_html = f"""<div style="margin-bottom:20px;">
      <div style="font-size:13px;font-weight:bold;color:#2c3e50;margin-bottom:8px;">📊 섹터 ETF 히트맵</div>
      <div style="display:flex;flex-wrap:wrap;gap:4px;">{sector_cells}</div>
    </div>"""

    # === Watchlist ===
    watchlist_html = ""
    cat_styles = {"Mag 7": ("🏆", "#8e44ad"), "Semicon": ("🔬", "#2c3e50"), "Finance": ("🏦", "#1a5276"), "KR Major": ("🇰🇷", "#c0392b")}
    for cat, stocks in watchlist.items():
        emoji, color = cat_styles.get(cat, ("📈", "#333"))
        rows = ""
        for s in stocks:
            vol = f"{s.get('volume', 0):,.0f}" if s.get("volume") else "-"
            rows += f"""<tr style="border-bottom:1px solid #f0f0f0;">
                <td style="padding:6px 12px;font-weight:600;color:#2c3e50;font-size:13px;">{s['name']}</td>
                <td style="padding:6px 12px;text-align:right;font-size:12px;font-family:monospace;">{fp(s['price'], s.get('symbol',''))}</td>
                <td style="padding:6px 12px;text-align:right;color:{c(s['change_pct'])};font-size:12px;font-family:monospace;font-weight:600;">
                  {arr(s['change_pct'])} {abs(s['change_pct'])}%</td>
                <td style="padding:6px 12px;text-align:right;font-size:11px;color:#999;">{vol}</td></tr>"""
        watchlist_html += f"""<div style="margin-bottom:14px;">
          <div style="font-size:13px;font-weight:bold;color:{color};margin-bottom:4px;">{emoji} {cat}</div>
          <table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:6px;overflow:hidden;">
            <thead><tr style="background:#f0f0f0;">
              <th style="padding:5px 12px;text-align:left;font-size:10px;color:#888;">종목</th>
              <th style="padding:5px 12px;text-align:right;font-size:10px;color:#888;">현재가</th>
              <th style="padding:5px 12px;text-align:right;font-size:10px;color:#888;">등락률</th>
              <th style="padding:5px 12px;text-align:right;font-size:10px;color:#888;">거래량</th>
            </tr></thead><tbody>{rows}</tbody></table></div>"""

    # === Key Highlights ===
    hl_html = ""
    for h in analysis.get("key_highlights", []):
        hl_html += f"""<div style="background:#f8f9fa;padding:14px 16px;border-radius:8px;margin-bottom:10px;border-left:4px solid #3498db;">
          <div style="font-size:15px;font-weight:bold;color:#1a1a2e;margin-bottom:6px;">{h.get('emoji','')} {h.get('title','')}</div>
          <div style="font-size:13px;color:#444;line-height:1.7;margin-bottom:4px;">{h.get('description','')}</div>
          <div style="font-size:12px;color:#e67e22;font-weight:600;">💡 {h.get('impact','')}</div>
          <div style="font-size:12px;color:#27ae60;margin-top:2px;">→ {h.get('action','')}</div>
        </div>"""

    # === Sector Rotation ===
    sr = analysis.get("sector_rotation", {})
    sr_html = ""
    if sr:
        sectors_detail = ""
        trend_colors = {"강세": "#27ae60", "약세": "#e74c3c", "보합": "#f39c12"}
        for s in sr.get("sectors", []):
            tc = trend_colors.get(s.get("trend", ""), "#666")
            sectors_detail += f"""<div style="background:#f8f9fa;padding:10px 14px;border-radius:6px;margin-bottom:8px;">
              <span style="font-size:13px;font-weight:bold;color:#2c3e50;">{s.get('name','')}</span>
              <span style="font-size:11px;font-weight:bold;color:{tc};background:{tc}22;padding:2px 6px;border-radius:4px;margin-left:6px;">{s.get('trend','')}</span>
              <div style="font-size:12px;color:#555;margin-top:4px;">{s.get('analysis','')}</div>
              <div style="font-size:11px;color:#888;margin-top:2px;">주요: {s.get('key_stocks','')}</div>
            </div>"""
        sr_html = f"""
        <div style="background:#e8f8f5;padding:12px 16px;border-radius:8px;margin-bottom:12px;">
          <div style="font-size:13px;color:#1a5276;line-height:1.7;"><strong>🟢 Leaders:</strong> {sr.get('leaders','')}</div>
          <div style="font-size:13px;color:#922b21;line-height:1.7;margin-top:4px;"><strong>🔴 Laggards:</strong> {sr.get('laggards','')}</div>
          <div style="font-size:13px;color:#7d6608;line-height:1.7;margin-top:4px;"><strong>🔄 Signal:</strong> {sr.get('rotation_signal','')}</div>
        </div>{sectors_detail}"""

    # === Macro Pulse ===
    mp = analysis.get("macro_pulse", {})
    mp_html = ""
    if mp:
        mp_html = f"""
        <div style="background:#f5f0ff;padding:16px 20px;border-radius:8px;border-left:4px solid #8e44ad;margin-bottom:20px;">
          <div style="font-size:14px;font-weight:bold;color:#6c3483;margin-bottom:10px;">🏛️ 매크로 펄스</div>
          <div style="font-size:13px;color:#444;line-height:1.8;margin-bottom:6px;"><strong>수익률 곡선:</strong> {mp.get('yield_curve_analysis','')}</div>
          <div style="font-size:13px;color:#444;line-height:1.8;margin-bottom:6px;"><strong>달러:</strong> {mp.get('dollar_analysis','')}</div>
          <div style="font-size:13px;color:#444;line-height:1.8;margin-bottom:6px;"><strong>연준:</strong> {mp.get('fed_watch','')}</div>
          <div style="font-size:13px;color:#444;line-height:1.8;"><strong>주요 이벤트:</strong> {mp.get('upcoming_events','')}</div>
        </div>"""

    # === Earnings Watch ===
    ew = analysis.get("earnings_watch", {})
    ew_html = ""
    if ew:
        reports = ""
        for r in ew.get("key_reports", []):
            reports += f"""<div style="background:#f8f9fa;padding:8px 14px;border-radius:6px;margin-bottom:6px;">
              <span style="font-size:13px;font-weight:bold;color:#2c3e50;">{r.get('company','')} ({r.get('date','')})</span>
              <div style="font-size:12px;color:#555;margin-top:2px;">{r.get('expectation','')}</div>
              <div style="font-size:11px;color:#e67e22;">{r.get('impact','')}</div>
            </div>"""
        ew_html = f"""<div style="margin-bottom:20px;">
          <div style="font-size:13px;color:#444;line-height:1.7;margin-bottom:10px;">{ew.get('summary','')}</div>
          {reports}</div>"""

    # === Economic Calendar Table ===
    econ_html = ""
    if economic_cal:
        econ_rows = ""
        for e in economic_cal[:8]:
            impact_dots = "🔴" * min(e.get("impact", 0), 3)
            econ_rows += f"""<tr style="border-bottom:1px solid #f0f0f0;">
              <td style="padding:6px 10px;font-size:12px;color:#888;">{e['date']}</td>
              <td style="padding:6px 10px;font-size:12px;color:#2c3e50;font-weight:600;">{e['event']}</td>
              <td style="padding:6px 10px;font-size:12px;text-align:center;">{impact_dots}</td>
              <td style="padding:6px 10px;font-size:12px;color:#888;text-align:right;">{e.get('estimate', '-')}</td>
              <td style="padding:6px 10px;font-size:12px;color:#888;text-align:right;">{e.get('prev', '-')}</td>
            </tr>"""
        econ_html = f"""<div style="margin-bottom:20px;">
          <table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:6px;overflow:hidden;">
            <thead><tr style="background:#f0f0f0;">
              <th style="padding:5px 10px;text-align:left;font-size:10px;color:#888;">날짜</th>
              <th style="padding:5px 10px;text-align:left;font-size:10px;color:#888;">이벤트</th>
              <th style="padding:5px 10px;text-align:center;font-size:10px;color:#888;">중요도</th>
              <th style="padding:5px 10px;text-align:right;font-size:10px;color:#888;">예상</th>
              <th style="padding:5px 10px;text-align:right;font-size:10px;color:#888;">이전</th>
            </tr></thead><tbody>{econ_rows}</tbody></table></div>"""

    # === KR Market Outlook ===
    kr = analysis.get("kr_market_outlook", {})
    kr_html = ""
    if kr:
        watch_items = "".join(f"<li style='margin-bottom:4px;'>{p}</li>" for p in kr.get("watch_points", []))
        kr_html = f"""
        <div style="background:#fff8e1;padding:16px 20px;border-radius:8px;border-left:4px solid #ff9800;margin-bottom:20px;">
          <div style="font-size:15px;font-weight:bold;color:#e65100;margin-bottom:8px;">🇰🇷 한국 시장 전망</div>
          <div style="font-size:13px;color:#444;line-height:1.7;margin-bottom:6px;">{kr.get('summary', '')}</div>
          <div style="font-size:13px;color:#d35400;font-weight:bold;margin-bottom:6px;">방향: {kr.get('kospi_direction', '')}</div>
          <div style="font-size:12px;font-weight:bold;color:#555;margin-bottom:4px;">📋 체크포인트</div>
          <ul style="font-size:12px;color:#555;line-height:1.8;margin:4px 0;padding-left:20px;">{watch_items}</ul>
        </div>"""

    # === Risk Radar ===
    risks = analysis.get("risk_radar", [])
    risk_html = ""
    if risks:
        level_styles = {"HIGH": ("#e74c3c", "🔴"), "MEDIUM": ("#f39c12", "🟡"), "LOW": ("#27ae60", "🟢")}
        risk_items = ""
        for r in risks:
            lc, le = level_styles.get(r.get("level", ""), ("#666", "⚪"))
            risk_items += f"""<div style="background:#f8f9fa;padding:10px 14px;border-radius:6px;margin-bottom:8px;border-left:3px solid {lc};">
              <div style="font-size:13px;font-weight:bold;color:#2c3e50;">{le} [{r.get('level','')}] {r.get('factor','')}</div>
              <div style="font-size:12px;color:#555;margin-top:4px;">{r.get('description','')}</div>
              <div style="font-size:11px;color:#2980b9;margin-top:2px;">🛡️ {r.get('hedge','')}</div>
            </div>"""
        risk_html = risk_items

    # === Trading Ideas ===
    ideas = analysis.get("trading_ideas", [])
    ideas_html = ""
    type_styles = {"주목": ("👀", "#3498db"), "매수관심": ("💰", "#27ae60"), "리스크관리": ("🛡️", "#e74c3c"), "숏관심": ("📉", "#8e44ad")}
    for idea in ideas:
        emoji, color = type_styles.get(idea.get("type", ""), ("📌", "#666"))
        tf = idea.get("timeframe", "")
        ideas_html += f"""<div style="background:#f8f9fa;padding:10px 14px;border-radius:6px;margin-bottom:8px;border-left:3px solid {color};">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-size:12px;font-weight:bold;color:{color};">{emoji} [{idea.get('type','')}] {idea.get('stock','')}</span>
            <span style="font-size:10px;color:#888;background:#eee;padding:2px 6px;border-radius:3px;">{tf}</span>
          </div>
          <div style="font-size:12px;color:#555;margin-top:4px;">{idea.get('reason','')}</div>
          <div style="font-size:11px;color:#e74c3c;margin-top:2px;">⚠️ {idea.get('risk','')}</div>
        </div>"""

    # === FULL EMAIL ===
    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Apple SD Gothic Neo','Segoe UI',Arial,sans-serif;">
  <div style="max-width:720px;margin:24px auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1);">

    <div style="background:linear-gradient(135deg,#0a0a23 0%,#1a1a3e 50%,#0d2137 100%);padding:30px 32px;text-align:center;">
      <h1 style="margin:0;color:white;font-size:24px;">📊 Daily Stock Report — Pro Edition</h1>
      <p style="margin:6px 0 0;color:rgba(255,255,255,.5);font-size:13px;">{date_str} · Morning Briefing</p>
    </div>

    <div style="padding:28px 32px;">
      {summary_html}
      {fg_html}
      {recap_html}

      <div style="margin-bottom:28px;">
        {section_header("📈", "시장 데이터")}
        {market_tables}
      </div>

      <div style="margin-bottom:28px;">
        {section_header("🏭", "섹터 로테이션")}
        {sector_etf_html}
        {sr_html}
      </div>

      <div style="margin-bottom:28px;">
        {section_header("👁️", "관심 종목")}
        {watchlist_html}
      </div>

      <div style="margin-bottom:28px;">
        {section_header("🔑", "핵심 하이라이트")}
        {hl_html}
      </div>

      {mp_html}

      <div style="margin-bottom:28px;">
        {section_header("📅", "이번 주 경제 캘린더")}
        {econ_html}
      </div>

      <div style="margin-bottom:28px;">
        {section_header("💼", "실적 발표 워치")}
        {ew_html}
      </div>

      {kr_html}

      <div style="margin-bottom:28px;">
        {section_header("⚠️", "리스크 레이더", "#c0392b")}
        {risk_html}
      </div>

      <div style="margin-bottom:28px;">
        {section_header("💡", "트레이딩 아이디어")}
        {ideas_html}
      </div>

      <div style="background:#f5f5f5;padding:12px 16px;border-radius:6px;margin-top:20px;">
        <div style="font-size:11px;color:#999;line-height:1.6;">
          ⚠️ 본 리포트는 정보 제공 목적으로 작성되었으며, 투자 권유가 아닙니다.
          투자 판단은 본인의 책임하에 이루어져야 하며, 본 리포트의 내용을 근거로 한 투자 손실에 대해 어떠한 책임도 지지 않습니다.
        </div>
      </div>
    </div>

    <div style="background:#f8f9fa;padding:16px 32px;text-align:center;color:#aaa;font-size:12px;border-top:1px solid #eee;">
      Generated automatically · Daily Stock Report Pro · {date_str}
    </div>
  </div>
</body>
</html>"""


# =====================================================
# EMAIL SENDER
# =====================================================

def send_email(html_content: str, date_str: str) -> None:
    """Send the HTML email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Daily Stock Report — {date_str}"
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(RECIPIENT_EMAILS)

    plain = f"Daily Stock Report — {date_str}\nPlease view this email in an HTML-capable mail client."
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAILS, msg.as_string())

    print(f"✅ Email sent to {', '.join(RECIPIENT_EMAILS)}")


# =====================================================
# MAIN
# =====================================================

def main() -> None:
    date_str = datetime.now(KST).strftime("%Y년 %m월 %d일 (%a)")
    print(f"📊 Generating Pro Stock Report for {date_str} …\n")

    # 1. Fetch all market data
    print("[US Indices]")
    us_indices = fetch_market_data(US_INDICES)
    print(f"  {len(us_indices)} fetched")

    print("[US Futures]")
    us_futures = fetch_market_data(US_FUTURES)
    print(f"  {len(us_futures)} fetched")

    print("[Sector ETFs]")
    sector_etfs = fetch_market_data(SECTOR_ETFS)
    print(f"  {len(sector_etfs)} fetched")

    print("[Bonds]")
    bond_data = fetch_market_data(BOND_TICKERS)
    print(f"  {len(bond_data)} fetched")

    print("[Yield Curve]")
    yield_curve = fetch_yield_curve(bond_data)
    print(f"  Spread: {yield_curve.get('spread', 'N/A')}bp")

    print("[FX]")
    fx_data = fetch_market_data(FX_TICKERS)
    print(f"  {len(fx_data)} fetched")

    print("[Commodities]")
    commodity_data = fetch_market_data(COMMODITY_TICKERS)
    print(f"  {len(commodity_data)} fetched")

    print("[Crypto]")
    crypto_data = fetch_market_data(CRYPTO_TICKERS)
    print(f"  {len(crypto_data)} fetched")

    print("[Watchlist]")
    watchlist = fetch_watchlist_data()
    total = sum(len(v) for v in watchlist.values())
    print(f"  {total} stocks fetched")

    print("[Fear & Greed Index]")
    fear_greed = fetch_fear_greed_index()
    print(f"  Score: {fear_greed.get('score', 'N/A')} ({fear_greed.get('rating', 'N/A')})")

    print("[Economic Calendar]")
    economic_cal = fetch_economic_calendar()
    print(f"  {len(economic_cal)} events")

    print("[Earnings Calendar]")
    earnings_cal = fetch_earnings_calendar()
    print(f"  {len(earnings_cal)} reports")

    print("[Market News]")
    news = fetch_market_news()
    print(f"  {len(news)} articles")

    # 2. AI Analysis
    print("\n🤖 Generating AI analysis …")
    analysis = generate_ai_analysis(
        us_indices, us_futures, sector_etfs, bond_data, yield_curve,
        fx_data, commodity_data, crypto_data, watchlist,
        fear_greed, economic_cal, earnings_cal, news,
    )
    print(f"  {len(analysis)} sections generated")

    # 3. Build and send email
    print("\n📧 Building and sending email …")
    html = build_html_email(
        analysis, us_indices, us_futures, sector_etfs, bond_data, yield_curve,
        fx_data, commodity_data, crypto_data, watchlist,
        fear_greed, economic_cal, earnings_cal, date_str,
    )
    send_email(html, date_str)


if __name__ == "__main__":
    main()
