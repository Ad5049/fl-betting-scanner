import urllib.request
import json
import re
import pandas as pd
import streamlit as st

# ==========================================
# PAGE CONFIGURATION & HEADERS
# ==========================================
st.set_page_config(page_title="FL VIP +EV Command Center", page_icon="🎯", layout="wide")

API_KEY = "714895ce62ecdfdc29c3ce0e9c0c7580"
REGIONS = "us,us_offshore"
MARKETS = "h2h,spreads,totals"

# Florida-accessible platforms (including DK Predictions)
FL_PLACEABLE_BOOKS = [
    "hard rock", "hardrock",
    "draftkings predictions", "dk predictions", "predictions", "pick6", "draftkings", "draft king",
    "bovada", 
    "fliff", 
    "rebet", 
    "lucky rebel", "luckyrebel",
    "prizepicks", "prize picks",
    "novig"
]

# ==========================================
# HELPER MATH & PARSING FUNCTIONS
# ==========================================
def american_to_implied(odds):
    return 100.0 / (odds + 100.0) if odds > 0 else abs(odds) / (abs(odds) + 100.0)

def american_to_decimal(odds):
    return (odds / 100.0) + 1.0 if odds > 0 else (100.0 / abs(odds)) + 1.0

def normalize_text(text):
    return re.sub(r'[^a-z0-9]', '', str(text).lower())

def is_fl_book(book_name):
    clean_book = normalize_text(book_name)
    for fl_b in FL_PLACEABLE_BOOKS:
        clean_fl = normalize_text(fl_b)
        if clean_fl in clean_book or clean_book in clean_fl:
            return True
    return False

def calculate_quarter_kelly(ev, decimal_odds, bankroll, base_unit):
    b = decimal_odds - 1.0
    full_kelly = ev / b
    # Quarter-Kelly fraction, capped at 5% max bankroll allocation per bet
    quarter_kelly = max(0.005, min(full_kelly * 0.25, 0.05)) 
    
    dollar_wager = round(max(2.50, bankroll * quarter_kelly), 2)  # Enforce $2.50 (0.5u) minimum
    units = round(dollar_wager / base_unit, 2)
    net_profit = round(dollar_wager * b, 2)
    total_payout = round(dollar_wager + net_profit, 2)
    
    return units, dollar_wager, net_profit, total_payout

