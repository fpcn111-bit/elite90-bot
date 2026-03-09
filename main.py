import os
import math
import unicodedata
import requests
from flask import Flask, request
from datetime import datetime

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
# CONFIG ELITE 13.0
# =========================================================

ALLOWED_LEAGUES = {
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

MIN_GOAL_PROB = 66
MIN_CORNER_PROB = 64
MIN_STRONG_PROB = 70
MIN_VALUE_PROB = 68

MAX_PREDICTION_CALLS = 18

predictions_cache = {}
matches_cache = {
    "date": None,
    "matches": []
}

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
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = (
        text.replace(".", " ")
        .replace(",", " ")
        .replace("-", " ")
        .replace("/", " ")
        .replace("(", " ")
        .replace(")", " ")
    )

    while "  " in text:
        text = text.replace("  ", " ")

    return text.strip()

def fair_odd_from_prob(prob):
    p = max(1.0, float(prob))
    return 100.0 / p

def value_band(prob):
    p = fmt_prob(prob)

    if p >= 76:
        return "VALUE ALTO"
    if p >= 72:
        return "VALUE BOM"
    if p >= 68:
        return "VALUE MODERADO"
    return "SEM VALUE"

# =========================================================
# BUSCAR JOGOS DO DIA
# =========================================================

def get_matches_today():
    today = datetime.utcnow().strftime("%Y-%m-%d")

    if matches_cache["date"] == today and matches_cache["matches"]:
        return matches_cache["matches"]

    data = api_get("/fixtures", {"date": today})
    matches = []

    for m in data.get("response", []):
        league_id = m.get("league", {}).get("id")
        status = (m.get("fixture", {}).get("status", {}).get("short") or "").upper()

        if league_id not in ALLOWED_LEAGUES:
            continue

        if status not in ("NS", "TBD"):
            continue

        matches.append(m)

    matches_cache["date"] = today
    matches_cache["matches"] = matches
    return matches

# =========================================================
# BASE FEATURES
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
        "date": fixture.get("date", ""),
    }

def base_goal_score(info):
    score = 63.0
    league_id = info["league_id"]
    texto = f"{info['home_name']} {info['away_name']}".lower()

    score *= LEAGUE_GOAL_PROFILE.get(league_id, 1.00)

    attacking_terms = [
        "ajax", "psv", "feyenoord", "bayern", "leverkusen",
        "atalanta", "sporting", "benfica", "porto",
        "manchester city", "arsenal", "liverpool",
        "al hilal", "al nassr", "al ittihad"
    ]

    if any(term in texto for term in attacking_terms):
        score += 2.5

    derby_terms = [
        "milan", "inter", "roma", "porto", "benfica",
        "galatasaray", "fenerbahce", "celtic", "rangers",
        "sevilla", "betis"
    ]

    if any(term in texto for term in derby_terms):
        score -= 1.5

    return clamp(score, 58, 78)

def base_corner_score(info):
    score = 60.0
    league_id = info["league_id"]
    texto = f"{info['home_name']} {info['away_name']}".lower()

    score *= LEAGUE_CORNER_PROFILE.get(league_id, 1.00)

    pressing_terms = [
        "liverpool", "arsenal", "atalanta", "leverkusen",
        "ajax", "psv", "feyenoord", "roma", "porto",
        "benfica", "al hilal", "al nassr", "al ittihad"
    ]

    if any(term in texto for term in pressing_terms):
        score += 3.0

    derby_terms = [
        "milan", "inter", "roma", "betis", "sevilla",
        "galatasaray", "fenerbahce", "celtic", "rangers"
    ]

    if any(term in texto for term in derby_terms):
        score -= 0.5

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

    home_attack = comparison.get("att", {}).get("home")
    away_attack = comparison.get("att", {}).get("away")

    if home_attack == "strong":
        score += 1.0
    if away_attack == "strong":
        score += 1.0

    return clamp(score, 58, 84)

