import os
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
# LIGAS PERMITIDAS
# =========================================================

ALLOWED_LEAGUES = {

    # Inglaterra
    39,

    # Espanha
    140,

    # Itália
    135,

    # Alemanha
    78,

    # França
    61,

    # Portugal
    94,

    # Holanda
    88,

    # Bélgica
    144,

    # Turquia
    203,

    # Suíça
    207,

    # Áustria
    218,

    # Dinamarca
    119,

    # Escócia
    179,

    # Brasil
    71,

    # Argentina
    128,

    # MLS
    253,

    # Libertadores
    13,

    # Sul-Americana
    11,

    # Arabia Saudita
    307

}

# =========================================================
# PROBABILIDADES
# =========================================================

MIN_GOAL_PROB = 66
MIN_CORNER_PROB = 64
MIN_STRONG_PROB = 70

# =========================================================
# HELPERS
# =========================================================

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

def confidence(prob):

    p = fmt_prob(prob)

    if p >= 75:
        return "MUITO FORTE"

    if p >= 70:
        return "BOA"

    if p >= 65:
        return "ACEITÁVEL"

    return "FRACA"

# =========================================================
# BUSCAR JOGOS DO DIA
# =========================================================

def get_matches_today():

    today = datetime.utcnow().strftime("%Y-%m-%d")

    url = f"{BASE_URL}/fixtures"

    params = {
        "date": today
    }

    r = session.get(url, params=params, timeout=30)

    data = r.json()

    matches = []

    for m in data.get("response", []):

        league_id = m["league"]["id"]

        if league_id not in ALLOWED_LEAGUES:
            continue

        status = m["fixture"]["status"]["short"]

        if status not in ("NS","TBD"):
            continue

        matches.append(m)

    return matches

# =========================================================
# ANALISE GOLS
# =========================================================

def goal_score(match):

    home = match["teams"]["home"]["name"]
    away = match["teams"]["away"]["name"]

    score = 63

    big_attack = [
        "ajax","psv","feyenoord","bayern","leverkusen",
        "atalanta","porto","benfica","sporting",
        "manchester city","arsenal","liverpool",
        "al hilal","al nassr"
    ]

    texto = f"{home} {away}".lower()

    if any(t in texto for t in big_attack):
        score += 3

    return score

# =========================================================
# ANALISE ESCANTEIOS
# =========================================================

def corner_score(match):

    home = match["teams"]["home"]["name"]
    away = match["teams"]["away"]["name"]

    score = 60

    pressing = [
        "liverpool","arsenal","atalanta","leverkusen",
        "ajax","psv","feyenoord","roma","porto",
        "benfica","al hilal","al nassr"
    ]

    texto = f"{home} {away}".lower()

    if any(t in texto for t in pressing):
        score += 4

    return score

# =========================================================
# RANKINGS
# =========================================================

def top_gols(matches):

    ranking = []

    for m in matches:

        score = goal_score(m)

        if score < MIN_GOAL_PROB:
            continue

        home = m["teams"]["home"]["name"]
        away = m["teams"]["away"]["name"]

        liga = m["league"]["name"]

        ranking.append({

            "jogo": f"{home} x {away}",
            "liga": liga,
            "mercado": "Total de Gols: Mais de 1.5",
            "prob": score,
            "faixa": confidence(score)

        })

    ranking.sort(key=lambda x: x["prob"], reverse=True)

    return ranking[:10]


def top_corners(matches):

    ranking = []

    for m in matches:

        score = corner_score(m)

        if score < MIN_CORNER_PROB:
            continue

        home = m["teams"]["home"]["name"]
        away = m["teams"]["away"]["name"]

        liga = m["league"]["name"]

        ranking.append({

            "jogo": f"{home} x {away}",
            "liga": liga,
            "mercado": "Total de Escanteios: Mais de 8.5",
            "prob": score,
            "faixa": confidence(score)

        })

    ranking.sort(key=lambda x: x["prob"], reverse=True)

    return ranking[:10]


def top_fortes(matches):

    ranking = []

    for m in matches:

        g = goal_score(m)
        c = corner_score(m)

        home = m["teams"]["home"]["name"]
        away = m["teams"]["away"]["name"]
        liga = m["league"]["name"]

        if g >= MIN_STRONG_PROB:

            ranking.append({

                "jogo": f"{home} x {away}",
                "liga": liga,
                "mercado": "Total de Gols: Mais de 1.5",
                "prob": g,
                "faixa": confidence(g)

            })

        if c >= MIN_STRONG_PROB:

            ranking.append({

                "jogo": f"{home} x {away}",
                "liga": liga,
                "mercado": "Total de Escanteios: Mais de 8.5",
                "prob": c,
                "faixa": confidence(c)

            })

    ranking.sort(key=lambda x: x["prob"], reverse=True)

    return ranking[:10]

# =========================================================
# FORMATAR
# =========================================================

def format_list(title, ranking):

    if not ranking:
        return f"{title}\n\nNenhuma oportunidade encontrada."

    msg = f"{title}\n\n"

    for i, r in enumerate(ranking, start=1):

        msg += f"{i}. {r['jogo']}\n"
        msg += f"{r['mercado']}\n"
        msg += f"Probabilidade: {r['prob']}%\n"
        msg += f"Faixa: {r['faixa']}\n"
        msg += f"{r['liga']}\n\n"

    return msg

# =========================================================
# FLASK
# =========================================================

@app.route("/")
def home():
    return "ELITE 12.0 online"


@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.get_json(silent=True) or {}

    message = data.get("message", {})

    chat_id = (message.get("chat") or {}).get("id")

    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}

    if text in ("/start","start"):

        send(
            chat_id,
            "🤖 ELITE 12.0 online\n\n"
            "Comandos:\n"
            "/teste\n"
            "/topgols\n"
            "/topescanteios\n"
            "/topfortes"
        )

    elif text == "/teste":

        send(chat_id,"✅ ELITE 12.0 funcionando")

    elif text == "/topgols":

        matches = get_matches_today()

        send(chat_id,
        format_list("🔥 TOP GOLS", top_gols(matches)))

    elif text == "/topescanteios":

        matches = get_matches_today()

        send(chat_id,
        format_list("🚩 TOP ESCANTEIOS", top_corners(matches)))

    elif text == "/topfortes":

        matches = get_matches_today()

        send(chat_id,
        format_list("💎 TOP FORTES", top_fortes(matches)))

    else:

        send(chat_id,
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
