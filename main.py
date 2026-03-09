import os
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("Faltou TELEGRAM_TOKEN")

if not FOOTBALL_DATA_KEY:
    raise RuntimeError("Faltou FOOTBALL_DATA_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
BASE_URL = "https://api.football-data.org/v4"

HEADERS = {
    "X-Auth-Token": FOOTBALL_DATA_KEY
}

session = requests.Session()
session.headers.update(HEADERS)

# =========================================================
# CONFIG ELITE 10.2
# =========================================================
ALLOWED_COMP_CODES = {"DED", "BL1", "PD", "SA", "FL1", "PPL", "ELC"}

LEAGUE_GOAL_PROFILE = {
    "DED": 1.18,   # Eredivisie
    "BL1": 1.12,   # Bundesliga
    "PD": 0.98,    # LaLiga
    "SA": 1.02,    # Serie A
    "FL1": 1.04,   # Ligue 1
    "PPL": 1.03,   # Primeira Liga
    "ELC": 1.01,   # Championship
}

LEAGUE_CORNER_PROFILE = {
    "DED": 1.02,
    "BL1": 1.08,
    "PD": 1.10,
    "SA": 1.03,
    "FL1": 1.01,
    "PPL": 0.98,
    "ELC": 1.06,
}

MIN_GOAL_PROB = 67
MIN_CORNER_PROB = 65
MIN_STRONG_PROB = 70

standings_cache = {}

# =========================================================
# HELPERS
# =========================================================
def fd_get(path, params=None):
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
    webhook_url = f"{PUBLIC_URL}/webhook"
    requests.post(
        f"{TELEGRAM_API}/setWebhook",
        json={"url": webhook_url},
        timeout=30
    )

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def fmt_prob(v):
    return int(round(v))

def get_confidence_label(prob):
    p = fmt_prob(prob)
    if p >= 75:
        return "MUITO FORTE"
    elif p >= 70:
        return "BOA"
    elif p >= 65:
        return "ACEITÁVEL"
    return "FRACA"

# =========================================================
# DADOS
# =========================================================
def get_matches_today():
    data = fd_get("/matches", {"status": "SCHEDULED"})
    matches = data.get("matches", [])
    out = []

    for m in matches:
        comp = m.get("competition", {})
        code = comp.get("code", "")

        if code not in ALLOWED_COMP_CODES:
            continue

        out.append(m)

    return out

def get_competition_standings(comp_code):
    if comp_code in standings_cache:
        return standings_cache[comp_code]

    try:
        data = fd_get(f"/competitions/{comp_code}/standings")
        standings_cache[comp_code] = data
        return data
    except Exception:
        standings_cache[comp_code] = None
        return None

def get_team_positions(comp_code):
    data = get_competition_standings(comp_code)
    positions = {}

    if not data:
        return positions

    try:
        standings = data.get("standings", [])
        for block in standings:
            table = block.get("table", [])
            for row in table:
                team = row.get("team", {})
                positions[team.get("id")] = row.get("position")
    except Exception:
        return {}

    return positions

def get_match_info(match):
    comp = match.get("competition", {})
    home = match.get("homeTeam", {})
    away = match.get("awayTeam", {})

    return {
        "id": match.get("id"),
        "status": match.get("status", ""),
        "competition_name": comp.get("name", ""),
        "competition_code": comp.get("code", ""),
        "home_name": home.get("name", "Casa"),
        "away_name": away.get("name", "Fora"),
        "home_id": home.get("id"),
        "away_id": away.get("id"),
        "utcDate": match.get("utcDate", "")
    }

# =========================================================
# SCORING GOLS
# =========================================================
def calc_goal_score(match_info):
    comp_code = match_info["competition_code"]
    home_id = match_info["home_id"]
    away_id = match_info["away_id"]

    league_factor = LEAGUE_GOAL_PROFILE.get(comp_code, 1.00)
    positions = get_team_positions(comp_code)

    home_pos = positions.get(home_id)
    away_pos = positions.get(away_id)

    score = 63.0
    score *= league_factor

    if home_pos and away_pos:
        diff = abs(home_pos - away_pos)

        if diff <= 4:
            score += 2.5
        elif diff <= 8:
            score += 3.5
        elif diff <= 12:
            score += 2.0
        else:
            score += 0.5

        if home_pos <= 6 or away_pos <= 6:
            score += 1.5

        if home_pos >= 15 and away_pos >= 15:
            score -= 1.0

    derby_terms = [
        "milan", "inter", "porto", "benfica", "roma",
        "sevilla", "betis", "lyon"
    ]

    texto = f"{match_info['home_name']} {match_info['away_name']}".lower()
    if any(term in texto for term in derby_terms):
        score -= 1.5

    score = clamp(score, 58, 82)

    mercado = "Total de Gols: Mais de 1.5"

    if comp_code in ("PD", "ELC") and score < 69:
        mercado = "Total de Gols: Menos de 3.5"
        score = clamp(score + 3, 60, 84)

    return mercado, score

# =========================================================
# SCORING ESCANTEIOS
# =========================================================
def calc_corner_score(match_info):
    comp_code = match_info["competition_code"]
    home_id = match_info["home_id"]
    away_id = match_info["away_id"]

    league_factor = LEAGUE_CORNER_PROFILE.get(comp_code, 1.00)
    positions = get_team_positions(comp_code)

    home_pos = positions.get(home_id)
    away_pos = positions.get(away_id)

    score = 60.0
    score *= league_factor

    if home_pos and away_pos:
        diff = abs(home_pos - away_pos)

        if diff <= 3:
            score += 5.0
        elif diff <= 6:
            score += 4.0
        elif diff <= 10:
            score += 2.0
        else:
            score -= 1.0

        if diff >= 12:
            score += 1.5

        if home_pos <= 5 or away_pos <= 5:
            score += 1.0

    texto = f"{match_info['home_name']} {match_info['away_name']}".lower()
    pressing_terms = [
        "feyenoord", "frankfurt", "roma", "porto", "benfica",
        "betis", "twente", "milan", "inter", "lyon"
    ]

    if any(term in texto for term in pressing_terms):
        score += 1.5

    derby_terms = ["milan", "inter", "roma", "betis", "sevilla"]
    if any(term in texto for term in derby_terms):
        score -= 0.5

    score = clamp(score, 56, 79)

    mercado = "Total de Escanteios: Mais de 8.5"
    if score < 68:
        mercado = "Total de Escanteios: Mais de 7.5"

    return mercado, score

# =========================================================
# RANKINGS
# =========================================================
def top_gols(matches):
    ranking = []
    jogos_usados = set()
    candidatos = []

    for m in matches:
        info = get_match_info(m)
        try:
            mercado, prob = calc_goal_score(info)

            if prob < MIN_GOAL_PROB:
                continue

            candidatos.append({
                "tipo": "GOLS",
                "jogo": f"{info['home_name']} x {info['away_name']}",
                "liga": info["competition_name"],
                "mercado": mercado,
                "prob": prob,
                "faixa": get_confidence_label(prob)
            })
        except Exception:
            continue

    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    for item in candidatos:
        if item["jogo"] in jogos_usados:
            continue
        jogos_usados.add(item["jogo"])
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

def top_escanteios(matches):
    ranking = []
    jogos_usados = set()
    candidatos = []

    for m in matches:
        info = get_match_info(m)
        try:
            mercado, prob = calc_corner_score(info)

            if prob < MIN_CORNER_PROB:
                continue

            candidatos.append({
                "tipo": "ESCANTEIOS",
                "jogo": f"{info['home_name']} x {info['away_name']}",
                "liga": info["competition_name"],
                "mercado": mercado,
                "prob": prob,
                "faixa": get_confidence_label(prob)
            })
        except Exception:
            continue

    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    for item in candidatos:
        if item["jogo"] in jogos_usados:
            continue
        jogos_usados.add(item["jogo"])
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

def top_fortes(matches):
    ranking = []
    usados = set()
    candidatos = []

    for m in matches:
        info = get_match_info(m)

        try:
            mercado_g, prob_g = calc_goal_score(info)
            if prob_g >= MIN_STRONG_PROB:
                candidatos.append({
                    "tipo": "GOLS",
                    "jogo": f"{info['home_name']} x {info['away_name']}",
                    "liga": info["competition_name"],
                    "mercado": mercado_g,
                    "prob": prob_g,
                    "faixa": get_confidence_label(prob_g)
                })
        except Exception:
            pass

        try:
            mercado_c, prob_c = calc_corner_score(info)
            if prob_c >= MIN_STRONG_PROB:
                candidatos.append({
                    "tipo": "ESCANTEIOS",
                    "jogo": f"{info['home_name']} x {info['away_name']}",
                    "liga": info["competition_name"],
                    "mercado": mercado_c,
                    "prob": prob_c,
                    "faixa": get_confidence_label(prob_c)
                })
        except Exception:
            pass

    candidatos.sort(key=lambda x: x["prob"], reverse=True)

    for item in candidatos:
        chave = (item["jogo"], item["tipo"])
        if chave in usados:
            continue
        usados.add(chave)
        ranking.append(item)
        if len(ranking) >= 10:
            break

    return ranking

# =========================================================
# FORMATTERS
# =========================================================
def format_topgols(matches):
    ranking = top_gols(matches)

    if not ranking:
        return "🔥 TOP GOLS\n\nNenhuma oportunidade forte encontrada."

    msg = f"🔥 TOP {len(ranking)} GOLS\n\n"

    for i, item in enumerate(ranking, start=1):
        msg += f"{i}. {item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"Probabilidade: {fmt_prob(item['prob'])}%\n"
        msg += f"Faixa: {item['faixa']}\n"
        msg += f"{item['liga']}\n\n"

    return msg

def format_topescanteios(matches):
    ranking = top_escanteios(matches)

    if not ranking:
        return "🚩 TOP ESCANTEIOS\n\nNenhuma oportunidade forte encontrada."

    msg = f"🚩 TOP {len(ranking)} ESCANTEIOS\n\n"

    for i, item in enumerate(ranking, start=1):
        msg += f"{i}. {item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"Probabilidade: {fmt_prob(item['prob'])}%\n"
        msg += f"Faixa: {item['faixa']}\n"
        msg += f"{item['liga']}\n\n"

    return msg

def format_topfortes(matches):
    ranking = top_fortes(matches)

    if not ranking:
        return "💎 TOP FORTES\n\nNenhuma oportunidade premium encontrada hoje."

    msg = f"💎 TOP {len(ranking)} FORTES\n\n"

    for i, item in enumerate(ranking, start=1):
        msg += f"{i}. [{item['tipo']}] {item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"Probabilidade: {fmt_prob(item['prob'])}%\n"
        msg += f"Faixa: {item['faixa']}\n"
        msg += f"{item['liga']}\n\n"

    return msg

# =========================================================
# FLASK
# =========================================================
@app.route("/")
def home():
    return "ELITE 10.2 online"

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
            "🤖 ELITE 10.2 online ✅\n\n"
            "Comandos:\n"
            "/teste\n"
            "/topgols\n"
            "/topescanteios\n"
            "/topfortes"
        )

    elif text == "/teste":
        send(chat_id, "✅ ELITE 10.2 funcionando")

    elif text == "/topgols":
        try:
            matches = get_matches_today()
            send(chat_id, format_topgols(matches))
        except Exception as e:
            send(chat_id, f"Erro no topgols: {type(e).__name__} - {e}")

    elif text == "/topescanteios":
        try:
            matches = get_matches_today()
            send(chat_id, format_topescanteios(matches))
        except Exception as e:
            send(chat_id, f"Erro no topescanteios: {type(e).__name__} - {e}")

    elif text == "/topfortes":
        try:
            matches = get_matches_today()
            send(chat_id, format_topfortes(matches))
        except Exception as e:
            send(chat_id, f"Erro no topfortes: {type(e).__name__} - {e}")

    else:
        send(
            chat_id,
            "Comandos:\n"
            "/teste\n"
            "/topgols\n"
            "/topescanteios\n"
            "/topfortes"
        )

    return {"ok": True}

try:
    set_webhook()
except Exception:
    pass
