
import os
import unicodedataimport os
import unicodedata
import requests
from flask import Flask, request
from datetime import datetime, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("Faltou TELEGRAM_TOKEN")

if not API_FOOTBALL_KEY:
    raise RuntimeError("Faltou API_FOOTBALL_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_FOOTBALL_KEY
}

session = requests.Session()
session.headers.update(HEADERS)

# =========================================================
# CONFIG ELITE 15.0
# =========================================================

ALLOWED_LEAGUES = {
    2,    # UEFA Champions League
    3,    # UEFA Europa League
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    94,   # Primeira Liga
    88,   # Eredivisie
    144,  # Belgium Pro League
    203,  # Super Lig
    207,  # Switzerland Super League
    218,  # Austria Bundesliga
    119,  # Denmark Superliga
    179,  # Scotland Premiership
    71,   # Brazil Serie A
    128,  # Argentina Liga Profesional
    253,  # MLS
    13,   # Libertadores
    11,   # Sul-Americana
    307   # Saudi Pro League
}

LEAGUE_GOAL_PROFILE = {
    2: 1.08,
    3: 1.03,
    39: 1.10,
    140: 0.98,
    135: 1.02,
    78: 1.12,
    61: 1.03,
    94: 1.03,
    88: 1.18,
    144: 1.07,
    203: 1.08,
    207: 1.05,
    218: 1.07,
    119: 1.04,
    179: 1.02,
    71: 1.04,
    128: 0.99,
    253: 1.06,
    13: 0.96,
    11: 0.95,
    307: 1.10
}

LEAGUE_CORNER_PROFILE = {
    2: 1.05,
    3: 1.03,
    39: 1.10,
    140: 1.08,
    135: 1.03,
    78: 1.08,
    61: 1.01,
    94: 1.00,
    88: 1.03,
    144: 1.04,
    203: 1.06,
    207: 1.02,
    218: 1.03,
    119: 1.02,
    179: 1.01,
    71: 1.03,
    128: 0.98,
    253: 1.04,
    13: 1.01,
    11: 1.00,
    307: 1.05
}

MIN_GOAL_PROB = 65
MIN_CORNER_PROB = 63
MIN_STRONG_PROB = 69
MIN_VALUE_PROB = 66
MIN_VALUE_EDGE = 0.08   # 8%
MAX_PREDICTION_CALLS = 20
MAX_VALUE_FIXTURES = 20

predictions_cache = {}
odds_cache = {}
matches_cache = {}

# =========================================================
# HELPERS
# =========================================================

def api_get(path, params=None):
    url = f"{BASE_URL}{path}"
    r = session.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def send(chat_id, text):
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30
    )

def set_webhook():
    if not PUBLIC_URL:
        return

    requests.post(
        f"{TELEGRAM_API}/setWebhook",
        json={"url": f"{PUBLIC_URL}/webhook"},
        timeout=30
    )

def fmt_prob(v):
    return int(round(v))

def fmt_odd(v):
    return f"{v:.2f}"

def confidence(prob):
    p = fmt_prob(prob)

    if p >= 75:
        return "MUITO FORTE"
    if p >= 70:
        return "BOA"
    if p >= 65:
        return "ACEITÁVEL"
    return "FRACA"

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def normalize_text(text):
    text = (text or "").lower().strip()

    text = text.replace("ı", "i")
    text = text.replace("ş", "s")
    text = text.replace("ğ", "g")
    text = text.replace("ü", "u")
    text = text.replace("ö", "o")
    text = text.replace("ç", "c")

    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")

    for ch in [".", ",", "-", "/", "(", ")", "'", '"', ":", ";"]:
        text = text.replace(ch, " ")

    remove_words = {"sk", "fk", "fc", "cf", "ac", "sc", "cd", "ud", "bk", "jk"}
    words = [w for w in text.split() if w not in remove_words]
    text = " ".join(words)

    while "  " in text:
        text = text.replace("  ", " ")

    return text.strip()

def fair_odd_from_prob(prob):
    p = max(1.0, float(prob))
    return 100.0 / p

def value_edge(prob, odd):
    fair = fair_odd_from_prob(prob)
    return (odd / fair) - 1.0

def edge_label(edge):
    if edge >= 0.20:
        return "VALUE ALTO"
    if edge >= 0.12:
        return "VALUE BOM"
    if edge >= 0.08:
        return "VALUE LEVE"
    return "SEM VALUE"

# =========================================================
# BUSCAR JOGOS
# =========================================================

def get_matches_by_date(date_str):
    if date_str in matches_cache:
        return matches_cache[date_str]

    data = api_get("/fixtures", {"date": date_str})
    matches = []

    for m in data.get("response", []):
        league_id = m.get("league", {}).get("id")
        status = (m.get("fixture", {}).get("status", {}).get("short") or "").upper()

        if league_id not in ALLOWED_LEAGUES:
            continue

        if status not in ("NS", "TBD"):
            continue

        matches.append(m)

    matches_cache[date_str] = matches
    return matches

def get_matches_today():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return get_matches_by_date(today)

def get_analysis_pool():
    base_date = datetime.utcnow().date()
    pool = []
    used = set()

    for delta in (-1, 0, 1, 2):
        date_str = (base_date + timedelta(days=delta)).strftime("%Y-%m-%d")
        for m in get_matches_by_date(date_str):
            fixture_id = m.get("fixture", {}).get("id")
            if fixture_id in used:
                continue
            used.add(fixture_id)
            pool.append(m)

    return pool

# =========================================================
# MATCH INFO
# =========================================================

def get_match_info(match):
    fixture = match.get("fixture", {})
    league = match.get("league", {})
    teams = match.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})

    return {
        "fixture_id": fixture.get("id"),
        "league_id": league.get("id"),
        "league_name": league.get("name", ""),
        "home_name": home.get("name", "Casa"),
        "away_name": away.get("name", "Fora"),
        "date": fixture.get("date", "")
    }

# =========================================================
# SCORE BASE
# =========================================================

def base_goal_score(info):
    score = 63.0
    league_id = info["league_id"]
    text = f"{info['home_name']} {info['away_name']}".lower()

    score *= LEAGUE_GOAL_PROFILE.get(league_id, 1.00)

    attacking_terms = [
        "ajax", "psv", "feyenoord", "bayern", "leverkusen",
        "atalanta", "sporting", "benfica", "porto",
        "manchester city", "arsenal", "liverpool",
        "real madrid", "barcelona", "dortmund",
        "al hilal", "al nassr", "al ittihad"
    ]

    if any(term in text for term in attacking_terms):
        score += 2.5

    derby_terms = [
        "milan", "inter", "roma", "porto", "benfica",
        "galatasaray", "fenerbahce", "celtic", "rangers",
        "sevilla", "betis"
    ]

    if any(term in text for term in derby_terms):
        score -= 1.5

    return clamp(score, 58, 78)

