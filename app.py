import urllib.request
import json
import re
import os
from datetime import datetime, timezone
import pandas as pd
import streamlit as st

st.set_page_config(page_title="FL VIP +EV Command Center", page_icon="🎯", layout="wide")

DEFAULT_API_KEY = "aa80562ae5fb97cfd71d78bc63a0cb1e"
REGIONS = "us,us2"
BETS_FILE = "bets.json"
SWEEP_FILE = "sweeps.json"

MAIN_MARKETS = "h2h,spreads,totals"
PROP_SPORTS = ["baseball_mlb", "americanfootball_nfl", "basketball_nba", "icehockey_nhl"]
PROP_MARKETS = "pitcher_strikeouts,batter_total_bases,batter_hits,player_pass_yds,player_pass_tds,player_rush_yds,player_rec_yds,player_points,player_rebounds,player_assists"

FL_PLACEABLE_BOOKS = [
    "hard rock", "hardrock",
    "draftkings predictions", "dk predictions", "predictions", "pick6", "draftkings", "draft king",
    "bovada", "fliff", "rebet", "lucky rebel", "prizepicks", "novig"
]

def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return [] if "bets" in filepath else {"total_withdrawn": 0.0}
    return [] if "bets" in filepath else {"total_withdrawn": 0.0}

def save_json(data, filepath):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

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

def auto_settle_main_lines(api_key, bets):
    pending = [b for b in bets if b.get("status") == "PENDING"]
    if not pending:
        return bets, False

    updated = False
    sports_to_check = list(set([b.get("sport_key", "baseball_mlb") for b in pending if b.get("sport_key")]))
    if not sports_to_check:
        sports_to_check = ["basketball_euroleague", "baseball_mlb", "americanfootball_nfl", "basketball_nba", "icehockey_nhl"]

    for sport in sports_to_check:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/scores/?apiKey={api_key}&daysFrom=3"
        scores, err, _ = fetch_json_with_status(url)
        if err or not scores or not isinstance(scores, list):
            continue

        for evt in scores:
            if not evt.get("completed"):
                continue
            home_team = evt.get("home_team", "")
            away_team = evt.get("away_team", "")
            score_list = evt.get("scores")
            if not score_list or len(score_list) < 2:
                continue

            scores_dict = {}
            for s in score_list:
                try:
                    scores_dict[normalize_text(s["name"])] = float(s["score"])
                except ValueError:
                    pass

            for b in pending:
                if b.get("status") != "PENDING":
                    continue

                clean_home = normalize_text(home_team)
                clean_away = normalize_text(away_team)
                b_matchup = normalize_text(b.get("matchup", ""))

                if clean_home in b_matchup and clean_away in b_matchup:
                    home_score = None
                    away_score = None
                    for k, v in scores_dict.items():
                        if clean_home in k or k in clean_home:
                            home_score = v
                        elif clean_away in k or k in clean_away:
                            away_score = v

                    if home_score is not None and away_score is not None:
                        sel = str(b.get("selection", "")).upper()
                        if "HOME" in sel or home_team.upper() in sel:
                            b["status"] = "WON" if home_score > away_score else ("LOST" if home_score < away_score else "PUSH")
                            updated = True
                        elif "AWAY" in sel or away_team.upper() in sel:
                            b["status"] = "WON" if away_score > home_score else ("LOST" if away_score < home_score else "PUSH")
                            updated = True

    return bets, updated

def process_bookmakers(bookmakers, clean_home, clean_away, home_team, away_team, is_prop=False):
    market_data = {}
    for book in bookmakers:
        b_name = book.get("title", "")
        for mkt in book.get("markets", []):
            m_key = mkt.get("key", "")
            if m_key not in market_data:
                market_data[m_key] = {}

            for outcome in mkt.get("outcomes", []):
                raw_name = outcome.get("name", "")
                player_desc = outcome.get("description", "")
                point = outcome.get("point", None)
                price = outcome.get("price")
                if price is None:
                    continue

                if is_prop:
                    if not player_desc:
                        continue
                    point_str = f" {point}" if point is not None else ""
                    line_key = f"{player_desc} ({point_str.strip()})"
                    side_label = raw_name.upper()
                else:
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
    return market_data

