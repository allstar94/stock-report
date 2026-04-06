#!/usr/bin/env python3
"""Daily Stock Market Report Generator using yfinance + Gemini + Gmail SMTP"""

import os
import json
import re
import smtplib
import feedparser
import yfinance as yf
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from google import genai

# --- Configuration ---
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = re.sub(r"[^\x20-\x7E]", " ", os.environ["GMAIL_APP_PASSWORD"]).strip()
RECIPIENT_EMAILS = ["alsltar94@gmail.com", "k30027@gmail.com"]

# --- Market Tickers ---
US_INDICES = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "Dow Jones": "^DJI",
    "Russell 2000": "^RUT",
    "VIX (공포지수)": "^VIX",
}

KR_INDICES = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
}

WATCHLIST = {
    "US Tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
    "US Semicon": ["TSM", "AVGO", "AMD", "INTC", "QCOM"],
    "KR Major": ["005930.KS", "000660.KS", "373220.KS", "035420.KS", "035720.KS"],
}

KR_STOCK_NAMES = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "373220.KS": "LG에너지솔루션",
    "035420.KS": "NAVER",
    "035720.KS": "카카오",
}

# --- Market News RSS ---
MARKET_NEWS_FEEDS = [
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.cnbc.com/id/10001147/device/rss/rss.html",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
]

CRYPTO_TICKERS = {
    "Bitcoin": "BTC-USD",
    "Ethereum": "ETH-USD",
}

COMMODITY_TICKERS = {
    "Gold": "GC=F",
    "WTI Oil": "CL=F",
    "Silver": "SI=F",
}

BOND_TICKERS = {
    "US 10Y Treasury": "^TNX",
    "US 2Y Treasury": "^IRX",
}

FX_TICKERS = {
    "USD/KRW": "KRW=X",
    "USD/JPY": "JPY=X",
    "EUR/USD": "EURUSD=X",
    "DXY (달러인덱스)": "DX-Y.NYB",
}


def fetch_market_data(tickers: dict[str, str]) -> list[dict]:
    """Fetch current price, change, change% for given tickers."""
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


def fetch_market_news(count: int = 15) -> list[dict]:
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
            if len(articles) >= count:
                break
        except Exception as e:
            print(f"  Warning: could not fetch {feed_url}: {e}")
    return articles[:count]


def generate_ai_analysis(
    us_indices: list[dict],
    kr_indices: list[dict],
    watchlist: dict[str, list[dict]],
    fx_data: list[dict],
    commodity_data: list[dict],
    crypto_data: list[dict],
    bond_data: list[dict],
    news: list[dict],
) -> dict:
    """Use Gemini to generate comprehensive market analysis."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Build market data context
    def format_data(data_list):
        return "\n".join(
            f"  - {d['name']}: {d['price']:,} ({'+' if d['change'] >= 0 else ''}{d['change']}, {'+' if d['change_pct'] >= 0 else ''}{d['change_pct']}%)"
            for d in data_list
        )

    watchlist_text = ""
    for cat, stocks in watchlist.items():
        watchlist_text += f"\n[{cat}]\n" + format_data(stocks)

    news_text = "\n".join(
        f"  [{i+1}] {a['source']}: {a['title']}\n      {a['summary'][:200]}"
        for i, a in enumerate(news)
    )

    prompt = f"""당신은 월스트리트 출신 시니어 금융 애널리스트입니다. 아래 실시간 시장 데이터와 뉴스를 바탕으로 한국 개인 투자자를 위한 종합 주식 리포트를 작성하세요.

=== 미국 주요 지수 ===
{format_data(us_indices)}

=== 한국 주요 지수 ===
{format_data(kr_indices)}

=== 환율/달러 ===
{format_data(fx_data)}

=== 원자재 ===
{format_data(commodity_data)}

=== 암호화폐 ===
{format_data(crypto_data)}

=== 채권 금리 ===
{format_data(bond_data)}

=== 주요 종목 ===
{watchlist_text}

=== 최근 시장 뉴스 ===
{news_text}