def base_corner_score(info):
    score = 60.0
    league_id = info["league_id"]
    text = f"{info['home_name']} {info['away_name']}".lower()

    score *= LEAGUE_CORNER_PROFILE.get(league_id, 1.00)

    pressing_terms = [
        "liverpool", "arsenal", "atalanta", "leverkusen",
        "ajax", "psv", "feyenoord", "roma", "porto",
        "benfica", "real madrid", "barcelona",
        "al hilal", "al nassr", "al ittihad"
    ]

    if any(term in text for term in pressing_terms):
        score += 3.0

    return clamp(score, 56, 77)

# =========================================================
# PREDICTIONS
# =========================================================

def get_prediction(fixture_id):
    if fixture_id in predictions_cache:
        return predictions_cache[fixture_id]

    try:
        data = api_get("/predictions", {"fixture": fixture_id})
        response = data.get("response") or []

        if not response:
            predictions_cache[fixture_id] = None
            return None

        pred = response[0]
        predictions_cache[fixture_id] = pred
        return pred

    except Exception:
        predictions_cache[fixture_id] = None
        return None

def apply_prediction_to_goal_score(base_score, pred):
    score = base_score

    if not pred:
        return clamp(score, 58, 84)

    predictions = pred.get("predictions", {})
    comparison = pred.get("comparison", {})
    goals = predictions.get("goals", {})
    advice = (predictions.get("advice") or "").lower()

    home_goals = goals.get("home")
    away_goals = goals.get("away")

    total_pred = 0.0
    if isinstance(home_goals, (int, float)):
        total_pred += float(home_goals)
    if isinstance(away_goals, (int, float)):
        total_pred += float(away_goals)

    if total_pred >= 3.0:
        score += 5.0
    elif total_pred >= 2.4:
        score += 3.0
    elif total_pred >= 2.0:
        score += 1.5
    else:
        score -= 1.0

    if "over 1.5" in advice:
        score += 4.0
    elif "under 3.5" in advice:
        score += 1.5

    if comparison.get("att", {}).get("home") == "strong":
        score += 1.0
    if comparison.get("att", {}).get("away") == "strong":
        score += 1.0

    return clamp(score, 58, 84)

def apply_prediction_to_corner_score(base_score, pred):
    score = base_score

    if not pred:
        return clamp(score, 56, 82)

    comparison = pred.get("comparison", {})
    predictions = pred.get("predictions", {})
    advice = (predictions.get("advice") or "").lower()

    if comparison.get("att", {}).get("home") == "strong":
        score += 1.5
    if comparison.get("att", {}).get("away") == "strong":
        score += 1.5
    if comparison.get("h2h", {}).get("home") == "strong":
        score += 0.5
    if comparison.get("h2h", {}).get("away") == "strong":
        score += 0.5
    if "over 2.5" in advice or "over 1.5" in advice:
        score += 1.5

    return clamp(score, 56, 82)

# =========================================================
# BUILD CANDIDATES
# =========================================================

def build_goal_candidates(matches):
    raw = []

    for m in matches:
        info = get_match_info(m)
        raw.append({"info": info, "base": base_goal_score(info)})

    raw.sort(key=lambda x: x["base"], reverse=True)

    enriched = []
    calls = 0

    for item in raw:
        info = item["info"]
        pred = None

        if calls < MAX_PREDICTION_CALLS:
            pred = get_prediction(info["fixture_id"])
            calls += 1

        prob = apply_prediction_to_goal_score(item["base"], pred)
        mercado = "Total de Gols: Mais de 1.5"

        if prob < 68 and info["league_id"] in {140, 128, 13, 11}:
            mercado = "Total de Gols: Menos de 3.5"
            prob = clamp(prob + 2.0, 58, 84)

        enriched.append({
            "tipo": "GOLS",
            "jogo": f"{info['home_name']} x {info['away_name']}",
            "liga": info["league_name"],
            "mercado": mercado,
            "prob": prob,
            "faixa": confidence(prob),
            "fixture_id": info["fixture_id"]
        })

    return enriched

def build_corner_candidates(matches):
    raw = []

    for m in matches:
        info = get_match_info(m)
        raw.append({"info": info, "base": base_corner_score(info)})

    raw.sort(key=lambda x: x["base"], reverse=True)

    enriched = []
    calls = 0

    for item in raw:
        info = item["info"]
        pred = None

        if calls < MAX_PREDICTION_CALLS:
            pred = get_prediction(info["fixture_id"])
            calls += 1

        prob = apply_prediction_to_corner_score(item["base"], pred)
        mercado = "Total de Escanteios: Mais de 8.5"

        if prob < 68:
            mercado = "Total de Escanteios: Mais de 7.5"

        enriched.append({
            "tipo": "ESCANTEIOS",
            "jogo": f"{info['home_name']} x {info['away_name']}",
            "liga": info["league_name"],
            "mercado": mercado,
            "prob": prob,
            "faixa": confidence(prob),
            "fixture_id": info["fixture_id"]
        })

    return enriched

# =========================================================
# RANKINGS
# =========================================================

def top_gols(matches):
    candidatos = [x for x in build_goal_candidates(matches) if x["prob"] >= MIN_GOAL_PROB]
    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    ranking = []
    used = set()

    for item in candidatos:
        if item["jogo"] in used:
            continue
        used.add(item["jogo"])
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

def top_escanteios(matches):
    candidatos = [x for x in build_corner_candidates(matches) if x["prob"] >= MIN_CORNER_PROB]
    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    ranking = []
    used = set()

    for item in candidatos:
        if item["jogo"] in used:
            continue
        used.add(item["jogo"])
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

def top_fortes(matches):
    candidatos = []

    for item in build_goal_candidates(matches):
        if item["prob"] >= MIN_STRONG_PROB:
            candidatos.append(item)

    for item in build_corner_candidates(matches):
        if item["prob"] >= MIN_STRONG_PROB:
            candidatos.append(item)

    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    ranking = []
    used = set()

    for item in candidatos:
        key = (item["jogo"], item["tipo"])
        if key in used:
            continue
        used.add(key)
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

# =========================================================
# ODDS / VALUE BETS
# =========================================================

def get_fixture_odds(fixture_id):
    if fixture_id in odds_cache:
        return odds_cache[fixture_id]

    try:
        data = api_get("/odds", {"fixture": fixture_id})
        response = data.get("response") or []
        odds_cache[fixture_id] = response
        return response
    except Exception:
        odds_cache[fixture_id] = []
        return []