def apply_prediction_to_corner_score(base_score, pred):
    score = base_score

    if not pred:
        return clamp(score, 56, 82)

    comparison = pred.get("comparison", {})
    predictions = pred.get("predictions", {})
    advice = (predictions.get("advice") or "").lower()

    home_att = comparison.get("att", {}).get("home")
    away_att = comparison.get("att", {}).get("away")
    home_h2h = comparison.get("h2h", {}).get("home")
    away_h2h = comparison.get("h2h", {}).get("away")

    if home_att == "strong":
        score += 1.5
    if away_att == "strong":
        score += 1.5

    if home_h2h == "strong":
        score += 0.5
    if away_h2h == "strong":
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
        base = base_goal_score(info)
        raw.append({"info": info, "base": base})

    raw.sort(key=lambda x: x["base"], reverse=True)

    enriched = []
    calls = 0

    for item in raw:
        info = item["info"]
        base = item["base"]

        pred = None
        if calls < MAX_PREDICTION_CALLS:
            pred = get_prediction(info["fixture_id"])
            calls += 1

        prob = apply_prediction_to_goal_score(base, pred)

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
            "faixa": confidence(prob)
        })

    return enriched

def build_corner_candidates(matches):
    raw = []

    for m in matches:
        info = get_match_info(m)
        base = base_corner_score(info)
        raw.append({"info": info, "base": base})

    raw.sort(key=lambda x: x["base"], reverse=True)

    enriched = []
    calls = 0

    for item in raw:
        info = item["info"]
        base = item["base"]

        pred = None
        if calls < MAX_PREDICTION_CALLS:
            pred = get_prediction(info["fixture_id"])
            calls += 1

        prob = apply_prediction_to_corner_score(base, pred)

        mercado = "Total de Escanteios: Mais de 8.5"
        if prob < 68:
            mercado = "Total de Escanteios: Mais de 7.5"

        enriched.append({
            "tipo": "ESCANTEIOS",
            "jogo": f"{info['home_name']} x {info['away_name']}",
            "liga": info["league_name"],
            "mercado": mercado,
            "prob": prob,
            "faixa": confidence(prob)
        })

    return enriched

# =========================================================
# RANKINGS
# =========================================================

def top_gols(matches):
    candidatos = build_goal_candidates(matches)
    candidatos = [x for x in candidatos if x["prob"] >= MIN_GOAL_PROB]
    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    ranking = []
    usados = set()

    for item in candidatos:
        if item["jogo"] in usados:
            continue
        usados.add(item["jogo"])
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

def top_escanteios(matches):
    candidatos = build_corner_candidates(matches)
    candidatos = [x for x in candidatos if x["prob"] >= MIN_CORNER_PROB]
    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    ranking = []
    usados = set()

    for item in candidatos:
        if item["jogo"] in usados:
            continue
        usados.add(item["jogo"])
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

def top_fortes(matches):
    gols = build_goal_candidates(matches)
    esc = build_corner_candidates(matches)

    candidatos = []

    for item in gols:
        if item["prob"] >= MIN_STRONG_PROB:
            candidatos.append(item)

    for item in esc:
        if item["prob"] >= MIN_STRONG_PROB:
            candidatos.append(item)

    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    ranking = []
    usados = set()

    for item in candidatos:
        chave = (item["jogo"], item["tipo"])
        if chave in usados:
            continue
        usados.add(chave)
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

def theoretical_value_bets(matches):
    gols = build_goal_candidates(matches)
    esc = build_corner_candidates(matches)

    candidatos = []

    for item in gols + esc:
        if item["prob"] < MIN_VALUE_PROB:
            continue

        odd_justa = fair_odd_from_prob(item["prob"])

        candidatos.append({
            "tipo": item["tipo"],
            "jogo": item["jogo"],
            "liga": item["liga"],
            "mercado": item["mercado"],
            "prob": item["prob"],
            "faixa": item["faixa"],
            "odd_justa": odd_justa,
            "value_faixa": value_band(item["prob"])
        })

    candidatos.sort(key=lambda x: (x["prob"], -x["odd_justa"]), reverse=True)

    ranking = []
    usados = set()

    for item in candidatos:
        chave = (item["jogo"], item["mercado"])
        if chave in usados:
            continue
        usados.add(chave)
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

# =========================================================
# ANALISE POR JOGO
# =========================================================

