import os
import datetime
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
API_KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("Faltou TELEGRAM_TOKEN")

if not API_KEY:
    raise RuntimeError("Faltou API_FOOTBALL_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_KEY
}

def af_get(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def jogos_hoje():
    hoje = datetime.date.today().isoformat()
    data = af_get("/fixtures", {"date": hoje})
    jogos = []

    for item in data.get("response", []):
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        league = item.get("league", {})

        jogos.append({
            "id": fixture.get("id"),
            "home": (teams.get("home") or {}).get("name", "Casa"),
            "away": (teams.get("away") or {}).get("name", "Fora"),
            "league": league.get("name", ""),
            "country": league.get("country", "")
        })

    return jogos

def send(chat_id, text):
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=25
    )

def set_webhook():
    if not PUBLIC_URL:
        return
    webhook_url = f"{PUBLIC_URL}/webhook"
    requests.post(
        f"{TELEGRAM_API}/setWebhook",
        json={"url": webhook_url},
        timeout=25
    )

@app.route("/")
def home():
    return "Elite90 API-Football online"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message", {})
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}

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
            try:
                stats = af_get("/fixtures/statistics", {"fixture": fixture_id})
                msg = "📊 Estatísticas:\n\n"

                for team in stats.get("response", []):
                    name = (team.get("team") or {}).get("name", "Time")
                    msg += f"{name}\n"

                    for s in team.get("statistics", []):
                        msg += f"{s.get('type')}: {s.get('value')}\n"

                    msg += "\n"

                send(chat_id, msg)

            except Exception as e:
                send(chat_id, f"Erro API-Football stats: {e}")

    else:
        send(chat_id, "Comandos:\n/teste\n/jogoshoje\n/stats ID_DO_JOGO")

    return {"ok": True}

try:
    set_webhook()
except Exception:
    pass
