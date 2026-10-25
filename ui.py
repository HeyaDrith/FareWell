"""Shared look for every page: fonts, colors, the beach hero and the glass cards.

The design follows the team's Figma (light-blue top bar, rounded display type, a tropical
hero with frosted-glass cards, pill inputs). Everything here is CSS or escaped HTML; no
user or provider text is ever inserted unescaped.
"""
from html import escape
from urllib.parse import quote

import streamlit as st

# A drawn beach scene (sky, sun, sea, sand, palms) so the hero needs no photo download.
_BEACH_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 560' preserveAspectRatio='xMidYMid slice'>
<defs>
 <linearGradient id='sky' x1='0' y1='0' x2='0' y2='1'>
  <stop offset='0' stop-color='#5BB8EC'/><stop offset='0.55' stop-color='#A9DDF5'/><stop offset='1' stop-color='#FFE3C2'/>
 </linearGradient>
 <linearGradient id='sea' x1='0' y1='0' x2='0' y2='1'>
  <stop offset='0' stop-color='#2BC4D6'/><stop offset='1' stop-color='#0A7FB0'/>
 </linearGradient>
 <radialGradient id='sun' cx='0.5' cy='0.5' r='0.5'>
  <stop offset='0' stop-color='#FFF3C4'/><stop offset='0.6' stop-color='#FFD27A'/><stop offset='1' stop-color='#FFD27A' stop-opacity='0'/>
 </radialGradient>
</defs>
<rect width='1440' height='560' fill='url(#sky)'/>
<circle cx='1130' cy='170' r='130' fill='url(#sun)'/>
<path d='M0 330 Q360 300 720 322 T1440 318 V560 H0 Z' fill='url(#sea)'/>
<path d='M0 360 Q120 350 240 360 T480 360 T720 360 T960 360 T1200 360 T1440 360' stroke='#FFFFFF' stroke-opacity='0.35' stroke-width='3' fill='none'/>
<path d='M0 400 Q150 388 300 400 T600 400 T900 400 T1200 400 T1500 400' stroke='#FFFFFF' stroke-opacity='0.25' stroke-width='3' fill='none'/>
<path d='M0 470 Q300 430 640 452 T1440 430 V560 H0 Z' fill='#F4DDB4'/>
<path d='M0 500 Q320 470 700 488 T1440 470 V560 H0 Z' fill='#EBCD98'/>
<g fill='none' stroke='#0B3B4A' stroke-opacity='0.82' stroke-linecap='round'>
 <path d='M130 520 Q150 380 210 250' stroke-width='16'/>
 <path d='M210 250 Q140 215 70 250' stroke-width='14'/><path d='M210 250 Q170 170 100 165' stroke-width='14'/>
 <path d='M210 250 Q240 170 310 160' stroke-width='14'/><path d='M210 250 Q290 225 350 265' stroke-width='14'/>
 <path d='M210 250 Q215 300 175 335' stroke-width='12'/>
 <path d='M1330 525 Q1300 400 1250 300' stroke-width='14'/>
 <path d='M1250 300 Q1190 270 1135 300' stroke-width='12'/><path d='M1250 300 Q1225 235 1165 225' stroke-width='12'/>
 <path d='M1250 300 Q1290 235 1345 235' stroke-width='12'/><path d='M1250 300 Q1310 290 1360 325' stroke-width='12'/>
