"""Streamlit 화면의 시각 체계와 재사용 가능한 HTML 컴포넌트."""

from __future__ import annotations

import base64
import html
from pathlib import Path

import streamlit as st


INK = "#12213B"
NAVY = "#102A83"
EXPORT = "#173D8F"
IMPORT = "#B8752B"
BRAND_RED = "#E5242A"
SKY = "#E1E8F5"
PAPER = "#F7F9FB"
PANEL = "#EEF3F6"
RULE = "#D7E0E6"
MUTED = "#607385"


_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap');

:root {{
    --ink: {INK}; --navy: {NAVY}; --export: {EXPORT}; --import: {IMPORT}; --brand-red: {BRAND_RED};
    --paper: {PAPER}; --panel: {PANEL}; --rule: {RULE}; --muted: {MUTED};
}}

html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
    font-family: 'IBM Plex Sans KR', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: var(--ink);
}}
[data-testid="stAppViewContainer"] {{ background: #FCFDFE; }}
.block-container {{ max-width: 1240px; padding-top: 2.1rem; padding-bottom: 3rem; }}

[data-testid="stSidebar"] {{
    background: #F1F5F8;
    border-right: 1px solid var(--rule);
}}
[data-testid="stSidebar"] .block-container {{ padding-top: 1.5rem; }}
[data-testid="stSidebar"] h3 {{
    color: var(--ink); font-size: 1.03rem; letter-spacing: -.01em; margin-bottom: .25rem;
}}

.stButton > button, .stDownloadButton > button {{
    min-height: 44px; border-radius: 8px; font-weight: 650; letter-spacing: -.01em;
    border: 1px solid var(--navy);
}}
.stButton > button[kind="primary"] {{
    background: var(--navy); color: white; box-shadow: 0 5px 14px rgba(22,58,95,.16);
}}
.stButton > button[kind="primary"]:hover {{ background: #0F2F4F; border-color: #0F2F4F; }}

[data-baseweb="input"] > div, [data-baseweb="select"] > div {{
    border-radius: 8px !important; border-color: #CBD7DF !important; background: white !important;
}}

.masthead {{
    display: flex; align-items: center; justify-content: space-between; gap: 22px;
    padding: 7px 0 22px; margin-bottom: 18px; border-bottom: 1px solid var(--rule);
}}
.brand-lockup {{ display: flex; align-items: center; gap: 16px; min-width: 0; }}
.brand-lockup > div:last-child {{ min-width: 0; }}
.masthead-logo {{ width: 166px; height: auto; display: block; flex: 0 0 166px; }}
.brand-divider {{ width: 1px; height: 48px; flex: 0 0 1px; background: var(--rule); }}
.masthead h1 {{ margin: 0 0 4px; color: var(--ink); font-size: clamp(24px, 3vw, 32px); letter-spacing: -.035em; }}
.masthead p {{ margin: 0; color: var(--muted); font-size: 13px; }}
.masthead-meta {{ text-align: right; }}
.eyebrow {{
    font: 600 11px/1.4 'IBM Plex Mono', monospace; letter-spacing: .1em; text-transform: uppercase;
    color: var(--export); margin-bottom: 6px;
}}
.meta-copy {{ color: var(--muted); font-size: 12px; }}
.analysis-band {{
    display: flex; justify-content: space-between; align-items: center; gap: 12px;
    margin: 2px 0 14px; padding: 9px 12px; border-left: 3px solid var(--navy);
    background: linear-gradient(90deg, rgba(16,42,131,.055), rgba(16,42,131,0));
}}
.analysis-band strong {{ font-size: 12px; color: var(--ink); }}
.analysis-band span {{ font: 500 10px/1.4 'IBM Plex Mono', monospace; color: var(--muted); letter-spacing: .06em; }}

.trust-strip {{
    display: grid; grid-template-columns: repeat(4, minmax(0,1fr));
    border: 1px solid var(--rule); border-radius: 10px; background: var(--paper);
    margin: 0 0 24px; overflow: hidden;
}}
.trust-item {{ min-width: 0; padding: 12px 16px; border-right: 1px solid var(--rule); }}
.trust-item:last-child {{ border-right: none; }}
.trust-label {{ font-size: 10px; color: var(--muted); letter-spacing: .08em; text-transform: uppercase; }}
.trust-value {{ margin-top: 3px; color: var(--ink); font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }}

.status-banner {{
    display: flex; gap: 10px; align-items: flex-start; padding: 11px 14px; margin-bottom: 20px;
    border-radius: 8px; border: 1px solid #E5D6C8; background: #FFF8F1; color: #704321; font-size: 13px;
}}
.status-dot {{ width: 8px; height: 8px; flex: 0 0 auto; margin-top: 5px; border-radius: 50%; background: var(--import); }}

.market-tape {{
    position: relative; overflow: hidden; margin: -6px 0 24px; border: 1px solid #263A54;
    border-radius: 10px; background: #0D1A2B; box-shadow: 0 8px 24px rgba(13,26,43,.13);
}}
.market-tape::before, .market-tape::after {{
    content: ''; position: absolute; z-index: 2; top: 0; bottom: 0; width: 28px; pointer-events: none;
}}
.market-tape::before {{ left: 0; background: linear-gradient(90deg, #0D1A2B, transparent); }}
.market-tape::after {{ right: 0; background: linear-gradient(270deg, #0D1A2B, transparent); }}
.market-tape-track {{ display: flex; width: max-content; animation: market-scroll 38s linear infinite; }}
.market-tape:hover .market-tape-track {{ animation-play-state: paused; }}
.market-tape-set {{ display: flex; align-items: stretch; flex: 0 0 auto; }}
.ticker-item {{
    display: grid; grid-template-columns: auto auto; column-gap: 12px; align-content: center;
    min-width: 205px; padding: 13px 18px; border-right: 1px solid rgba(255,255,255,.13);
}}
.ticker-label {{ color: #AAB8C8; font: 500 10px/1.35 'IBM Plex Mono', monospace; letter-spacing: .06em; text-transform: uppercase; }}
.ticker-status {{ margin-left: 6px; color: #6F8298; font-size: 8px; letter-spacing: .04em; }}
.ticker-value {{
    grid-column: 1; margin-top: 3px; color: #FFFFFF; font: 600 15px/1.2 'IBM Plex Mono', monospace;
    font-variant-numeric: tabular-nums; animation: quote-flash .9s ease-out 1;
}}
.ticker-change {{
    grid-column: 2; grid-row: 1 / span 2; align-self: center; justify-self: end;
    font: 600 11px/1.2 'IBM Plex Mono', monospace; white-space: nowrap;
}}
.ticker-change.up {{ color: #8EB8FF; }}
.ticker-change.down {{ color: #E4AD67; }}
.ticker-change.neutral {{ color: #91A1B3; }}

.market-status-row {{
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    margin: 3px 0 14px; color: var(--muted); font: 500 10px/1.4 'IBM Plex Mono', monospace;
}}
.market-status-left {{ display: flex; align-items: center; gap: 7px; }}
.market-live-dot {{
    width: 7px; height: 7px; border-radius: 50%; background: var(--export);
    box-shadow: 0 0 0 0 rgba(23,61,143,.32); animation: live-pulse 2.4s ease-out infinite;
}}
.market-live-dot.offline {{ background: #9AACBA; box-shadow: none; animation: none; }}
.signal-card {{
    min-height: 112px; padding: 15px 16px; margin-bottom: 10px; border: 1px solid var(--rule);
    border-radius: 9px; background: #FFFFFF; border-left: 3px solid var(--export);
}}
.signal-card.watch {{ border-left-color: var(--import); }}
.signal-card.neutral {{ border-left-color: #9AACBA; }}
.signal-status {{
    font: 600 9px/1.35 'IBM Plex Mono', monospace; color: var(--export); letter-spacing: .09em;
    text-transform: uppercase;
}}
.signal-card.watch .signal-status {{ color: var(--import); }}
.signal-card.neutral .signal-status {{ color: var(--muted); }}
.signal-title {{ margin: 8px 0 4px; color: var(--ink); font-size: 14px; font-weight: 700; }}
.signal-copy {{ color: var(--muted); font-size: 11px; line-height: 1.55; }}

@keyframes market-scroll {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
@keyframes quote-flash {{ 0% {{ color: #FFFFFF; }} 35% {{ color: #8EB8FF; text-shadow: 0 0 8px rgba(142,184,255,.55); }} 100% {{ color: #FFFFFF; }} }}
@keyframes live-pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(23,61,143,.34); }} 70% {{ box-shadow: 0 0 0 7px rgba(23,61,143,0); }} 100% {{ box-shadow: 0 0 0 0 rgba(23,61,143,0); }} }}

.section-title {{ margin: 6px 0 16px; }}
.section-title h2 {{ margin: 0 0 5px; font-size: 20px; color: var(--ink); letter-spacing: -.025em; }}
.section-title p {{ margin: 0; font-size: 13px; color: var(--muted); }}

.kpi-card {{
    min-height: 142px; padding: 18px 18px 16px; background: white; border: 1px solid var(--rule);
    border-radius: 10px; box-shadow: 0 4px 14px rgba(26,46,66,.045);
}}
.kpi-top {{ display: flex; justify-content: space-between; gap: 10px; align-items: center; }}
.kpi-label {{ color: var(--muted); font-size: 12px; font-weight: 600; }}
.kpi-index {{ font: 500 10px/1 'IBM Plex Mono', monospace; color: #8CA0AF; }}
.kpi-value {{
    margin: 18px 0 8px; font: 600 clamp(21px, 2.5vw, 28px)/1 'IBM Plex Mono', monospace;
    color: var(--ink); letter-spacing: -.04em; font-variant-numeric: tabular-nums;
}}
.kpi-note {{ font-size: 11px; line-height: 1.45; color: var(--muted); }}
.kpi-note .up {{ color: var(--export); font-weight: 700; }}
.kpi-note .down {{ color: var(--import); font-weight: 700; }}

.chart-heading {{ margin: 8px 0 2px; font-size: 16px; font-weight: 700; color: var(--ink); }}
.chart-subtitle {{ margin: 0 0 8px; font-size: 11px; color: var(--muted); }}
.insight-card {{
    min-height: 92px; padding: 15px 16px; margin-bottom: 10px; border-radius: 9px;
    background: var(--paper); border: 1px solid var(--rule);
}}
.insight-kicker {{ font: 600 10px/1.4 'IBM Plex Mono', monospace; color: var(--export); letter-spacing: .07em; text-transform: uppercase; }}
.insight-title {{ margin: 7px 0 3px; font-size: 14px; font-weight: 700; color: var(--ink); }}
.insight-copy {{ font-size: 12px; line-height: 1.55; color: var(--muted); }}

.source-note {{
    margin-top: 30px; padding-top: 14px; border-top: 1px solid var(--rule);
    font: 400 10px/1.6 'IBM Plex Mono', monospace; color: var(--muted);
}}
.sidebar-brand {{ padding: 3px 0 15px; }}
.sidebar-logo {{ display: block; width: 176px; height: auto; margin-bottom: 8px; }}
.sidebar-brand span {{ font: 600 10px/1.4 'IBM Plex Mono', monospace; letter-spacing: .11em; color: var(--navy); }}
.sidebar-help {{
    padding: 11px 12px; border: 1px solid var(--rule); border-radius: 8px;
    background: rgba(255,255,255,.62); color: var(--muted); font-size: 11px; line-height: 1.55;
}}

.stTabs [data-baseweb="tab-list"] {{ gap: 22px; border-bottom: 1px solid var(--rule); }}
.stTabs [data-baseweb="tab"] {{
    height: 46px; padding: 0 2px; font-size: 13px; font-weight: 650; color: var(--muted);
}}
.stTabs [aria-selected="true"] {{ color: var(--navy) !important; }}
[data-testid="stDataFrame"] {{ border: 1px solid var(--rule); border-radius: 9px; overflow: hidden; }}

@media (max-width: 760px) {{
    .block-container {{ padding-top: 4rem; }}
    .masthead {{ align-items: flex-start; }}
    .brand-lockup {{ display: block; width: 100%; }}
    .masthead-meta {{ display: none; }}
    .masthead-logo {{ width: 150px; margin-bottom: 18px; }}
    .brand-divider {{ display: none; }}
    .masthead h1 {{ font-size: 27px; line-height: 1.22; word-break: keep-all; overflow-wrap: normal; }}
    .masthead p {{ line-height: 1.65; word-break: keep-all; }}
    .section-title h2 {{ font-size: 19px; line-height: 1.45; word-break: keep-all; }}
    .trust-strip {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
    .trust-item:nth-child(2) {{ border-right: none; }}
    .trust-item:nth-child(-n+2) {{ border-bottom: 1px solid var(--rule); }}
    .kpi-card {{ min-height: 126px; margin-bottom: 8px; }}
    .market-tape {{ margin-top: 0; }}
    .ticker-item {{ min-width: 178px; padding: 12px 15px; }}
    .market-status-row {{ align-items: flex-start; flex-direction: column; }}
}}

@media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; transition: none !important; }} }}
</style>
"""


def inject() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def asset_data_uri(path: str | Path, mime: str = "image/svg+xml") -> str:
    """로컬 브랜드 자산을 배포 가능한 data URI로 변환한다."""
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def section_title(title: str, subtitle: str) -> None:
    st.markdown(
        f"<div class='section-title'><h2>{esc(title)}</h2><p>{esc(subtitle)}</p></div>",
        unsafe_allow_html=True,
    )


def kpi_card(index: str, label: str, value: str, note: str, tone: str = "neutral") -> None:
    tone_class = "up" if tone == "positive" else "down" if tone == "negative" else ""
    st.markdown(
        "<div class='kpi-card'>"
        f"<div class='kpi-top'><span class='kpi-label'>{esc(label)}</span>"
        f"<span class='kpi-index'>{esc(index)}</span></div>"
        f"<div class='kpi-value'>{esc(value)}</div>"
        f"<div class='kpi-note'><span class='{tone_class}'>{esc(note)}</span></div>"
        "</div>",
        unsafe_allow_html=True,
    )


def insight_card(kicker: str, title: str, copy: str) -> None:
    st.markdown(
        "<div class='insight-card'>"
        f"<div class='insight-kicker'>{esc(kicker)}</div>"
        f"<div class='insight-title'>{esc(title)}</div>"
        f"<div class='insight-copy'>{esc(copy)}</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def market_tape(items: list[dict[str, str]]) -> None:
    """최신값·변화율·데이터 주기를 흐르는 시장 테이프로 표시한다."""
    cells = "".join(
        "<div class='ticker-item'>"
        f"<div class='ticker-label'>{esc(item['label'])}"
        f"<span class='ticker-status'>{esc(item['status'])}</span></div>"
        f"<div class='ticker-value'>{esc(item['value'])}</div>"
        f"<div class='ticker-change {esc(item.get('tone', 'neutral'))}'>{esc(item['change'])}</div>"
        "</div>"
        for item in items
    )
    st.markdown(
        "<div class='market-tape'><div class='market-tape-track'>"
        f"<div class='market-tape-set'>{cells}</div>"
        f"<div class='market-tape-set' aria-hidden='true'>{cells}</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )


def signal_card(status: str, title: str, copy: str, tone: str = "positive") -> None:
    tone_class = "watch" if tone == "negative" else "neutral" if tone == "neutral" else ""
    st.markdown(
        f"<div class='signal-card {tone_class}'>"
        f"<div class='signal-status'>{esc(status)}</div>"
        f"<div class='signal-title'>{esc(title)}</div>"
        f"<div class='signal-copy'>{esc(copy)}</div>"
        "</div>",
        unsafe_allow_html=True,
    )