def parse_odd_value(value):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None

def best_market_odd(odds_response, market_type, target_name):
    """
    market_type:
      - goals
      - btts
    target_name:
      - Over 1.5
      - Over 2.5
      - Yes
    """
    best_odd = None
    best_bookmaker = None

    for item in odds_response:
        bookmakers = item.get("bookmakers", []) or []

        for bookmaker in bookmakers:
            bookmaker_name = bookmaker.get("name", "Bookmaker")
            bets = bookmaker.get("bets", []) or []

            for bet in bets:
                bet_name = (bet.get("name") or "").strip().lower()
                values = bet.get("values", []) or []

                if market_type == "goals":
                    if "goals over/under" not in bet_name and "over/under" not in bet_name:
                        continue

                    for v in values:
                        label = (v.get("value") or "").strip().lower()
                        odd = parse_odd_value(v.get("odd"))

                        if odd is None:
                            continue

                        if label == target_name.lower():
                            if best_odd is None or odd > best_odd:
                                best_odd = odd
                                best_bookmaker = bookmaker_name

                elif market_type == "btts":
                    if "both teams score" not in bet_name and "btts" not in bet_name:
                        continue

                    for v in values:
                        label = (v.get("value") or "").strip().lower()
                        odd = parse_odd_value(v.get("odd"))

                        if odd is None:
                            continue

                        if label == target_name.lower():
                            if best_odd is None or odd > best_odd:
                                best_odd = odd
                                best_bookmaker = bookmaker_name

    return best_odd, best_bookmaker

def build_real_valuebets(matches):
    goal_candidates = build_goal_candidates(matches)
    goal_candidates.sort(key=lambda x: x["prob"], reverse=True)

    selected = []
    used_fixture = set()

    for item in goal_candidates:
        if item["fixture_id"] in used_fixture:
            continue
        used_fixture.add(item["fixture_id"])
        selected.append(item)
        if len(selected) >= MAX_VALUE_FIXTURES:
            break

    results = []

    for item in selected:
        fixture_id = item["fixture_id"]
        odds_response = get_fixture_odds(fixture_id)

        if not odds_response:
            continue

        markets = [
            {
                "mercado": "Total de Gols: Mais de 1.5",
                "market_type": "goals",
                "target": "Over 1.5",
                "prob": item["prob"]
            },
            {
                "mercado": "Total de Gols: Mais de 2.5",
                "market_type": "goals",
                "target": "Over 2.5",
                "prob": clamp(item["prob"] - 7, 45, 82)
            },
            {
                "mercado": "BTTS: Sim",
                "market_type": "btts",
                "target": "Yes",
                "prob": clamp(item["prob"] - 9, 42, 78)
            }
        ]

        for m in markets:
            prob = m["prob"]

            if prob < MIN_VALUE_PROB:
                continue

            best_odd, bookmaker = best_market_odd(
                odds_response,
                m["market_type"],
                m["target"]
            )

            if not best_odd:
                continue

            fair = fair_odd_from_prob(prob)
            edge = value_edge(prob, best_odd)

            if edge < MIN_VALUE_EDGE:
                continue

            results.append({
                "jogo": item["jogo"],
                "liga": item["liga"],
                "fixture_id": fixture_id,
                "mercado": m["mercado"],
                "prob": prob,
                "odd_justa": fair,
                "odd_casa": best_odd,
                "bookmaker": bookmaker or "Bookmaker",
                "edge": edge,
                "faixa": edge_label(edge)
            })

    results.sort(key=lambda x: x["edge"], reverse=True)

    unique = []
    used = set()

    for r in results:
        key = (r["fixture_id"], r["mercado"])
        if key in used:
            continue
        used.add(key)
        unique.append(r)
        if len(unique) >= 10:
            break

    return unique

# =========================================================
# ANALISE EXATA
# =========================================================

def find_match_exact(pool, query):
    q = normalize_text(query)

    if q.isdigit():
        fixture_id = int(q)
        for m in pool:
            info = get_match_info(m)
            if info["fixture_id"] == fixture_id:
                return m
        return None

    if " x " not in q:
        return None

    left, right = q.split(" x ", 1)
    left = normalize_text(left)
    right = normalize_text(right)

    for m in pool:
        info = get_match_info(m)
        home = normalize_text(info["home_name"])
        away = normalize_text(info["away_name"])

        if home == left and away == right:
            return m

    candidates = []

    for m in pool:
        info = get_match_info(m)
        home = normalize_text(info["home_name"])
        away = normalize_text(info["away_name"])

        if left in home and right in away:
            score = len(left) + len(right)
            candidates.append((score, m))

    if len(candidates) == 1:
        return candidates[0][1]

    return None

def analysis_from_prediction(pred, info):
    base_goals = base_goal_score(info)
    base_corners = base_corner_score(info)

    over15 = apply_prediction_to_goal_score(base_goals, pred)
    over25 = clamp(over15 - 7, 45, 82)
    btts = clamp(over15 - 9, 42, 78)
    corners85 = apply_prediction_to_corner_score(base_corners, pred)
    corners75 = clamp(corners85 + 2, 50, 84)

    recommendations = [
        ("Total de Gols: Mais de 1.5", over15),
        ("Total de Gols: Mais de 2.5", over25),
        ("BTTS: Sim", btts),
        ("Total de Escanteios: Mais de 7.5", corners75),
        ("Total de Escanteios: Mais de 8.5", corners85),
    ]

    recommendations.sort(key=lambda x: x[1], reverse=True)
    best_market, best_prob = recommendations[0]

    msg = "📊 ANÁLISE DO JOGO\n\n"
    msg += f"{info['home_name']} x {info['away_name']}\n"
    msg += f"{info['league_name']}\n\n"
    msg += f"ID do jogo: {info['fixture_id']}\n\n"

    msg += f"Over 1.5 gols: {fmt_prob(over15)}% ({confidence(over15)})\n"
    msg += f"Over 2.5 gols: {fmt_prob(over25)}% ({confidence(over25)})\n"
    msg += f"BTTS Sim: {fmt_prob(btts)}% ({confidence(btts)})\n"
    msg += f"Escanteios +7.5: {fmt_prob(corners75)}% ({confidence(corners75)})\n"
    msg += f"Escanteios +8.5: {fmt_prob(corners85)}% ({confidence(corners85)})\n\n"

    msg += "Melhor mercado:\n"
    msg += f"{best_market}\n"
    msg += f"Probabilidade: {fmt_prob(best_prob)}%\n"
    msg += f"Faixa: {confidence(best_prob)}"

    return msg

