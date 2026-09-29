import urllib.request
import json
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="FL VIP +EV Command Center", page_icon="🎯", layout="wide")

DEFAULT_API_KEY = "aa80562ae5fb97cfd71d78bc63a0cb1e"
REGIONS = "us,us_offshore"

MAIN_MARKETS = "h2h,spreads,totals"
PROP_SPORTS = ["baseball_mlb", "americanfootball_nfl", "basketball_nba"]
PROP_MARKETS = "pitcher_strikeouts,batter_total_bases,batter_hits,player_pass_yds,player_pass_tds,player_rush_yds,player_rec_yds,player_points,player_rebounds,player_assists"

FL_PLACEABLE_BOOKS = [
    "hard rock", "hardrock",
    "draftkings predictions", "dk predictions", "predictions", "pick6", "draftkings", "draft king",
    "bovada", "fliff", "rebet", "lucky rebel", "prizepicks", "novig"
]

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
    if ev <= 0:
        return 0.0, 0.0, 0.0, 0.0
    full_kelly = ev / b
    quarter_kelly = max(0.005, min(full_kelly * 0.25, 0.05))
    dollar_wager = round(max(2.50, bankroll * quarter_kelly), 2)
    units = round(dollar_wager / base_unit, 2)
    net_profit = round(dollar_wager * b, 2)
    total_payout = round(dollar_wager + net_profit, 2)
    return units, dollar_wager, net_profit, total_payout