Return ONLY valid JSON — no markdown fences, no extra text:
{{
  "market_summary": {{
    "title": "오늘의 시장 한줄 요약 (예: 나스닥 2% 급등, AI 랠리 지속)",
    "overview": "전체 시장 흐름을 3-4문장으로 요약. 주요 지수 움직임, 핵심 테마 포함.",
    "sentiment": "Bullish / Bearish / Neutral 중 하나",
    "sentiment_reason": "시장 심리 판단 근거 1-2문장"
  }},
  "key_highlights": [
    {{
      "emoji": "적절한 이모지",
      "title": "핵심 포인트 제목",
      "description": "2-3문장 설명. 구체적 수치와 종목 포함.",
      "impact": "투자자에게 미치는 영향 1문장"
    }}
  ],
  "sector_analysis": [
    {{
      "sector": "섹터명 (예: 반도체, AI, 에너지)",
      "trend": "상승 / 하락 / 보합",
      "analysis": "해당 섹터 동향 2-3문장",
      "key_stocks": "주요 종목과 등락률"
    }}
  ],
  "kr_market_outlook": {{
    "summary": "한국 시장 전망 2-3문장. 미국 시장 영향, 환율 등 고려.",
    "watch_points": ["오늘 주목할 포인트 1", "포인트 2", "포인트 3"]
  }},
  "risk_factors": [
    "리스크 요인 1",
    "리스크 요인 2",
    "리스크 요인 3"
  ],
  "trading_ideas": [
    {{
      "type": "주목 / 매수관심 / 리스크관리",
      "stock": "종목명",
      "reason": "근거 1-2문장"
    }}
  ]
}}

Rules:
- 모든 내용은 한국어로 작성
- key_highlights: 3-5개
- sector_analysis: 3-4개 섹터
- trading_ideas: 3-5개 (투자 권유가 아닌 참고 의견임을 인지)
- 구체적 수치(가격, 등락률)를 최대한 포함
- 뉴스 기반 팩트 위주로 작성, 근거 없는 추측 배제"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )
        text = response.text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        print(f"  Raw response (first 500 chars): {response.text[:500]}")
        return {}
    except Exception as e:
        print(f"  Gemini API error: {e}")
        return {}