def evaluate_markets(market_data, sport_title, matchup, sport_key, max_odds_cap, min_ev_val, bankroll_val, unit_val, is_prop=False):
    opps = []
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

                if best_o > max_odds_cap:
                    continue

                best_dec = american_to_decimal(best_o)
                b = best_dec - 1.0
                ev = (fair_p * b) - (1.0 - fair_p)

                if ev >= min_ev_val:
                    u, wager, net_profit, payout = calculate_quarter_kelly(ev, best_dec, 500.00, unit_val)
                    if is_prop:
                        mkt_disp = m_key.replace("_", " ").title()
                        selection_disp = f"{mkt_disp}: {line_key} - {side_name}"
                    else:
                        selection_disp = f"{m_key.upper()}: {side_name}" if line_key == "main" else f"{m_key.upper()}: {side_name} ({line_key})"
                    
                    opps.append({
                        "League": sport_title,
                        "Matchup": matchup,
                        "Selection": selection_disp,
                        "Platform": best_b,
                        "Odds": best_o,
                        "Odds Disp": f"{best_o:+d} ({best_dec:.2f}x)",
                        "Stake": wager,
                        "Stake Disp": f"${wager:.2f} ({u}u)",
                        "Net Profit": net_profit,
                        "Edge (+EV)": f"{ev * 100:+.2f}%",
                        "sport_key": sport_key,
                        "ev_raw": ev
                    })
    return opps

st.title("🎯 Florida VIP +EV Scanner & Bet Command")

if "tracked_bets" not in st.session_state:
    st.session_state.tracked_bets = load_json(BETS_FILE)
if "sweep_data" not in st.session_state:
    st.session_state.sweep_data = load_json(SWEEP_FILE)

st.sidebar.header("⚙️ Controls")
api_key_input = st.sidebar.text_input("API Key", value=DEFAULT_API_KEY)
bankroll_input = st.sidebar.number_input("Operational Capital Base ($)", value=500.00, step=25.00)
base_unit_input = st.sidebar.number_input("Base Unit Size ($)", value=5.00, step=1.00)
min_ev_input = st.sidebar.slider("Minimum Edge (+EV %)", min_value=1, max_value=15, value=5) / 100.0
max_odds_input = st.sidebar.number_input("Max American Odds Cap (+400)", value=400, step=50)

include_props = st.sidebar.checkbox("Include Player Props Scanning", value=True)
exclude_live = st.sidebar.checkbox("Exclude Live / Started Games", value=True)

tab1, tab2 = st.tabs(["🎯 Live +EV Scanner", "📊 Bet Tracker & Bankroll"])