def analyze_match_command(text):
    query = text[len("/analise"):].strip()

    if not query:
        return (
            "Use assim:\n"
            "/analise Time da Casa x Time de Fora\n"
            "ou\n"
            "/analise ID_DO_JOGO\n\n"
            "Primeiro rode /jogos para ver a lista real."
        )

    pool = get_analysis_pool()
    match = find_match_exact(pool, query)

    if not match:
        return (
            "Não encontrei esse jogo de forma exata.\n\n"
            "Faça assim:\n"
            "1. rode /jogos\n"
            "2. copie o confronto exatamente como apareceu\n"
            "ou use /analise ID_DO_JOGO"
        )

    info = get_match_info(match)
    pred = get_prediction(info["fixture_id"])

    return analysis_from_prediction(pred, info)

# =========================================================
# FORMATAR
# =========================================================

def format_list(title, ranking):
    if not ranking:
        return f"{title}\n\nNenhuma oportunidade encontrada."

    msg = f"{title}\n\n"

    for i, item in enumerate(ranking, start=1):
        prefix = f"[{item['tipo']}] " if title == "💎 TOP FORTES" else ""
        msg += f"{i}. {prefix}{item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"Probabilidade: {fmt_prob(item['prob'])}%\n"
        msg += f"Faixa: {item['faixa']}\n"
        msg += f"{item['liga']}\n\n"

    return msg

def format_tophoje(matches):
    gols = top_gols(matches)[:5]
    esc = top_escanteios(matches)[:5]
    fortes = top_fortes(matches)[:3]

    msg = "📅 TOP HOJE\n\n"

    msg += "🔥 GOLS\n"
    if gols:
        for i, item in enumerate(gols, start=1):
            msg += f"{i}. {item['jogo']} - {fmt_prob(item['prob'])}%\n"
    else:
        msg += "Nenhuma oportunidade.\n"

    msg += "\n🚩 ESCANTEIOS\n"
    if esc:
        for i, item in enumerate(esc, start=1):
            msg += f"{i}. {item['jogo']} - {fmt_prob(item['prob'])}%\n"
    else:
        msg += "Nenhuma oportunidade.\n"

    msg += "\n💎 FORTES\n"
    if fortes:
        for i, item in enumerate(fortes, start=1):
            msg += f"{i}. [{item['tipo']}] {item['jogo']} - {fmt_prob(item['prob'])}%\n"
    else:
        msg += "Nenhuma oportunidade.\n"

    return msg

def format_games(pool):
    if not pool:
        return "📋 JOGOS\n\nNenhum jogo encontrado na janela de busca."

    msg = "📋 JOGOS\n\n"
    count = 0

    for m in pool:
        info = get_match_info(m)
        msg += f"{info['fixture_id']} | {info['home_name']} x {info['away_name']}\n"
        msg += f"{info['league_name']}\n\n"
        count += 1
        if count >= 30:
            break

    msg += "Use:\n/analise ID_DO_JOGO"
    return msg

def format_valuebets(ranking):
    if not ranking:
        return "💰 VALUEBETS\n\nNenhum value real encontrado com odds disponíveis."

    msg = "💰 VALUEBETS\n\n"

    for i, item in enumerate(ranking, start=1):
        msg += f"{i}. {item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"ID: {item['fixture_id']}\n"
        msg += f"Probabilidade modelo: {fmt_prob(item['prob'])}%\n"
        msg += f"Odd justa: {fmt_odd(item['odd_justa'])}\n"
        msg += f"Odd encontrada: {fmt_odd(item['odd_casa'])}\n"
        msg += f"Bookmaker: {item['bookmaker']}\n"
        msg += f"Edge: {item['edge'] * 100:.1f}%\n"
        msg += f"Faixa: {item['faixa']}\n"
        msg += f"{item['liga']}\n\n"

    return msg

# =========================================================
# FLASK
# =========================================================

@app.route("/")
def home():
    return "ELITE 15.0 online"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message", {})

    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}

    if text in ("/start", "start"):
        send(
            chat_id,
            "🤖 ELITE 15.0 online ✅\n\n"
            "Comandos:\n"
            "/teste\n"
            "/jogos\n"
            "/topgols\n"
            "/topescanteios\n"
            "/topfortes\n"
            "/tophoje\n"
            "/valuebets\n"
            "/analise Time A x Time B\n"
            "/analise ID_DO_JOGO"
        )

    elif text == "/teste":
        send(chat_id, "✅ ELITE 15.0 funcionando")

    elif text == "/jogos":
        try:
            send(chat_id, format_games(get_analysis_pool()))
        except Exception as e:
            send(chat_id, f"Erro no jogos: {type(e).__name__} - {e}")

    elif text == "/topgols":
        try:
            matches = get_matches_today()
            send(chat_id, format_list("🔥 TOP GOLS", top_gols(matches)))
        except Exception as e:
            send(chat_id, f"Erro no topgols: {type(e).__name__} - {e}")

    elif text == "/topescanteios":
        try:
            matches = get_matches_today()
            send(chat_id, format_list("🚩 TOP ESCANTEIOS", top_escanteios(matches)))
        except Exception as e:
            send(chat_id, f"Erro no topescanteios: {type(e).__name__} - {e}")

    elif text == "/topfortes":
        try:
            matches = get_matches_today()
            send(chat_id, format_list("💎 TOP FORTES", top_fortes(matches)))
        except Exception as e:
            send(chat_id, f"Erro no topfortes: {type(e).__name__} - {e}")

    elif text == "/tophoje":
        try:
            matches = get_matches_today()
            send(chat_id, format_tophoje(matches))
        except Exception as e:
            send(chat_id, f"Erro no tophoje: {type(e).__name__} - {e}")

    elif text == "/valuebets":
        try:
            matches = get_matches_today()
            send(chat_id, format_valuebets(build_real_valuebets(matches)))
        except Exception as e:
            send(chat_id, f"Erro no valuebets: {type(e).__name__} - {e}")

    elif text.lower().startswith("/analise"):
        try:
            send(chat_id, analyze_match_command(text))
        except Exception as e:
            send(chat_id, f"Erro no analise: {type(e).__name__} - {e}")

    else:
        send(
            chat_id,
            "Comandos:\n"
            "/teste\n"
            "/jogos\n"
            "/topgols\n"
            "/topescanteios\n"
            "/topfortes\n"
            "/tophoje\n"
            "/valuebets\n"
            "/analise Time A x Time B\n"
            "/analise ID_DO_JOGO"
        )

    return {"ok": True}

try:
    set_webhook()
except Exception:
    pass