def fetch_json(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None

# ==========================================
# STREAMLIT UI & CONTROL PANEL
# ==========================================
st.title("🎯 Florida VIP +EV Scanner & Unit Command")
st.caption("Universal N-Way Devigging across all active sports endpoints for Florida platforms.")

st.sidebar.header("⚙️ Bankroll Controls")
bankroll_input = st.sidebar.number_input("Total Bankroll ($)", value=500.00, step=25.00)
base_unit_input = st.sidebar.number_input("Base Unit Size ($)", value=5.00, step=1.00)
min_ev_input = st.sidebar.slider("Minimum Edge (+EV %)", min_value=1, max_value=15, value=5) / 100.0
min_books_input = st.sidebar.number_input("Min Consensus Books Required", value=2, min_value=2, max_value=10)

if st.button("🚀 Run Live Market Scan", type="primary", use_container_width=True):
    with st.spinner("Fetching active leagues and executing N-way devigging..."):
        sports_data = fetch_json(f"https://api.the-odds-api.com/v4/sports/?apiKey={API_KEY}")
        
        if not sports_data or not isinstance(sports_data, list):
            st.error("Failed to connect to odds API. Check network connection or API limits.")
        else:
            active_sports = [s["key"] for s in sports_data if s.get("active", False)]
            all_opportunities = []

            for sport_key in active_sports:
                url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={API_KEY}&regions={REGIONS}&markets={MARKETS}&oddsFormat=american"
                games = fetch_json(url)
                if not games or not isinstance(games, list):
                    continue
                    
                for game in games:
                    home_team = game.get("home_team", "")
                    away_team = game.get("away_team", "")
                    if not home_team or not away_team:
                        continue
                        
                    matchup = f"{away_team} @ {home_team}"
                    clean_home = normalize_text(home_team)
                    clean_away = normalize_text(away_team)
                    
                    bookmakers = game.get("bookmakers", [])
                    if len(bookmakers) < min_books_input:
                        continue
                        
                    market_data = {}

                    for book in bookmakers:
                        b_name = book["title"]
                        for mkt in book.get("markets", []):
                            m_key = mkt["key"]
                            if m_key not in market_data:
                                market_data[m_key] = {}
                                
                            for outcome in mkt.get("outcomes", []):
                                raw_name = outcome.get("name", "")
                                point = outcome.get("point", 0.0)
                                price = outcome.get("price")
                                if price is None:
                                    continue
                                    
                                clean_raw = normalize_text(raw_name)
                                
                                # Role and side normalization
                                if clean_raw in clean_home or clean_home in clean_raw or clean_raw == "home":
                                    side_label = f"HOME: {home_team}"
                                elif clean_raw in clean_away or clean_away in clean_raw or clean_raw == "away":
                                    side_label = f"AWAY: {away_team}"
                                elif "draw" in clean_raw or clean_raw == "tie":
                                    side_label = "DRAW"
                                elif "over" in clean_raw:
                                    side_label = "OVER"
                                elif "under" in clean_raw:
                                    side_label = "UNDER"
                                else:
                                    side_label = raw_name

                                # FIX: Group opposing spreads (-3.5 & +3.5) together under abs(point)
                                if m_key == "spreads":
                                    line_key = str(abs(float(point)))
                                elif m_key == "totals":
                                    line_key = str(point)
                                else:
                                    line_key = "main"
                                
                                if line_key not in market_data[m_key]:
                                    market_data[m_key][line_key] = {}
                                if side_label not in market_data[m_key][line_key]:
                                    market_data[m_key][line_key][side_label] = {}
                                    
                                market_data[m_key][line_key][side_label][b_name] = price

                    # Universal N-Way Devigging Engine
                    for m_key, lines in market_data.items():
                        for line_key, sides in lines.items():
                            if len(sides) < 2:
                                continue
                                
                            side_avg_implied = {}
                            valid_market = True
                            
                            for side_name, books_dict in sides.items():
                                if len(books_dict) < min_books_input:
                                    valid_market = False
                                    break
                                side_avg_implied[side_name] = sum(american_to_implied(p) for p in books_dict.values()) / len(books_dict)
                                
                            if not valid_market:
                                continue
                                
                            total_hold = sum(side_avg_implied.values())
                            if total_hold <= 0:
                                continue
                                
                            # Multiplicative fair probabilities
                            fair_probs = {side_name: imp / total_hold for side_name, imp in side_avg_implied.items()}

                            for side_name, books_dict in sides.items():
                                fair_p = fair_probs[side_name]
                                flo = {b: p for b, p in books_dict.items() if is_fl_book(b)}
                                if not flo:
                                    continue
                                    
                                best_b = max(flo, key=flo.get)
                                best_o = flo[best_b]
                                best_dec = american_to_decimal(best_o)
                                
                                b = best_dec - 1.0
                                ev = (fair_p * b) - (1.0 - fair_p)
                                
                                if ev >= min_ev_input:
                                    u, wager, net_profit, payout = calculate_quarter_kelly(ev, best_dec, bankroll_input, base_unit_input)
                                    disp = f"{m_key.upper()}: {side_name}" if line_key == "main" else f"{m_key.upper()}: {side_name} ({line_key})"
                                    
                                    all_opportunities.append({
                                        "League": sport_key.replace("_", " ").title(),
                                        "Matchup": matchup,
                                        "Selection": disp,
                                        "Platform": best_b,
                                        "Odds": f"{best_o:+d}",
                                        "Stake": f"${wager:.2f} ({u}u)",
                                        "Net Profit": f"${net_profit:.2f}",
                                        "Total Payout": f"${payout:.2f}",
                                        "Fair Win %": f"{fair_p * 100:.1f}%",
                                        "Edge (+EV)": f"{ev * 100:+.2f}%",
                                        "ev_raw": ev
                                    })

            if all_opportunities:
                df = pd.DataFrame(all_opportunities).sort_values(by="ev_raw", ascending=False).drop(columns=["ev_raw"])
                st.success(f"Found {len(df)} Actionable +EV Execution Orders!")
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No plays currently meet your minimum edge threshold across active markets.")