def build_html_email(
    analysis: dict,
    us_indices: list[dict],
    kr_indices: list[dict],
    watchlist: dict[str, list[dict]],
    fx_data: list[dict],
    commodity_data: list[dict],
    crypto_data: list[dict],
    bond_data: list[dict],
    date_str: str,
) -> str:
    """Build styled HTML email for the stock report."""

    def color_val(val):
        if val > 0:
            return "#e74c3c"
        elif val < 0:
            return "#2980b9"
        return "#666"

    def arrow(val):
        if val > 0:
            return "▲"
        elif val < 0:
            return "▼"
        return "−"

    def format_price(price, symbol=""):
        if symbol.endswith(".KS") or symbol in ("KRW=X",):
            return f"{price:,.0f}"
        return f"{price:,.2f}"

    # --- Market Summary ---
    ms = analysis.get("market_summary", {})
    sentiment = ms.get("sentiment", "Neutral")
    sentiment_colors = {
        "Bullish": ("#27ae60", "#e8f8f5", "🟢"),
        "Bearish": ("#e74c3c", "#fdedec", "🔴"),
        "Neutral": ("#f39c12", "#fef9e7", "🟡"),
    }
    s_color, s_bg, s_icon = sentiment_colors.get(sentiment, sentiment_colors["Neutral"])

    summary_html = f"""
    <div style="background:{s_bg};border-left:4px solid {s_color};padding:16px 20px;border-radius:0 8px 8px 0;margin-bottom:24px;">
      <div style="font-size:18px;font-weight:bold;color:#1a1a2e;margin-bottom:8px;">
        {s_icon} {ms.get('title', '시장 요약')}
      </div>
      <div style="font-size:14px;color:#444;line-height:1.8;margin-bottom:8px;">
        {ms.get('overview', '')}
      </div>
      <div style="font-size:13px;color:{s_color};font-weight:bold;">
        시장 심리: {sentiment} — {ms.get('sentiment_reason', '')}
      </div>
    </div>"""

    # --- Index Table ---
    def build_data_table(title, emoji, data_list, show_symbol=False):
        rows = ""
        for d in data_list:
            c = color_val(d["change_pct"])
            a = arrow(d["change_pct"])
            p = format_price(d["price"], d.get("symbol", ""))
            rows += f"""<tr style="border-bottom:1px solid #f0f0f0;">
                <td style="padding:10px 12px;font-weight:600;color:#2c3e50;font-size:13px;">{d['name']}</td>
                <td style="padding:10px 12px;text-align:right;font-size:13px;font-family:monospace;">{p}</td>
                <td style="padding:10px 12px;text-align:right;color:{c};font-size:13px;font-family:monospace;font-weight:600;">
                  {a} {abs(d['change_pct'])}%
                </td>
              </tr>"""
        return f"""
        <div style="margin-bottom:20px;">
          <div style="font-size:14px;font-weight:bold;color:#2c3e50;margin-bottom:8px;">{emoji} {title}</div>
          <table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:6px;overflow:hidden;">
            <thead><tr style="background:#f0f0f0;">
              <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;text-transform:uppercase;">Name</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;color:#888;text-transform:uppercase;">Price</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;color:#888;text-transform:uppercase;">Change</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""

    indices_html = build_data_table("미국 주요 지수", "🇺🇸", us_indices)
    indices_html += build_data_table("한국 주요 지수", "🇰🇷", kr_indices)
    indices_html += build_data_table("환율", "💱", fx_data)
    indices_html += build_data_table("원자재", "🛢️", commodity_data)
    indices_html += build_data_table("암호화폐", "₿", crypto_data)
    indices_html += build_data_table("채권 금리", "📊", bond_data)

    # --- Watchlist ---
    watchlist_html = ""
    cat_styles = {
        "US Tech": ("💻", "#8e44ad"),
        "US Semicon": ("🔬", "#2c3e50"),
        "KR Major": ("🇰🇷", "#c0392b"),
    }
    for cat, stocks in watchlist.items():
        emoji, color = cat_styles.get(cat, ("📈", "#333"))
        rows = ""
        for s in stocks:
            c = color_val(s["change_pct"])
            a = arrow(s["change_pct"])
            p = format_price(s["price"], s.get("symbol", ""))
            vol = f"{s.get('volume', 0):,.0f}" if s.get("volume") else "-"
            rows += f"""<tr style="border-bottom:1px solid #f0f0f0;">
                <td style="padding:8px 12px;font-weight:600;color:#2c3e50;font-size:13px;">{s['name']}</td>
                <td style="padding:8px 12px;text-align:right;font-size:13px;font-family:monospace;">{p}</td>
                <td style="padding:8px 12px;text-align:right;color:{c};font-size:13px;font-family:monospace;font-weight:600;">
                  {a} {abs(s['change_pct'])}%
                </td>
                <td style="padding:8px 12px;text-align:right;font-size:11px;color:#999;">{vol}</td>
              </tr>"""
        watchlist_html += f"""
        <div style="margin-bottom:16px;">
          <div style="font-size:13px;font-weight:bold;color:{color};margin-bottom:6px;">{emoji} {cat}</div>
          <table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:6px;overflow:hidden;">
            <thead><tr style="background:#f0f0f0;">
              <th style="padding:6px 12px;text-align:left;font-size:11px;color:#888;">종목</th>
              <th style="padding:6px 12px;text-align:right;font-size:11px;color:#888;">현재가</th>
              <th style="padding:6px 12px;text-align:right;font-size:11px;color:#888;">등락률</th>
              <th style="padding:6px 12px;text-align:right;font-size:11px;color:#888;">거래량</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""

    # --- Key Highlights ---
    highlights = analysis.get("key_highlights", [])
    highlights_html = ""
    for h in highlights:
        highlights_html += f"""
        <div style="background:#f8f9fa;padding:14px 16px;border-radius:8px;margin-bottom:10px;border-left:4px solid #3498db;">
          <div style="font-size:15px;font-weight:bold;color:#1a1a2e;margin-bottom:6px;">
            {h.get('emoji', '📌')} {h.get('title', '')}
          </div>
          <div style="font-size:13px;color:#444;line-height:1.7;margin-bottom:4px;">{h.get('description', '')}</div>
          <div style="font-size:12px;color:#e67e22;font-weight:600;">💡 {h.get('impact', '')}</div>
        </div>"""

    # --- Sector Analysis ---
    sectors = analysis.get("sector_analysis", [])
    sector_html = ""
    trend_colors = {"상승": "#27ae60", "하락": "#e74c3c", "보합": "#f39c12"}
    for s in sectors:
        tc = trend_colors.get(s.get("trend", ""), "#666")
        sector_html += f"""
        <div style="background:#f8f9fa;padding:12px 16px;border-radius:8px;margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <span style="font-size:14px;font-weight:bold;color:#2c3e50;">{s.get('sector', '')}</span>
            <span style="font-size:12px;font-weight:bold;color:{tc};background:{tc}22;padding:2px 8px;border-radius:4px;">{s.get('trend', '')}</span>
          </div>
          <div style="font-size:13px;color:#444;line-height:1.7;">{s.get('analysis', '')}</div>
          <div style="font-size:12px;color:#888;margin-top:4px;">주요 종목: {s.get('key_stocks', '')}</div>
        </div>"""

    # --- KR Market Outlook ---
    kr = analysis.get("kr_market_outlook", {})
    kr_html = ""
    if kr:
        watch_items = "".join(f"<li style='margin-bottom:4px;'>{p}</li>" for p in kr.get("watch_points", []))
        kr_html = f"""
        <div style="background:#fff8e1;padding:16px 20px;border-radius:8px;border-left:4px solid #ff9800;margin-bottom:20px;">
          <div style="font-size:15px;font-weight:bold;color:#e65100;margin-bottom:8px;">🇰🇷 한국 시장 전망</div>
          <div style="font-size:13px;color:#444;line-height:1.7;margin-bottom:8px;">{kr.get('summary', '')}</div>
          <div style="font-size:13px;font-weight:bold;color:#555;margin-bottom:4px;">📋 오늘의 체크포인트</div>
          <ul style="font-size:13px;color:#555;line-height:1.8;margin:4px 0;padding-left:20px;">{watch_items}</ul>
        </div>"""

    # --- Risk Factors ---
    risks = analysis.get("risk_factors", [])
    risk_html = ""
    if risks:
        risk_items = "".join(f"<li style='margin-bottom:4px;'>{r}</li>" for r in risks)
        risk_html = f"""
        <div style="background:#fdedec;padding:14px 20px;border-radius:8px;border-left:4px solid #e74c3c;margin-bottom:20px;">
          <div style="font-size:14px;font-weight:bold;color:#c0392b;margin-bottom:8px;">⚠️ 리스크 요인</div>
          <ul style="font-size:13px;color:#555;line-height:1.8;margin:0;padding-left:20px;">{risk_items}</ul>
        </div>"""

    # --- Trading Ideas ---
    ideas = analysis.get("trading_ideas", [])
    ideas_html = ""
    type_styles = {
        "주목": ("👀", "#3498db"),
        "매수관심": ("💰", "#27ae60"),
        "리스크관리": ("🛡️", "#e74c3c"),
    }
    for idea in ideas:
        emoji, color = type_styles.get(idea.get("type", ""), ("📌", "#666"))
        ideas_html += f"""
        <div style="background:#f8f9fa;padding:10px 14px;border-radius:6px;margin-bottom:8px;border-left:3px solid {color};">
          <span style="font-size:12px;font-weight:bold;color:{color};">{emoji} [{idea.get('type', '')}]</span>
          <span style="font-size:13px;font-weight:bold;color:#2c3e50;margin-left:6px;">{idea.get('stock', '')}</span>
          <div style="font-size:12px;color:#666;margin-top:4px;">{idea.get('reason', '')}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Apple SD Gothic Neo','Segoe UI',Arial,sans-serif;">
  <div style="max-width:700px;margin:24px auto;background:white;border-radius:12px;
              overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1);">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#0a0a23 0%,#1a1a3e 50%,#0d2137 100%);
                padding:30px 32px;text-align:center;">
      <h1 style="margin:0;color:white;font-size:24px;letter-spacing:0.5px;">
        📊 Daily Stock Report
      </h1>
      <p style="margin:6px 0 0;color:rgba(255,255,255,.6);font-size:13px;">{date_str} · Morning Briefing</p>
    </div>

    <div style="padding:28px 32px;">

      <!-- Market Summary -->
      {summary_html}

      <!-- Market Data -->
      <div style="margin-bottom:28px;">
        <div style="background:#1a1a2e;color:white;padding:10px 16px;border-radius:6px;font-size:15px;font-weight:bold;margin-bottom:14px;">
          📈 시장 데이터
        </div>
        {indices_html}
      </div>

      <!-- Watchlist -->
      <div style="margin-bottom:28px;">
        <div style="background:#1a1a2e;color:white;padding:10px 16px;border-radius:6px;font-size:15px;font-weight:bold;margin-bottom:14px;">
          👁️ 관심 종목
        </div>
        {watchlist_html}
      </div>

      <!-- Key Highlights -->
      <div style="margin-bottom:28px;">
        <div style="background:#1a1a2e;color:white;padding:10px 16px;border-radius:6px;font-size:15px;font-weight:bold;margin-bottom:14px;">
          🔑 핵심 하이라이트
        </div>
        {highlights_html}
      </div>

      <!-- Sector Analysis -->
      <div style="margin-bottom:28px;">
        <div style="background:#1a1a2e;color:white;padding:10px 16px;border-radius:6px;font-size:15px;font-weight:bold;margin-bottom:14px;">
          🏭 섹터별 분석
        </div>
        {sector_html}
      </div>

      <!-- KR Market Outlook -->
      {kr_html}

      <!-- Risk Factors -->
      {risk_html}

      <!-- Trading Ideas -->
      <div style="margin-bottom:28px;">
        <div style="background:#1a1a2e;color:white;padding:10px 16px;border-radius:6px;font-size:15px;font-weight:bold;margin-bottom:14px;">
          💡 트레이딩 아이디어
        </div>
        {ideas_html}
      </div>

      <!-- Disclaimer -->
      <div style="background:#f5f5f5;padding:12px 16px;border-radius:6px;margin-top:20px;">
        <div style="font-size:11px;color:#999;line-height:1.6;">
          ⚠️ 본 리포트는 정보 제공 목적으로 작성되었으며, 투자 권유가 아닙니다.
          투자 판단은 본인의 책임하에 이루어져야 하며, 본 리포트의 내용을 근거로 한 투자 손실에 대해 어떠한 책임도 지지 않습니다.
        </div>
      </div>

    </div>

    <!-- Footer -->
    <div style="background:#f8f9fa;padding:16px 32px;text-align:center;
                color:#aaa;font-size:12px;border-top:1px solid #eee;">
      Generated automatically · Daily Stock Report System · {date_str}
    </div>
  </div>
</body>
</html>"""