import requests
from flask import Flask, request
from datetime import datetime, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("Faltou TELEGRAM_TOKEN")

if not API_FOOTBALL_KEY:
    raise RuntimeError("Faltou API_FOOTBALL_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_FOOTBALL_KEY
}

session = requests.Session()
session.headers.update(HEADERS)

# =========================================================
# CONFIG ELITE 15.0
# =========================================================

ALLOWED_LEAGUES = {
    2,    # UEFA Champions League
    3,    # UEFA Europa League
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    94,   # Primeira Liga
    88,   # Eredivisie
    144,  # Belgium Pro League
    203,  # Super Lig
    207,  # Switzerland Super League
    218,  # Austria Bundesliga
    119,  # Denmark Superliga
    179,  # Scotland Premiership
    71,   # Brazil Serie A
    128,  # Argentina Liga Profesional
    253,  # MLS
    13,   # Libertadores
    11,   # Sul-Americana
    307   # Saudi Pro League
}

LEAGUE_GOAL_PROFILE = {
    2: 1.08,
    3: 1.03,
    39: 1.10,
    140: 0.98,
    135: 1.02,
    78: 1.12,
    61: 1.03,
    94: 1.03,
    88: 1.18,
    144: 1.07,
    203: 1.08,
    207: 1.05,
    218: 1.07,
    119: 1.04,
    179: 1.02,
    71: 1.04,
    128: 0.99,
    253: 1.06,
    13: 0.96,
    11: 0.95,
    307: 1.10
}

LEAGUE_CORNER_PROFILE = {
    2: 1.05,
    3: 1.03,
    39: 1.10,
    140: 1.08,
    135: 1.03,
    78: 1.08,
    61: 1.01,
    94: 1.00,
    88: 1.03,
    144: 1.04,
    203: 1.06,
    207: 1.02,
    218: 1.03,
    119: 1.02,
    179: 1.01,
    71: 1.03,
    128: 0.98,
    253: 1.04,
    13: 1.01,
    11: 1.00,
    307: 1.05
}

MIN_GOAL_PROB = 65
MIN_CORNER_PROB = 63
MIN_STRONG_PROB = 69
MIN_VALUE_PROB = 66
MIN_VALUE_EDGE = 0.08   # 8%
MAX_PREDICTION_CALLS = 20
MAX_VALUE_FIXTURES = 20

predictions_cache = {}
odds_cache = {}
matches_cache = {}

# =========================================================
# HELPERS
# =========================================================

def api_get(path, params=None):
    url = f"{BASE_URL}{path}"
    r = session.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def send(chat_id, text):
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30
    )

def set_webhook():
    if not PUBLIC_URL:
        return

    requests.post(
        f"{TELEGRAM_API}/setWebhook",
        json={"url": f"{PUBLIC_URL}/webhook"},
        timeout=30
    )

def fmt_prob(v):
    return int(round(v))

def fmt_odd(v):
    return f"{v:.2f}"

def confidence(prob):
    p = fmt_prob(prob)

    if p >= 75:
        return "MUITO FORTE"
    if p >= 70:
        return "BOA"
    if p >= 65:
        return "ACEITÁVEL"
    return "FRACA"

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def normalize_text(text):
    text = (text or "").lower().strip()

    text = text.replace("ı", "i")
    text = text.replace("ş", "s")
    text = text.replace("ğ", "g")
    text = text.replace("ü", "u")
    text = text.replace("ö", "o")
    text = text.replace("ç", "c")

    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")

    for ch in [".", ",", "-", "/", "(", ")", "'", '"', ":", ";"]:
        text = text.replace(ch, " ")

    remove_words = {"sk", "fk", "fc", "cf", "ac", "sc", "cd", "ud", "bk", "jk"}
    words = [w for w in text.split() if w not in remove_words]
    text = " ".join(words)

    while "  " in text:
        text = text.replace("  ", " ")

    return text.strip()

def fair_odd_from_prob(prob):
    p = max(1.0, float(prob))
    return 100.0 / p

def value_edge(prob, odd):
    fair = fair_odd_from_prob(prob)
    return (odd / fair) - 1.0

def edge_label(edge):
    if edge >= 0.20:
        return "VALUE ALTO"
    if edge >= 0.12:
        return "VALUE BOM"
    if edge >= 0.08:
        return "VALUE LEVE"
    return "SEM VALUE"

# =========================================================
# BUSCAR JOGOS
# =========================================================

def get_matches_by_date(date_str):
    if date_str in matches_cache:
        return matches_cache[date_str]

    data = api_get("/fixtures", {"date": date_str})
    matches = []

    for m in data.get("response", []):
        league_id = m.get("league", {}).get("id")
        status = (m.get("fixture", {}).get("status", {}).get("short") or "").upper()

        if league_id not in ALLOWED_LEAGUES:
            continue

        if status not in ("NS", "TBD"):
            continue

        matches.append(m)

    matches_cache[date_str] = matches
    return matches

def get_matches_today():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return get_matches_by_date(today)

def get_analysis_pool():
    base_date = datetime.utcnow().date()
    pool = []
    used = set()

    for delta in (-1, 0, 1, 2):
        date_str = (base_date + timedelta(days=delta)).strftime("%Y-%m-%d")
        for m in get_matches_by_date(date_str):
            fixture_id = m.get("fixture", {}).get("id")
            if fixture_id in used:
                continue
            used.add(fixture_id)
            pool.append(m)

    return pool

# =========================================================
# MATCH INFO
# =========================================================

def get_match_info(match):
    fixture = match.get("fixture", {})
    league = match.get("league", {})
    teams = match.get("teams", {})
    home = teams.get("home", {})
    away = teams.get("away", {})

    return {
        "fixture_id": fixture.get("id"),
        "league_id": league.get("id"),
        "league_name": league.get("name", ""),
        "home_name": home.get("name", "Casa"),
        "away_name": away.get("name", "Fora"),
        "date": fixture.get("date", "")
    }

# =========================================================
# SCORE BASE
# =========================================================

def base_goal_score(info):
    score = 63.0
    league_id = info["league_id"]
    text = f"{info['home_name']} {info['away_name']}".lower()

    score *= LEAGUE_GOAL_PROFILE.get(league_id, 1.00)

    attacking_terms = [
        "ajax", "psv", "feyenoord", "bayern", "leverkusen",
        "atalanta", "sporting", "benfica", "porto",
        "manchester city", "arsenal", "liverpool",
        "real madrid", "barcelona", "dortmund",
        "al hilal", "al nassr", "al ittihad"
    ]

    if any(term in text for term in attacking_terms):
        score += 2.5

    derby_terms = [
        "milan", "inter", "roma", "porto", "benfica",
        "galatasaray", "fenerbahce", "celtic", "rangers",
        "sevilla", "betis"
    ]

    if any(term in text for term in derby_terms):
        score -= 1.5

    return clamp(score, 58, 78)

