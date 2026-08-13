"""화면 스타일과 커스텀 컴포넌트."""

import streamlit as st

# 통관 서류의 스탬프 잉크와 컨테이너 도장에서 가져온 팔레트
INK = "#14202B"      # 신고필증 스탬프 잉크
EXPORT = "#0B6E6E"   # 반출 — 심해 청록
IMPORT = "#B4531A"   # 반입 — 컨테이너 도장 녹빛
PANEL = "#EDF1F3"    # 강재 표면 톤
RULE = "#C6D0D6"
MUTED = "#5C6B77"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'IBM Plex Sans KR', -apple-system, sans-serif;
}}

.block-container {{ padding-top: 2.2rem; max-width: 1180px; }}

/* 머리말 — 신고서 상단 블록처럼 */
.masthead {{
    display: flex; align-items: center; gap: 18px;
    padding-bottom: 18px; margin-bottom: 26px;
    border-bottom: 2px solid {INK};
}}
.masthead-mark {{
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600; font-size: 20px; letter-spacing: .06em;
    color: {INK};
    border: 2px solid {INK}; border-radius: 2px;
    padding: 10px 12px; line-height: 1;
}}
.masthead h1 {{
    font-size: 25px; font-weight: 700; color: {INK};
    margin: 0 0 3px 0; letter-spacing: -.01em;
}}
.masthead p {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px; color: {MUTED}; margin: 0; letter-spacing: .02em;
}}

.section-head {{
    display: flex; align-items: baseline; justify-content: space-between;
    flex-wrap: wrap; gap: 8px;
    font-size: 19px; font-weight: 600; color: {INK};
    margin: 4px 0 18px 0;
}}
.section-head span {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px; font-weight: 400; color: {MUTED};
}}

.rule {{ height: 1px; background: {RULE}; margin: 26px 0 6px 0; }}

.demo-flag {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px; color: {IMPORT};
    border-left: 3px solid {IMPORT};
    background: rgba(180, 83, 26, .06);
    padding: 9px 13px; margin-bottom: 20px;
}}

/* 무역수지 저울 — 중심선에서 양쪽으로 갈라지는 막대 */
.scale {{
    background: {PANEL};
    border: 1px solid {RULE};
    padding: 20px 22px 16px 22px;
    margin-bottom: 22px;
}}
.scale-top {{
    display: flex; justify-content: space-between;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px; letter-spacing: .09em; text-transform: uppercase;
    color: {MUTED}; margin-bottom: 9px;
}}
.scale-track {{
    position: relative; height: 34px;
    display: flex; align-items: center;
}}
.scale-half {{ height: 26px; display: flex; align-items: center; width: 50%; }}
.scale-half.left  {{ justify-content: flex-end; }}
.scale-half.right {{ justify-content: flex-start; }}
.scale-bar {{ height: 100%; }}
.scale-bar.exp {{ background: {EXPORT}; }}
.scale-bar.imp {{ background: {IMPORT}; }}
.scale-axis {{
    position: absolute; left: 50%; top: -3px; bottom: -3px;
    width: 2px; background: {INK};
}}
.scale-foot {{
    display: flex; justify-content: space-between;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 14px; font-weight: 600; color: {INK}; margin-top: 9px;
}}

/* 지표 숫자를 표 조판용 서체로 */
[data-testid="stMetricValue"] {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 24px; font-variant-numeric: tabular-nums; color: {INK};
}}
[data-testid="stMetricLabel"] {{
    font-size: 12px; letter-spacing: .04em; color: {MUTED};
}}

.stTabs [data-baseweb="tab"] {{
    font-size: 14px; font-weight: 500;
}}

.footnote {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px; color: {MUTED};
    border-top: 1px solid {RULE};
    margin-top: 34px; padding-top: 12px;
}}

@media (prefers-reduced-motion: reduce) {{
    * {{ animation: none !important; transition: none !important; }}
}}
</style>
"""


def inject():
    st.markdown(_CSS, unsafe_allow_html=True)


def balance_scale(export_value, import_value):
    """
    수출과 수입을 중심선 기준 좌우로 그려 무역수지를 한눈에 보여준다.
    긴 쪽이 100%를 차지하고 짧은 쪽은 그 비율만큼 그려진다.
    """
    peak = max(export_value, import_value, 1)
    exp_pct = export_value / peak * 100
    imp_pct = import_value / peak * 100

    st.markdown(
        f"""
        <div class="scale">
          <div class="scale-top"><span>Export · 수출</span><span>수입 · Import</span></div>
          <div class="scale-track">
            <div class="scale-half left">
              <div class="scale-bar exp" style="width:{exp_pct:.2f}%"></div>
            </div>
            <div class="scale-half right">
              <div class="scale-bar imp" style="width:{imp_pct:.2f}%"></div>
            </div>
            <div class="scale-axis"></div>
          </div>
          <div class="scale-foot">
            <span>{export_value/1000:,.1f}백만 $</span>
            <span>{import_value/1000:,.1f}백만 $</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