with tab1:
    if st.button("🚀 Run Live Market Scan", type="primary", use_container_width=True):
        clean_api_key = api_key_input.strip().lower()
        now_utc = datetime.now(timezone.utc)

        with st.spinner("Fetching market data across Florida books..."):
            all_opportunities = []
            last_remaining = "Unknown"

            main_url = f"https://api.the-odds-api.com/v4/sports/upcoming/odds/?apiKey={clean_api_key}&regions={REGIONS}&markets={MAIN_MARKETS}&oddsFormat=american"
            games, err, remaining = fetch_json_with_status(main_url)

            if err:
                st.error(f"❌ Main Market API Error: {err}")
            else:
                last_remaining = remaining
                if games and isinstance(games, list):
                    for game in games:
                        commence_str = game.get("commence_time")
                        if exclude_live and commence_str:
                            try:
                                commence_dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
                                if commence_dt <= now_utc:
                                    continue
                            except Exception:
                                pass

                        home_team = game.get("home_team", "")
                        away_team = game.get("away_team", "")
                        sport_title = game.get("sport_title", "Unknown Sport")
                        sport_key = game.get("sport_key", "")
                        if not home_team or not away_team:
                            continue

                        matchup = f"{away_team} @ {home_team}"
                        clean_home = normalize_text(home_team)
                        clean_away = normalize_text(away_team)

                        bookmakers = game.get("bookmakers", [])
                        if len(bookmakers) < 2:
                            continue

                        m_data = process_bookmakers(bookmakers, clean_home, clean_away, home_team, away_team, is_prop=False)
                        m_opps = evaluate_markets(m_data, sport_title, matchup, sport_key, max_odds_input, min_ev_input, bankroll_input, base_unit_input, is_prop=False)
                        all_opportunities.extend(m_opps)

            if include_props:
                for s_key in PROP_SPORTS:
                    events_url = f"https://api.the-odds-api.com/v4/sports/{s_key}/events/?apiKey={clean_api_key}"
                    events, p_err, _ = fetch_json_with_status(events_url)
                    if p_err or not events or not isinstance(events, list):
                        continue

                    for evt in events[:5]:
                        commence_str = evt.get("commence_time")
                        if exclude_live and commence_str:
                            try:
                                commence_dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
                                if commence_dt <= now_utc:
                                    continue
                            except Exception:
                                pass

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

                        p_data_dict = process_bookmakers(bookmakers, normalize_text(home_team), normalize_text(away_team), home_team, away_team, is_prop=True)
                        p_opps = evaluate_markets(p_data_dict, s_key.replace("_", " ").upper(), matchup, s_key, max_odds_input, min_ev_input, bankroll_input, base_unit_input, is_prop=True)
                        all_opportunities.extend(p_opps)

            st.session_state.scan_results = all_opportunities
            st.session_state.last_remaining = last_remaining

    if "scan_results" in st.session_state and st.session_state.scan_results:
        st.info(f"API Credits Remaining: **{st.session_state.get('last_remaining', 'Unknown')}**")
        df_scan = pd.DataFrame(st.session_state.scan_results).sort_values(by="ev_raw", ascending=False)
        disp_df = df_scan[["League", "Matchup", "Selection", "Platform", "Odds Disp", "Stake Disp", "Edge (+EV)"]].rename(columns={"Odds Disp": "Odds (American / Decimal)", "Stake Disp": "Stake"})
        
        st.success(f"Found {len(df_scan)} +EV opportunities:")
        st.dataframe(disp_df, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("📌 Log Wager to App Tracker")
        records = df_scan.to_dict('records')
        options = [f"{i}: {r.get('Selection')} ({r.get('Platform')} {r.get('Odds Disp')})" for i, r in enumerate(records)]
        selected_opt = st.selectbox("Select Play Placed:", options)
        
        if selected_opt:
            idx = int(selected_opt.split(":")[0])
            item = records[idx]
            actual_stake = st.number_input("Actual Dollar Stake ($)", value=float(item.get('Stake', 2.50)), step=0.50)
            actual_odds = st.number_input("Actual Placed Odds (American)", value=int(item.get('Odds', 100)), step=10)

            if st.button("✅ Confirm & Log Wager"):
                dec = american_to_decimal(actual_odds)
                potential_profit = round(actual_stake * (dec - 1.0), 2)
                new_bet = {
                    "id": len(st.session_state.tracked_bets) + 1,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "matchup": item.get("Matchup", ""),
                    "selection": item.get("Selection", ""),
                    "platform": item.get("Platform", ""),
                    "odds": actual_odds,
                    "stake": actual_stake,
                    "potential_profit": potential_profit,
                    "status": "PENDING",
                    "sport_key": item.get("sport_key", "")
                }
                st.session_state.tracked_bets.append(new_bet)
                save_json(st.session_state.tracked_bets, BETS_FILE)
                st.success(f"Logged wager #{new_bet['id']} ({item.get('Selection')})!")
                st.rerun()

with tab2:
    bets = st.session_state.tracked_bets
    sweep_data = st.session_state.sweep_data
    
    weekly_profit = sum([b.get('potential_profit', 0.0) if b.get('status') == 'WON' else (-b.get('stake', 0.0) if b.get('status') == 'LOST' else 0.0) for b in bets])
    pending_staked = sum([b.get('stake', 0.0) for b in bets if b.get('status') == 'PENDING'])
    current_bankroll = bankroll_input + weekly_profit
    active_liquid = current_bankroll - pending_staked
    all_time_withdrawn = sweep_data.get("total_withdrawn", 0.0)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Weekly Bankroll", f"${current_bankroll:.2f}")
    col2.metric("Weekly Profit", f"${weekly_profit:+.2f}")
    col3.metric("Pending Exposure", f"${pending_staked:.2f}")
    col4.metric("Available Capital", f"${active_liquid:.2f}")
    col5.metric("Total Bank Withdrawn", f"${all_time_withdrawn:.2f}")

    st.markdown("---")
    
    col_a, col_b = st.columns([1, 1])
    with col_a:
        if st.button("🔄 Auto-Settle Main Line Bets", type="primary", use_container_width=True):
            clean_api_key = api_key_input.strip().lower()
            updated_bets, changed = auto_settle_main_lines(clean_api_key, bets)
            if changed:
                st.session_state.tracked_bets = updated_bets
                save_json(updated_bets, BETS_FILE)
                st.success("Auto-settlement completed!")
                st.rerun()
            else:
                st.info("No main line pending bets match completed games in score feed.")
     with col_b:
        if st.button("🧹 Sunday Profit Sweep & Reset Baseline", use_container_width=True):
            if weekly_profit <= 0 and not any(b.get('status') != 'PENDING' for b in bets):
                st.warning("No profits to sweep.")
            else:
                sweep_data["total_withdrawn"] = round(sweep_data.get("total_withdrawn", 0.0) + max(0.0, weekly_profit), 2)
                st.session_state.sweep_data = sweep_data
                save_json(sweep_data, SWEEP_FILE)

                st.session_state.tracked_bets = [b for b in bets if b.get('status') == 'PENDING']
                save_json(st.session_state.tracked_bets, BETS_FILE)

                st.success("Swept weekly profit! Ledger reset to $500.00.")
                st.rerun()
                