def base_corner_score(info):
    score = 60.0
    league_id = info["league_id"]
    text = f"{info['home_name']} {info['away_name']}".lower()

    score *= LEAGUE_CORNER_PROFILE.get(league_id, 1.00)

    pressing_terms = [
        "liverpool", "arsenal", "atalanta", "leverkusen",
        "ajax", "psv", "feyenoord", "roma", "porto",
        "benfica", "real madrid", "barcelona",
        "al hilal", "al nassr", "al ittihad"
    ]

    if any(term in text for term in pressing_terms):
        score += 3.0

    return clamp(score, 56, 77)

# =========================================================
# PREDICTIONS
# =========================================================

def get_prediction(fixture_id):
    if fixture_id in predictions_cache:
        return predictions_cache[fixture_id]

    try:
        data = api_get("/predictions", {"fixture": fixture_id})
        response = data.get("response") or []

        if not response:
            predictions_cache[fixture_id] = None
            return None

        pred = response[0]
        predictions_cache[fixture_id] = pred
        return pred

    except Exception:
        predictions_cache[fixture_id] = None
        return None

def apply_prediction_to_goal_score(base_score, pred):
    score = base_score

    if not pred:
        return clamp(score, 58, 84)

    predictions = pred.get("predictions", {})
    comparison = pred.get("comparison", {})
    goals = predictions.get("goals", {})
    advice = (predictions.get("advice") or "").lower()

    home_goals = goals.get("home")
    away_goals = goals.get("away")

    total_pred = 0.0
    if isinstance(home_goals, (int, float)):
        total_pred += float(home_goals)
    if isinstance(away_goals, (int, float)):
        total_pred += float(away_goals)

    if total_pred >= 3.0:
        score += 5.0
    elif total_pred >= 2.4:
        score += 3.0
    elif total_pred >= 2.0:
        score += 1.5
    else:
        score -= 1.0

    if "over 1.5" in advice:
        score += 4.0
    elif "under 3.5" in advice:
        score += 1.5

    if comparison.get("att", {}).get("home") == "strong":
        score += 1.0
    if comparison.get("att", {}).get("away") == "strong":
        score += 1.0

    return clamp(score, 58, 84)

def apply_prediction_to_corner_score(base_score, pred):
    score = base_score

    if not pred:
        return clamp(score, 56, 82)

    comparison = pred.get("comparison", {})
    predictions = pred.get("predictions", {})
    advice = (predictions.get("advice") or "").lower()

    if comparison.get("att", {}).get("home") == "strong":
        score += 1.5
    if comparison.get("att", {}).get("away") == "strong":
        score += 1.5
    if comparison.get("h2h", {}).get("home") == "strong":
        score += 0.5
    if comparison.get("h2h", {}).get("away") == "strong":
        score += 0.5
    if "over 2.5" in advice or "over 1.5" in advice:
        score += 1.5

    return clamp(score, 56, 82)

# =========================================================
# BUILD CANDIDATES
# =========================================================

def build_goal_candidates(matches):
    raw = []

    for m in matches:
        info = get_match_info(m)
        raw.append({"info": info, "base": base_goal_score(info)})

    raw.sort(key=lambda x: x["base"], reverse=True)

    enriched = []
    calls = 0

    for item in raw:
        info = item["info"]
        pred = None

        if calls < MAX_PREDICTION_CALLS:
            pred = get_prediction(info["fixture_id"])
            calls += 1

        prob = apply_prediction_to_goal_score(item["base"], pred)
        mercado = "Total de Gols: Mais de 1.5"

        if prob < 68 and info["league_id"] in {140, 128, 13, 11}:
            mercado = "Total de Gols: Menos de 3.5"
            prob = clamp(prob + 2.0, 58, 84)

        enriched.append({
            "tipo": "GOLS",
            "jogo": f"{info['home_name']} x {info['away_name']}",
            "liga": info["league_name"],
            "mercado": mercado,
            "prob": prob,
            "faixa": confidence(prob),
            "fixture_id": info["fixture_id"]
        })

    return enriched

def build_corner_candidates(matches):
    raw = []

    for m in matches:
        info = get_match_info(m)
        raw.append({"info": info, "base": base_corner_score(info)})

    raw.sort(key=lambda x: x["base"], reverse=True)

    enriched = []
    calls = 0

    for item in raw:
        info = item["info"]
        pred = None

        if calls < MAX_PREDICTION_CALLS:
            pred = get_prediction(info["fixture_id"])
            calls += 1

        prob = apply_prediction_to_corner_score(item["base"], pred)
        mercado = "Total de Escanteios: Mais de 8.5"

        if prob < 68:
            mercado = "Total de Escanteios: Mais de 7.5"

        enriched.append({
            "tipo": "ESCANTEIOS",
            "jogo": f"{info['home_name']} x {info['away_name']}",
            "liga": info["league_name"],
            "mercado": mercado,
            "prob": prob,
            "faixa": confidence(prob),
            "fixture_id": info["fixture_id"]
        })

    return enriched

# =========================================================
# RANKINGS
# =========================================================

def top_gols(matches):
    candidatos = [x for x in build_goal_candidates(matches) if x["prob"] >= MIN_GOAL_PROB]
    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    ranking = []
    used = set()

    for item in candidatos:
        if item["jogo"] in used:
            continue
        used.add(item["jogo"])
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

def top_escanteios(matches):
    candidatos = [x for x in build_corner_candidates(matches) if x["prob"] >= MIN_CORNER_PROB]
    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    ranking = []
    used = set()

    for item in candidatos:
        if item["jogo"] in used:
            continue
        used.add(item["jogo"])
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

def top_fortes(matches):
    candidatos = []

    for item in build_goal_candidates(matches):
        if item["prob"] >= MIN_STRONG_PROB:
            candidatos.append(item)

    for item in build_corner_candidates(matches):
        if item["prob"] >= MIN_STRONG_PROB:
            candidatos.append(item)

    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    ranking = []
    used = set()

    for item in candidatos:
        key = (item["jogo"], item["tipo"])
        if key in used:
            continue
        used.add(key)
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

# =========================================================
# ODDS / VALUE BETS
# =========================================================

def get_fixture_odds(fixture_id):
    if fixture_id in odds_cache:
        return odds_cache[fixture_id]

    try:
        data = api_get("/odds", {"fixture": fixture_id})
        response = data.get("response") or []
        odds_cache[fixture_id] = response
        return response
    except Exception:
        odds_cache[fixture_id] = []
        return []

