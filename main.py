import os
import datetime
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
API_KEY = os.environ.get("API_FOOTBALL_KEY")
PUBLIC_URL = os.environ.get("PUBLIC_URL")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_KEY
}

def af_get(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

# =========================
# PEGAR TODOS JOGOS DO DIA
# =========================

def jogos_do_dia():

    hoje = datetime.date.today().isoformat()

    data = af_get("/fixtures", {
        "date": hoje,
        "timezone": "America/Sao_Paulo"
    })

    jogos = []

    for item in data.get("response", []):

        fixture = item["fixture"]
        teams = item["teams"]
        league = item["league"]

        status = fixture["status"]["short"]

        if status == "FT":
            continue

        jogos.append({
            "id": fixture["id"],
            "home": teams["home"]["name"],
            "away": teams["away"]["name"],
            "league": league["name"],
            "country": league["country"],
            "timestamp": fixture["timestamp"]
        })

    return jogos

# =========================
# ANALISE SIMPLES GOLS
# =========================

def prob_gols(fixture_id):

    stats = af_get("/fixtures/statistics", {"fixture": fixture_id})

    shots = 0

    for team in stats["response"]:
        for s in team["statistics"]:
            if s["type"] == "Total Shots" and s["value"]:
                shots += int(s["value"])

    if shots >= 25:
        prob = 80
    elif shots >= 20:
        prob = 72
    elif shots >= 15:
        prob = 65
    else:
        prob = 55

    return prob

# =========================
# ANALISE ESCANTEIOS
# =========================

def prob_escanteios(fixture_id):

    stats = af_get("/fixtures/statistics", {"fixture": fixture_id})

    corners = 0

    for team in stats["response"]:
        for s in team["statistics"]:
            if s["type"] == "Corner Kicks" and s["value"]:
                corners += int(s["value"])

    if corners >= 12:
        prob = 78
    elif corners >= 10:
        prob = 72
    elif corners >= 8:
        prob = 65
    else:
        prob = 55

    return prob

# =========================
# TELEGRAM
# =========================

def send(chat_id, text):

    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30
    )

# =========================
# WEBHOOK
# =========================

@app.route("/")
def home():
    return "ELITE 10.0 online"

@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.json
    message = data.get("message", {})

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id:
        return {"ok": True}

# =========================
# COMANDOS
# =========================

    if text == "/teste":

        send(chat_id, "✅ ELITE 10.0 funcionando")

# =========================
# LISTAR JOGOS
# =========================

    elif text == "/jogoshoje":

        jogos = jogos_do_dia()

        msg = "⚽ Jogos de hoje:\n\n"

        for j in jogos[:30]:

            msg += f"{j['home']} x {j['away']}\n"
            msg += f"{j['country']} - {j['league']}\n"
            msg += f"id: {j['id']}\n\n"

        send(chat_id, msg)

# =========================
# TOP GOLS
# =========================

    elif text == "/topgols":

        jogos = jogos_do_dia()

        ranking = []

        for j in jogos:

            try:

                p = prob_gols(j["id"])

                ranking.append((p, j))

            except:
                pass

        ranking.sort(reverse=True)

        msg = "🔥 TOP 10 GOLS\n\n"

        for r in ranking[:10]:

            jogo = r[1]

            msg += f"{jogo['home']} x {jogo['away']}\n"
            msg += f"Total de Gols: Mais de 1.5\n"
            msg += f"Probabilidade: {r[0]}%\n\n"

        send(chat_id, msg)

# =========================
# TOP ESCANTEIOS
# =========================

    elif text == "/topescanteios":

        jogos = jogos_do_dia()

        ranking = []

        for j in jogos:

            try:

                p = prob_escanteios(j["id"])

                ranking.append((p, j))

            except:
                pass

        ranking.sort(reverse=True)

        msg = "🚩 TOP 10 ESCANTEIOS\n\n"

        for r in ranking[:10]:

            jogo = r[1]

            msg += f"{jogo['home']} x {jogo['away']}\n"
            msg += f"Total de Escanteios: Mais de 8.5\n"
            msg += f"Probabilidade: {r[0]}%\n\n"

        send(chat_id, msg)

# =========================
# ANALISE INDIVIDUAL
# =========================

    elif text.startswith("/analise"):

        try:

            fixture_id = text.split()[-1]

            stats = af_get("/fixtures/statistics", {"fixture": fixture_id})

            msg = "📊 Estatísticas\n\n"

            for team in stats["response"]:

                name = team["team"]["name"]

                msg += f"{name}\n"

                for s in team["statistics"]:

                    msg += f"{s['type']}: {s['value']}\n"

                msg += "\n"

            send(chat_id, msg)

        except:

            send(chat_id, "Jogo não encontrado")

    else:

        send(chat_id,
        "Comandos:\n"
        "/teste\n"
        "/jogoshoje\n"
        "/topgols\n"
        "/topescanteios\n"
        "/analise ID")

    return {"ok": True}