</g>
</svg>"""
BEACH_URL = "data:image/svg+xml;charset=utf-8," + quote(" ".join(_BEACH_SVG.split()))

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700;800&family=Inter:wght@400;500;600;700&display=swap');

:root {
  --ts-navy: #0B2545; --ts-ink: #334E68; --ts-muted: #627D98;
  --ts-sky: #DCEAF7; --ts-ocean: #0E7CC4; --ts-teal: #14B8C7;
  --ts-coral: #FF6B57; --ts-sun: #FFB547; --ts-sand: #F4DDB4;
  --ts-card: #FFFFFF; --ts-line: #D3E0EE;
  --ts-shadow: 0 10px 30px rgba(11, 37, 69, 0.10);
}
/* Text only: a broad selector would also replace Streamlit's Material icon font. */
html, body, p, li, label, input, textarea, .stMarkdown, [data-testid="stCaptionContainer"] {
  font-family: 'Inter', system-ui, sans-serif; }
h1, h2, h3, h1 *, h2 *, h3 *, .ts-display { font-family: 'Baloo 2', 'Inter', sans-serif !important;
  letter-spacing: -0.01em; color: var(--ts-navy); }
h2 { font-weight: 800 !important; }

/* Page width and spacing */
[data-testid="stMainBlockContainer"], .block-container { max-width: 1180px; padding-top: 4.5rem; padding-bottom: 4rem; }

/* Top bar (st.navigation position="top") in the design's light blue */
header[data-testid="stHeader"] { background: rgba(220, 234, 247, 0.92); backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--ts-line); }
img[data-testid="stHeaderLogo"] { height: 2.6rem !important; max-height: none !important; width: auto !important;
  margin-right: 0.75rem; }

/* Pill inputs like the Figma form */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-testid="stNumberInputContainer"] {
  border-radius: 999px !important; background: #FFFFFF; }
[data-testid="stNumberInputContainer"] [data-baseweb="input"] { border-radius: 999px 0 0 999px !important; }
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="base-input"] input,
[data-baseweb="select"] > div, [data-testid="stNumberInputContainer"] button { background-color: #FFFFFF !important; }
.stDateInput [data-baseweb="input"] { border-radius: 999px !important; }

/* Buttons: sunset gradient for the main actions, soft pills for the rest */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(135deg, var(--ts-coral), var(--ts-sun)) !important; border: none !important;
  color: #fff !important; font-weight: 700; border-radius: 999px !important; padding: 0.55rem 1.4rem;
  box-shadow: 0 8px 20px rgba(255, 107, 87, 0.35); transition: transform .15s ease, box-shadow .15s ease; }
[data-testid="stBaseButton-primary"]:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 12px 26px rgba(255, 107, 87, 0.45); }
[data-testid="stBaseButton-primary"]:disabled { background: #C9D6E3 !important; box-shadow: none; }
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"], [data-testid="stBaseLinkButton-secondary"] {
  border-radius: 999px !important; border-color: var(--ts-line) !important; background: #FFFFFF; font-weight: 600; }
[data-testid="stBaseButton-secondary"]:hover:not(:disabled) { border-color: var(--ts-ocean) !important; color: var(--ts-ocean) !important; }

/* Metric tiles */
[data-testid="stMetric"] { background: var(--ts-card); border: 1px solid var(--ts-line); border-radius: 18px;
  padding: 14px 18px; box-shadow: var(--ts-shadow); }
[data-testid="stMetricValue"] { font-family: 'Baloo 2', sans-serif; font-weight: 800; color: var(--ts-navy); }
[data-testid="stProgress"] > div > div > div > div { background: linear-gradient(90deg, var(--ts-teal), var(--ts-ocean)); }

/* Cards made from keyed containers (st.container(key="card-...")) */
[class*="st-key-card-"] { background: var(--ts-card); border: 1px solid var(--ts-line); border-radius: 22px;
  padding: 22px 24px; box-shadow: var(--ts-shadow); }
[class*="st-key-opt-"] { background: var(--ts-card); border: 1px solid var(--ts-line); border-radius: 16px;
  padding: 10px 14px; transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease; }
[class*="st-key-opt-"]:hover { border-color: #9CC9EA; box-shadow: 0 8px 22px rgba(14, 124, 196, 0.12); transform: translateY(-1px); }
/* An option that's in the trip: green border, soft green fill and a check bar on the left */
[class*="st-key-opt-"][class*="-picked"], [class*="st-key-opt-"][class*="-picked"]:hover {
  border: 2px solid #22A06B; background: #EFFAF4; box-shadow: inset 6px 0 0 #22A06B, 0 8px 22px rgba(34, 160, 107, 0.16); }
[class*="st-key-opt-"][class*="-picked"] strong { color: #0F7A4F; }
[class*="st-key-opt-"][class*="-picked"] [data-testid="stBaseButton-secondary"] {
  border-color: #F2B8B5 !important; color: #C0392B !important; background: #FFFFFF; }
[class*="st-key-opt-"][class*="-picked"] [data-testid="stBaseButton-secondary"]:hover:not(:disabled) {
  border-color: #C0392B !important; background: #FDECEA; }

/* Beach heroes */
.st-key-hero-home, .st-key-hero-plan { position: relative; border-radius: 28px; overflow: hidden;
  background: linear-gradient(180deg, rgba(11, 37, 69, 0.10), rgba(11, 37, 69, 0.28)), url("BEACH") center / cover no-repeat;
  padding: 34px 30px 30px; box-shadow: 0 18px 40px rgba(11, 37, 69, 0.18); }
.st-key-hero-plan h1, .st-key-hero-plan h1 *, .st-key-hero-home h1, .st-key-hero-home h1 * {
  color: #FFFFFF !important; text-shadow: 0 2px 16px rgba(11, 37, 69, 0.45); font-size: 3rem; }
.st-key-hero-plan [data-baseweb="select"] > div { background: #FFFFFF !important; }
.ts-hero-sub { color: #FFFFFF; font-weight: 600; font-size: 1.05rem; text-shadow: 0 1px 10px rgba(11, 37, 69, 0.45); margin: -0.4rem 0 0.6rem; }
.st-key-hero-plan [data-baseweb="select"] > div { min-height: 54px; font-size: 1.05rem;
  box-shadow: 0 10px 26px rgba(11, 37, 69, 0.22); border: 2px solid rgba(255, 255, 255, 0.9) !important; }

/* Frosted-glass dashboard cards */
.ts-glass-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 22px; }
@media (max-width: 900px) { .ts-glass-row { grid-template-columns: 1fr; } }
.ts-glass { background: rgba(255, 255, 255, 0.28); border: 1px solid rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); border-radius: 24px; padding: 16px 16px 18px;
  box-shadow: 0 12px 30px rgba(11, 37, 69, 0.18); display: flex; flex-direction: column; }
.ts-glass .ts-panel { flex: 1; }
.ts-glass h3 { text-align: center; margin: 0 0 10px; font-size: 1.55rem; color: var(--ts-navy); }
.ts-panel { background: #FFFFFF; border-radius: 16px; padding: 12px 14px; min-height: 200px; }
.ts-panel-head { display: flex; flex-wrap: wrap; gap: 2px 10px; justify-content: space-between; align-items: baseline; padding-bottom: 8px;
  border-bottom: 1px solid #E6EEF6; margin-bottom: 6px; }
.ts-panel-head b { color: var(--ts-navy); }
.ts-panel-head span, .ts-sub { color: var(--ts-muted); font-size: 0.82rem; }
.ts-line { display: flex; justify-content: space-between; align-items: center; padding: 7px 0; gap: 10px; }
.ts-line b { color: var(--ts-navy); font-weight: 600; }
.ts-amount { font-weight: 700; color: var(--ts-navy); white-space: nowrap; }
.ts-amount.good { color: #0F9D6B; } .ts-amount.bad { color: #D64545; }
.ts-bar { height: 7px; background: #E6EEF6; border-radius: 999px; overflow: hidden; margin-top: 5px; }
.ts-bar > i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--ts-teal), var(--ts-ocean)); }
.ts-empty { color: var(--ts-muted); font-size: 0.9rem; padding: 18px 4px; text-align: center; }
.ts-empty b { display: block; color: var(--ts-navy); margin-bottom: 4px; }

/* Big homepage tiles */
[class*="st-key-tile-"] { border-radius: 24px; padding: 26px 24px; min-height: 170px;
  border: 1px solid var(--ts-line); box-shadow: var(--ts-shadow); }
.st-key-tile-trip { background: linear-gradient(135deg, #DCEAF7, #C7E3F6); }
.st-key-tile-fin { background: linear-gradient(135deg, #EEF2F7, #E3E9F0); }
[class*="st-key-tile-"] h3 { font-size: 2rem; margin: 0 0 4px; }
.st-key-tile-trip [data-testid="stPageLink"] a { background: linear-gradient(135deg, var(--ts-coral), var(--ts-sun));
  border-radius: 999px; padding: 6px 18px; box-shadow: 0 8px 20px rgba(255, 107, 87, 0.35); }
.st-key-tile-trip [data-testid="stPageLink"] a p { color: #FFFFFF !important; font-weight: 700; }
.ts-soon { display: inline-block; background: #FFFFFF; border: 1px dashed #A9BCD0; color: var(--ts-ink);
  border-radius: 999px; padding: 4px 12px; font-size: 0.85rem; font-weight: 600; }

/* Step tracker */
.ts-steps { display: flex; gap: 10px; flex-wrap: wrap; margin: 4px 0 2px; }
.ts-step { display: flex; align-items: center; gap: 8px; padding: 6px 14px 6px 6px; border-radius: 999px;
  background: #FFFFFF; border: 1px solid var(--ts-line); color: var(--ts-muted); font-weight: 600; font-size: 0.9rem; }
.ts-step i { font-style: normal; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
  background: #E6EEF6; color: var(--ts-muted); font-weight: 700; }
.ts-step.done { color: var(--ts-navy); } .ts-step.done i { background: #CDEFE3; color: #0F9D6B; }
.ts-step.now { color: var(--ts-navy); border-color: #9CC9EA; box-shadow: 0 6px 16px rgba(14, 124, 196, 0.15); }
.ts-step.now i { background: linear-gradient(135deg, var(--ts-coral), var(--ts-sun)); color: #fff; }

.ts-powered { color: var(--ts-muted); font-size: 0.85rem; text-align: center; margin-top: 18px; }
.ts-powered b { color: var(--ts-ink); }
"""