def fetch_json_with_status(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            remaining = response.headers.get("x-requests-remaining", "Unknown")
            return data, None, remaining
    except urllib.error.HTTPError as e:
        return None, f"HTTP Error {e.code}: {e.reason}", "0"
    except Exception as e:
        return None, str(e), "0"

st.title("🎯 Florida VIP +EV Scanner & Unit Command")

st.sidebar.header("⚙️ Controls")
api_key_input = st.sidebar.text_input("API Key", value=DEFAULT_API_KEY)
bankroll_input = st.sidebar.number_input("Total Bankroll ($)", value=500.00, step=25.00)
base_unit_input = st.sidebar.number_input("Base Unit Size ($)", value=5.00, step=1.00)
min_ev_input = st.sidebar.slider("Minimum Edge (+EV %)", min_value=1, max_value=15, value=5) / 100.0

include_props = st.sidebar.checkbox("Include Player Props Scanning", value=True)

if st.button("🚀 Run Live Market Scan", type="primary", use_container_width=True):
    clean_api_key = api_key_input.strip().lower()
    
    with st.spinner("Fetching live market data across Florida books..."):
        all_opportunities = []
        last_remaining = "Unknown"

        # 1. Main Lines Scan (Bulk /upcoming)
        main_url = f"https://api.the-odds-api.com/v4/sports/upcoming/odds/?apiKey={clean_api_key}&regions={REGIONS}&markets={MAIN_MARKETS}&oddsFormat=american"
        games, err, remaining = fetch_json_with_status(main_url)

        if err:
            st.error(f"❌ Main Market API Error: {err}")
        else:
            last_remaining = remaining
            if games and isinstance(games, list):
                for game in games:
                    home_team = game.get("home_team", "")
                    away_team = game.get("away_team", "")
                    sport_title = game.get("sport_title", "Unknown Sport")
                    if not home_team or not away_team:
                        continue

                    matchup = f"{away_team} @ {home_team}"
                    clean_home = normalize_text(home_team)
                    clean_away = normalize_text(away_team)

                    bookmakers = game.get("bookmakers", [])
                    if len(bookmakers) < 2:
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
                                point = outcome.get("point", None)
                                price = outcome.get("price")
                                if price is None:
                                    continue

                                clean_raw = normalize_text(raw_name)
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

                                line_key = str(abs(float(point))) if m_key == "spreads" else (str(point) if m_key == "totals" else "main")
                                if line_key not in market_data[m_key]:
                                    market_data[m_key][line_key] = {}
                                if side_label not in market_data[m_key][line_key]:
                                    market_data[m_key][line_key][side_label] = {}

                                market_data[m_key][line_key][side_label][b_name] = price

                    for m_key, lines in market_data.items():
                        for line_key, sides in lines.items():
                            if len(sides) < 2:
                                continue
                            side_avg_implied = {}
                            valid_market = True
                            for side_name, books_dict in sides.items():
                                if len(books_dict) < 2:
                                    valid_market = False
                                    break
                                side_avg_implied[side_name] = sum(american_to_implied(p) for p in books_dict.values()) / len(books_dict)
                            if not valid_market:
                                continue
                            total_hold = sum(side_avg_implied.values())
                            if total_hold <= 0:
                                continue
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
                                    selection_disp = f"{mkt_display_name if 'mkt_display_name' in locals() else m_key.upper()}: {side_name}" if line_key == "main" else f"{m_key.upper()}: {side_name} ({line_key})"
                                    all_opportunities.append({
                                        "League": sport_title,
                                        "Matchup": matchup,
                                        "Selection": selection_disp,
                                        "Platform": best_b,
                                        "Odds": f"{best_o:+d}",
                                        "Stake": f"${wager:.2f} ({u}u)",
                                        "Net Profit": f"${net_profit:.2f}",
                                        "Total Payout": f"${payout:.2f}",
                                        "Fair Win %": f"{fair_p * 100:.1f}%",
                                        "Edge (+EV)": f"{ev * 100:+.2f}%",
                                        "ev_raw": ev
                                    })

        # 2. Player Props Scan (Event-Level)
        if include_props:
            for s_key in PROP_SPORTS:
                events_url = f"https://api.the-odds-api.com/v4/sports/{s_key}/events/?apiKey={clean_api_key}"
                events, p_err, _ = fetch_json_with_status(events_url)
                if p_err or not events or not isinstance(events, list):
                    continue

                for evt in events[:5]:
                    evt_id = evt.get("id")
                    home_team = evt.get("home_team", "")
                    away_team = evt.get("away_team", "")
                    matchup = f"{away_team} @ {home_team}"

                    prop_url = f"https://api.the-odds-api.com/v4/sports/{s_key}/events/{evt_id}/odds/?apiKey={clean_api_key}&regions={REGIONS}&markets={PROP_MARKETS}&oddsFormat=american"
                    p_data, p_odds_err, p_rem = fetch_json_with_status(prop_url)
                    if p_rem != "0":
                        last_remaining = p_rem
                    if p_odds_err or not p_data or not isinstance(p_data, dict):
                        continue

                    bookmakers = p_data.get("bookmakers", [])
                    if len(bookmakers) < 2:
                        continue

                    prop_market_data = {}
                    for book in bookmakers:
                        b_name = book["title"]
                        for mkt in book.get("markets", []):
                            m_key = mkt["key"]
                            if m_key not in prop_market_data:
                                prop_market_data[m_key] = {}

                            for outcome in mkt.get("outcomes", []):
                                raw_name = outcome.get("name", "")
                                player_desc = outcome.get("description", "")
                                point = outcome.get("point", None)
                                price = outcome.get("price")
                                if price is None or not player_desc:
                                    continue

                                point_str = f" {point}" if point is not None else ""
                                line_key = f"{player_desc} ({point_str.strip()})"
                                side_label = raw_name.upper()

                                if line_key not in prop_market_data[m_key]:
                                    prop_market_data[m_key][line_key] = {}
                                if side_label not in prop_market_data[m_key][line_key]:
                                    prop_market_data[m_key][line_key][side_label] = {}

                                prop_market_data[m_key][line_key][side_label][b_name] = price

                    for m_key, lines in prop_market_data.items():
                        for line_key, sides in lines.items():
                            if len(sides) < 2:
                                continue
                            side_avg_implied = {}
                            valid_market = True
                            for side_name, books_dict in sides.items():
                                if len(books_dict) < 2:
                                    valid_market = False
                                    break
                                side_avg_implied[side_name] = sum(american_to_implied(p) for p in books_dict.values()) / len(books_dict)
                            if not valid_market:
                                continue
                            total_hold = sum(side_avg_implied.values())
                            if total_hold <= 0:
                                continue
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
                                    mkt_display_name = m_key.replace("_", " ").title()
                                    selection_disp = f"{mkt_display_name}: {line_key} - {side_name}"
                                    all_opportunities.append({
                                        "League": s_key.replace("_", " ").upper(),
                                        "Matchup": matchup,
                                        "Selection": selection_disp,
                                        "Platform": best_b,
                                        "Odds": f"{best_o:+d}",
                                        "Stake": f"${wager:.2f} ({u}u)",
                                        "Net Profit": f"${net_profit:.2f}",
                                        "Total Payout": f"${payout:.2f}",
                                        "Fair Win %": f"{fair_p * 100:.1f}%",
                                        "Edge (+EV)": f"{ev * 100:+.2f}%",
                                        "ev_raw": ev
                                    })

        st.info(f"API Credits Remaining: **{last_remaining}**")

        if all_opportunities:
            df = pd.DataFrame(all_opportunities).sort_values(by="ev_raw", ascending=False).drop(columns=["ev_raw"])
            st.success(f"Found {len(df)} +EV opportunities across Main Lines & Player Props:")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info(f"No active lines found with Edge ≥ {min_ev_input*100:.1f}%.")
            