def parse_odd_value(value):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None

def best_market_odd(odds_response, market_type, target_name):
    """
    market_type:
      - goals
      - btts
    target_name:
      - Over 1.5
      - Over 2.5
      - Yes
    """
    best_odd = None
    best_bookmaker = None

    for item in odds_response:
        bookmakers = item.get("bookmakers", []) or []

        for bookmaker in bookmakers:
            bookmaker_name = bookmaker.get("name", "Bookmaker")
            bets = bookmaker.get("bets", []) or []

            for bet in bets:
                bet_name = (bet.get("name") or "").strip().lower()
                values = bet.get("values", []) or []

                if market_type == "goals":
                    if "goals over/under" not in bet_name and "over/under" not in bet_name:
                        continue

                    for v in values:
                        label = (v.get("value") or "").strip().lower()
                        odd = parse_odd_value(v.get("odd"))

                        if odd is None:
                            continue

                        if label == target_name.lower():
                            if best_odd is None or odd > best_odd:
                                best_odd = odd
                                best_bookmaker = bookmaker_name

                elif market_type == "btts":
                    if "both teams score" not in bet_name and "btts" not in bet_name:
                        continue

                    for v in values:
                        label = (v.get("value") or "").strip().lower()
                        odd = parse_odd_value(v.get("odd"))

                        if odd is None:
                            continue

                        if label == target_name.lower():
                            if best_odd is None or odd > best_odd:
                                best_odd = odd
                                best_bookmaker = bookmaker_name

    return best_odd, best_bookmaker

def build_real_valuebets(matches):
    goal_candidates = build_goal_candidates(matches)
    goal_candidates.sort(key=lambda x: x["prob"], reverse=True)

    selected = []
    used_fixture = set()

    for item in goal_candidates:
        if item["fixture_id"] in used_fixture:
            continue
        used_fixture.add(item["fixture_id"])
        selected.append(item)
        if len(selected) >= MAX_VALUE_FIXTURES:
            break

    results = []

    for item in selected:
        fixture_id = item["fixture_id"]
        odds_response = get_fixture_odds(fixture_id)

        if not odds_response:
            continue

        markets = [
            {
                "mercado": "Total de Gols: Mais de 1.5",
                "market_type": "goals",
                "target": "Over 1.5",
                "prob": item["prob"]
            },
            {
                "mercado": "Total de Gols: Mais de 2.5",
                "market_type": "goals",
                "target": "Over 2.5",
                "prob": clamp(item["prob"] - 7, 45, 82)
            },
            {
                "mercado": "BTTS: Sim",
                "market_type": "btts",
                "target": "Yes",
                "prob": clamp(item["prob"] - 9, 42, 78)
            }
        ]

        for m in markets:
            prob = m["prob"]

            if prob < MIN_VALUE_PROB:
                continue

            best_odd, bookmaker = best_market_odd(
                odds_response,
                m["market_type"],
                m["target"]
            )

            if not best_odd:
                continue

            fair = fair_odd_from_prob(prob)
            edge = value_edge(prob, best_odd)

            if edge < MIN_VALUE_EDGE:
                continue

            results.append({
                "jogo": item["jogo"],
                "liga": item["liga"],
                "fixture_id": fixture_id,
                "mercado": m["mercado"],
                "prob": prob,
                "odd_justa": fair,
                "odd_casa": best_odd,
                "bookmaker": bookmaker or "Bookmaker",
                "edge": edge,
                "faixa": edge_label(edge)
            })

    results.sort(key=lambda x: x["edge"], reverse=True)

    unique = []
    used = set()

    for r in results:
        key = (r["fixture_id"], r["mercado"])
        if key in used:
            continue
        used.add(key)
        unique.append(r)
        if len(unique) >= 10:
            break

    return unique

# =========================================================
# ANALISE EXATA
# =========================================================

def find_match_exact(pool, query):
    q = normalize_text(query)

    if q.isdigit():
        fixture_id = int(q)
        for m in pool:
            info = get_match_info(m)
            if info["fixture_id"] == fixture_id:
                return m
        return None

    if " x " not in q:
        return None

    left, right = q.split(" x ", 1)
    left = normalize_text(left)
    right = normalize_text(right)

    for m in pool:
        info = get_match_info(m)
        home = normalize_text(info["home_name"])
        away = normalize_text(info["away_name"])

        if home == left and away == right:
            return m

    candidates = []

    for m in pool:
        info = get_match_info(m)
        home = normalize_text(info["home_name"])
        away = normalize_text(info["away_name"])

        if left in home and right in away:
            score = len(left) + len(right)
            candidates.append((score, m))

    if len(candidates) == 1:
        return candidates[0][1]

    return None

def analysis_from_prediction(pred, info):
    base_goals = base_goal_score(info)
    base_corners = base_corner_score(info)

    over15 = apply_prediction_to_goal_score(base_goals, pred)
    over25 = clamp(over15 - 7, 45, 82)
    btts = clamp(over15 - 9, 42, 78)
    corners85 = apply_prediction_to_corner_score(base_corners, pred)
    corners75 = clamp(corners85 + 2, 50, 84)

    recommendations = [
        ("Total de Gols: Mais de 1.5", over15),
        ("Total de Gols: Mais de 2.5", over25),
        ("BTTS: Sim", btts),
        ("Total de Escanteios: Mais de 7.5", corners75),
        ("Total de Escanteios: Mais de 8.5", corners85),
    ]

    recommendations.sort(key=lambda x: x[1], reverse=True)
    best_market, best_prob = recommendations[0]

    msg = "📊 ANÁLISE DO JOGO\n\n"
    msg += f"{info['home_name']} x {info['away_name']}\n"
    msg += f"{info['league_name']}\n\n"
    msg += f"ID do jogo: {info['fixture_id']}\n\n"

    msg += f"Over 1.5 gols: {fmt_prob(over15)}% ({confidence(over15)})\n"
    msg += f"Over 2.5 gols: {fmt_prob(over25)}% ({confidence(over25)})\n"
    msg += f"BTTS Sim: {fmt_prob(btts)}% ({confidence(btts)})\n"
    msg += f"Escanteios +7.5: {fmt_prob(corners75)}% ({confidence(corners75)})\n"
    msg += f"Escanteios +8.5: {fmt_prob(corners85)}% ({confidence(corners85)})\n\n"

    msg += "Melhor mercado:\n"
    msg += f"{best_market}\n"
    msg += f"Probabilidade: {fmt_prob(best_prob)}%\n"
    msg += f"Faixa: {confidence(best_prob)}"

    return msg