def inject_css():
    """Load the theme on every page (call once per run, before any content)."""
    st.html("<style>" + _CSS.replace("BEACH", BEACH_URL) + "</style>")


def h(text) -> str:
    """Escape any text going into HTML."""
    return escape(str(text), quote=True)


def dollars(amount: float, cents: bool = False) -> str:
    return f"${amount:,.2f}" if cents else f"${amount:,.0f}"


def line(label: str, value: str, sub: str = "", tone: str = "") -> str:
    """One row in a dashboard panel: label (+ small subtitle) on the left, amount on the right."""
    sub_html = f"<div class='ts-sub'>{h(sub)}</div>" if sub else ""
    return (f"<div class='ts-line'><div><b>{h(label)}</b>{sub_html}</div>"
            f"<div class='ts-amount {h(tone)}'>{h(value)}</div></div>")


def goal(label: str, sub: str, pct: float, value: str = "") -> str:
    """A row with a progress bar (pct is 0-100)."""
    pct = max(0.0, min(100.0, pct))
    return (f"<div class='ts-line' style='display:block'><div style='display:flex;justify-content:space-between'>"
            f"<b>{h(label)}</b><span class='ts-amount'>{h(value or f'{pct:.0f}%')}</span></div>"
            f"<div class='ts-sub'>{h(sub)}</div><div class='ts-bar'><i style='width:{pct:.1f}%'></i></div></div>")