def find_match_by_text(matches, query):
    q = normalize_text(query)

    if " x " not in q:
        return None

    left, right = q.split(" x ", 1)
    left = left.strip()
    right = right.strip()

    best = None
    best_score = -1

    for m in matches:
        info = get_match_info(m)
        home = normalize_text(info["home_name"])
        away = normalize_text(info["away_name"])

        score = 0

        if left in home:
            score += 3
        if right in away:
            score += 3

        if home.startswith(left):
            score += 2
        if away.startswith(right):
            score += 2

        if left == home:
            score += 3
        if right == away:
            score += 3

        if score > best_score:
            best_score = score
            best = m

    if best_score < 3:
        return None

    return best

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

    msg = f"📊 ANÁLISE DO JOGO\n\n"
    msg += f"{info['home_name']} x {info['away_name']}\n"
    msg += f"{info['league_name']}\n\n"

    msg += f"Over 1.5 gols: {fmt_prob(over15)}% ({confidence(over15)})\n"
    msg += f"Over 2.5 gols: {fmt_prob(over25)}% ({confidence(over25)})\n"
    msg += f"BTTS Sim: {fmt_prob(btts)}% ({confidence(btts)})\n"
    msg += f"Escanteios +7.5: {fmt_prob(corners75)}% ({confidence(corners75)})\n"
    msg += f"Escanteios +8.5: {fmt_prob(corners85)}% ({confidence(corners85)})\n\n"

    msg += f"Melhor mercado:\n{best_market}\n"
    msg += f"Probabilidade: {fmt_prob(best_prob)}%\n"
    msg += f"Faixa: {confidence(best_prob)}"

    return msg

def analyze_match_command(text, matches):
    query = text[len("/analise"):].strip()

    if not query:
        return (
            "Use assim:\n"
            "/analise Time da Casa x Time de Fora\n\n"
            "Exemplo:\n"
            "/analise Al Nassr x Al Hilal"
        )

    match = find_match_by_text(matches, query)

    if not match:
        return (
            "Não encontrei esse jogo na lista de hoje.\n\n"
            "Use assim:\n"
            "/analise Time da Casa x Time de Fora"
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
        prefixo = f"[{item['tipo']}] " if title == "💎 TOP FORTES" else ""
        msg += f"{i}. {prefixo}{item['jogo']}\n"
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

def format_valuebets(ranking):
    if not ranking:
        return (
            "💰 VALUEBETS\n\n"
            "Nenhum value teórico encontrado.\n\n"
            "Obs: esta versão usa odd justa do modelo, sem odd real da casa."
        )

    msg = "💰 VALUEBETS\n\n"
    msg += "Obs: odd justa do modelo, sem odd real da casa.\n\n"

    for i, item in enumerate(ranking, start=1):
        msg += f"{i}. [{item['tipo']}] {item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"Probabilidade: {fmt_prob(item['prob'])}%\n"
        msg += f"Odd justa: {fmt_odd(item['odd_justa'])}\n"
        msg += f"Faixa: {item['value_faixa']}\n"
        msg += f"{item['liga']}\n\n"

    return msg

# =========================================================
# FLASK
# =========================================================

@app.route("/")
def home():
    return "ELITE 13.0 online"

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
            "🤖 ELITE 13.0 online ✅\n\n"
            "Comandos:\n"
            "/teste\n"
            "/topgols\n"
            "/topescanteios\n"
            "/topfortes\n"
            "/tophoje\n"
            "/valuebets\n"
            "/analise Time A x Time B"
        )

    elif text == "/teste":
        send(chat_id, "✅ ELITE 13.0 funcionando")

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
            send(chat_id, format_valuebets(theoretical_value_bets(matches)))
        except Exception as e:
            send(chat_id, f"Erro no valuebets: {type(e).__name__} - {e}")

    elif text.lower().startswith("/analise"):
        try:
            matches = get_matches_today()
            send(chat_id, analyze_match_command(text, matches))
        except Exception as e:
            send(chat_id, f"Erro no analise: {type(e).__name__} - {e}")

    else:
        send(
            chat_id,
            "Comandos:\n"
            "/teste\n"
            "/topgols\n"
            "/topescanteios\n"
            "/topfortes\n"
            "/tophoje\n"
            "/valuebets\n"
            "/analise Time A x Time B"
        )

    return {"ok": True}

try:
    set_webhook()
except Exception:
    pass