def send_email(html_content: str, date_str: str) -> None:
    """Send the HTML email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 Daily Stock Report — {date_str}"
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(RECIPIENT_EMAILS)

    plain = (
        f"Daily Stock Report — {date_str}\n\n"
        "Please view this email in an HTML-capable mail client."
    )
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAILS, msg.as_string())

    print(f"✅ Email sent to {', '.join(RECIPIENT_EMAILS)}")


def main() -> None:
    kst = timezone(timedelta(hours=9))
    date_str = datetime.now(kst).strftime("%Y년 %m월 %d일 (%a)")

    print(f"📊 Generating Daily Stock Report for {date_str} …\n")

    # 1. Fetch all market data
    print("[US Indices]")
    us_indices = fetch_market_data(US_INDICES)
    print(f"  Fetched {len(us_indices)} indices")

    print("[KR Indices]")
    kr_indices = fetch_market_data(KR_INDICES)
    print(f"  Fetched {len(kr_indices)} indices")

    print("[FX]")
    fx_data = fetch_market_data(FX_TICKERS)
    print(f"  Fetched {len(fx_data)} pairs")

    print("[Commodities]")
    commodity_data = fetch_market_data(COMMODITY_TICKERS)
    print(f"  Fetched {len(commodity_data)} items")

    print("[Crypto]")
    crypto_data = fetch_market_data(CRYPTO_TICKERS)
    print(f"  Fetched {len(crypto_data)} items")

    print("[Bonds]")
    bond_data = fetch_market_data(BOND_TICKERS)
    print(f"  Fetched {len(bond_data)} items")

    print("[Watchlist]")
    watchlist = fetch_watchlist_data()
    total_stocks = sum(len(v) for v in watchlist.values())
    print(f"  Fetched {total_stocks} stocks")

    print("[Market News]")
    news = fetch_market_news()
    print(f"  Fetched {len(news)} articles")

    # 2. AI Analysis
    print("\n🤖 Generating AI analysis …")
    analysis = generate_ai_analysis(
        us_indices, kr_indices, watchlist, fx_data,
        commodity_data, crypto_data, bond_data, news
    )
    print(f"  Analysis generated: {len(analysis)} sections")

    # 3. Build and send email
    print("\n📧 Building and sending email …")
    html = build_html_email(
        analysis, us_indices, kr_indices, watchlist,
        fx_data, commodity_data, crypto_data, bond_data, date_str
    )
    send_email(html, date_str)


if __name__ == "__main__":
    main()