def empty(title: str, body: str) -> str:
    return f"<div class='ts-empty'><b>{h(title)}</b>{h(body)}</div>"


def glass(title: str, head: str, head_sub: str, body_html: str) -> str:
    """A frosted card with a white panel inside (the Figma dashboard cards)."""
    return (f"<div class='ts-glass'><h3>{h(title)}</h3><div class='ts-panel'>"
            f"<div class='ts-panel-head'><b>{h(head)}</b><span>{h(head_sub)}</span></div>{body_html}</div></div>")


def steps(current: int, done: set[int]):
    """Trip → Options → Lock in tracker; `current` is 1-3."""
    names = ("Your trip", "Pick options", "Lock it in")
    chips = []
    for n, name in enumerate(names, start=1):
        state = "done" if n in done else "now" if n == current else ""
        mark = "✓" if n in done else str(n)
        chips.append(f"<div class='ts-step {state}'><i>{mark}</i>{h(name)}</div>")
    st.html("<div class='ts-steps'>" + "".join(chips) + "</div>")


def powered_by():
    st.html("<div class='ts-powered'>Live prices from <b>SerpApi</b> (Google Flights &amp; Hotels) · "
            "Budgets tracked with <b>Capital One Nessie</b> · Maps © OpenStreetMap, CARTO</div>")