def analyze_match_command(text):
    query = text[len("/analise"):].strip()

    if not query:
        return (
            "Use assim:\n"
            "/analise Time da Casa x Time de Fora\n"
            "ou\n"
            "/analise ID_DO_JOGO\n\n"
            "Primeiro rode /jogos para ver a lista real."
        )

    pool = get_analysis_pool()
    match = find_match_exact(pool, query)

    if not match:
        return (
            "Não encontrei esse jogo de forma exata.\n\n"
            "Faça assim:\n"
            "1. rode /jogos\n"
            "2. copie o confronto exatamente como apareceu\n"
            "ou use /analise ID_DO_JOGO"
        )

    info = get_match_info(match)
    pred = get_prediction(info["fixture_id"])

    return analysis_from_prediction(pred, info)

# =========================================================
# FORMATAR
# =========================================================

def format_list(title, ranking):
    if not ranking:
        return f"{title}\n\nNenhuma oportunidade encontrada."

    msg = f"{title}\n\n"

    for i, item in enumerate(ranking, start=1):
        prefix = f"[{item['tipo']}] " if title == "💎 TOP FORTES" else ""
        msg += f"{i}. {prefix}{item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"Probabilidade: {fmt_prob(item['prob'])}%\n"
        msg += f"Faixa: {item['faixa']}\n"
        msg += f"{item['liga']}\n\n"

    return msg

def format_tophoje(matches):
    gols = top_gols(matches)[:5]
    esc = top_escanteios(matches)[:5]
    fortes = top_fortes(matches)[:3]

    msg = "📅 TOP HOJE\n\n"

    msg += "🔥 GOLS\n"
    if gols:
        for i, item in enumerate(gols, start=1):
            msg += f"{i}. {item['jogo']} - {fmt_prob(item['prob'])}%\n"
    else:
        msg += "Nenhuma oportunidade.\n"

    msg += "\n🚩 ESCANTEIOS\n"
    if esc:
        for i, item in enumerate(esc, start=1):
            msg += f"{i}. {item['jogo']} - {fmt_prob(item['prob'])}%\n"
    else:
        msg += "Nenhuma oportunidade.\n"

    msg += "\n💎 FORTES\n"
    if fortes:
        for i, item in enumerate(fortes, start=1):
            msg += f"{i}. [{item['tipo']}] {item['jogo']} - {fmt_prob(item['prob'])}%\n"
    else:
        msg += "Nenhuma oportunidade.\n"

    return msg

def format_games(pool):
    if not pool:
        return "📋 JOGOS\n\nNenhum jogo encontrado na janela de busca."

    msg = "📋 JOGOS\n\n"
    count = 0

    for m in pool:
        info = get_match_info(m)
        msg += f"{info['fixture_id']} | {info['home_name']} x {info['away_name']}\n"
        msg += f"{info['league_name']}\n\n"
        count += 1
        if count >= 30:
            break

    msg += "Use:\n/analise ID_DO_JOGO"
    return msg

def format_valuebets(ranking):
    if not ranking:
        return "💰 VALUEBETS\n\nNenhum value real encontrado com odds disponíveis."

    msg = "💰 VALUEBETS\n\n"

    for i, item in enumerate(ranking, start=1):
        msg += f"{i}. {item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"ID: {item['fixture_id']}\n"
        msg += f"Probabilidade modelo: {fmt_prob(item['prob'])}%\n"
        msg += f"Odd justa: {fmt_odd(item['odd_justa'])}\n"
        msg += f"Odd encontrada: {fmt_odd(item['odd_casa'])}\n"
        msg += f"Bookmaker: {item['bookmaker']}\n"
        msg += f"Edge: {item['edge'] * 100:.1f}%\n"
        msg += f"Faixa: {item['faixa']}\n"
        msg += f"{item['liga']}\n\n"

    return msg

# =========================================================
# FLASK
# =========================================================

@app.route("/")
def home():
    return "ELITE 15.0 online"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message", {})

    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}

    if text in ("/start", "start"):
        send(
            chat_id,
            "🤖 ELITE 15.0 online ✅\n\n"
            "Comandos:\n"
            "/teste\n"
            "/jogos\n"
            "/topgols\n"
            "/topescanteios\n"
            "/topfortes\n"
            "/tophoje\n"
            "/valuebets\n"
            "/analise Time A x Time B\n"
            "/analise ID_DO_JOGO"
        )

    elif text == "/teste":
        send(chat_id, "✅ ELITE 15.0 funcionando")

    elif text == "/jogos":
        try:
            send(chat_id, format_games(get_analysis_pool()))
        except Exception as e:
            send(chat_id, f"Erro no jogos: {type(e).__name__} - {e}")

    elif text == "/topgols":
        try:
            matches = get_matches_today()
            send(chat_id, format_list("🔥 TOP GOLS", top_gols(matches)))
        except Exception as e:
            send(chat_id, f"Erro no topgols: {type(e).__name__} - {e}")

    elif text == "/topescanteios":
        try:
            matches = get_matches_today()
            send(chat_id, format_list("🚩 TOP ESCANTEIOS", top_escanteios(matches)))
        except Exception as e:
            send(chat_id, f"Erro no topescanteios: {type(e).__name__} - {e}")

    elif text == "/topfortes":
        try:
            matches = get_matches_today()
            send(chat_id, format_list("💎 TOP FORTES", top_fortes(matches)))
        except Exception as e:
            send(chat_id, f"Erro no topfortes: {type(e).__name__} - {e}")

    elif text == "/tophoje":
        try:
            matches = get_matches_today()
            send(chat_id, format_tophoje(matches))
        except Exception as e:
            send(chat_id, f"Erro no tophoje: {type(e).__name__} - {e}")

    elif text == "/valuebets":
        try:
            matches = get_matches_today()
            send(chat_id, format_valuebets(build_real_valuebets(matches)))
        except Exception as e:
            send(chat_id, f"Erro no valuebets: {type(e).__name__} - {e}")

    elif text.lower().startswith("/analise"):
        try:
            send(chat_id, analyze_match_command(text))
        except Exception as e:
            send(chat_id, f"Erro no analise: {type(e).__name__} - {e}")

    else:
        send(
            chat_id,
            "Comandos:\n"
            "/teste\n"
            "/jogos\n"
            "/topgols\n"
            "/topescanteios\n"
            "/topfortes\n"
            "/tophoje\n"
            "/valuebets\n"
            "/analise Time A x Time B\n"
            "/analise ID_DO_JOGO"
        )

    return {"ok": True}

try:
    set_webhook()
except Exception:
    pass

