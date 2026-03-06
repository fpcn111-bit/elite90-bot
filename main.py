import os
import datetime
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
API_KEY = os.environ.get("API_FOOTBALL_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_KEY
}

def af_get(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    r = requests.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()

def jogos_hoje():
    hoje = datetime.date.today().isoformat()

    data = af_get("/fixtures", {"date": hoje})

    jogos = []

    for item in data["response"]:

        fixture = item["fixture"]
        teams = item["teams"]
        league = item["league"]

        jogos.append({
            "id": fixture["id"],
            "home": teams["home"]["name"],
            "away": teams["away"]["name"],
            "league": league["name"],
            "country": league["country"]
        })

    return jogos

def send(chat_id, text):
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

@app.route("/")
def home():
    return "Elite90 API-Football online"

@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.json

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if text == "/teste":

        send(chat_id, "✅ Bot funcionando com API-Football")

    elif text == "/jogoshoje":

        try:

            jogos = jogos_hoje()

            msg = "⚽ Jogos de hoje:\n\n"

            for j in jogos[:15]:

                msg += f"{j['home']} x {j['away']}\n"
                msg += f"{j['country']} - {j['league']}\n"
                msg += f"id: {j['id']}\n\n"

            send(chat_id, msg)

        except Exception as e:

            send(chat_id, f"Erro API-Football: {e}")

    elif text.startswith("/stats"):

        parts = text.split()

        if len(parts) < 2:

            send(chat_id, "Use: /stats ID_DO_JOGO")

        else:

            fixture_id = parts[1]

            stats = af_get("/fixtures/statistics", {"fixture": fixture_id})

            msg = "📊 Estatísticas:\n\n"

            for team in stats["response"]:

                name = team["team"]["name"]

                msg += f"{name}\n"

                for s in team["statistics"]:

                    msg += f"{s['type']}: {s['value']}\n"

                msg += "\n"

            send(chat_id, msg)

    else:

        send(chat_id, "Comandos:\n/teste\n/jogoshoje\n/stats ID_DO_JOGO")

    return {"ok": True}
