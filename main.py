import os
import datetime
import requests
from flask import Flask, request

app = Flask(__name__)

# =========================
# CONFIG
# =========================
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

session = requests.Session()
session.headers.update(HEADERS)

# =========================
# HELPERS
# =========================
def af_get(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    r = session.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

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

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# =========================
# JOGOS DO DIA
# =========================
def jogos_hoje_raw():
    hoje = datetime.date.today().isoformat()
    data = af_get("/fixtures", {"date": hoje})
    return data.get("response", [])

def jogos_hoje_formatados():
    jogos = []

    for item in jogos_hoje_raw():
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        league = item.get("league", {})

        jogos.append({
            "id": fixture.get("id"),
            "home_id": teams.get("home", {}).get("id"),
            "away_id": teams.get("away", {}).get("id"),
            "home": teams.get("home", {}).get("name"),
            "away": teams.get("away", {}).get("name"),
            "league_id": league.get("id"),
            "league": league.get("name"),
            "country": league.get("country"),
            "season": league.get("season")
        })

    return jogos

# =========================
# ESTATÍSTICAS
# =========================
def ultimos_jogos(team_id):
    data = af_get("/fixtures", {"team": team_id, "last": 10})
    return data.get("response", [])

def confrontos(home_id, away_id):
    data = af_get("/fixtures/headtohead", {"h2h": f"{home_id}-{away_id}", "last": 10})
    return data.get("response", [])

def predictions(fixture_id):
    try:
        data = af_get("/predictions", {"fixture": fixture_id})
        resp = data.get("response", [])
        return resp[0] if resp else {}
    except:
        return {}

# =========================
# MODELO PROBABILIDADE
# =========================
def calc_prob(jogo):

    home_last = ultimos_jogos(jogo["home_id"])
    away_last = ultimos_jogos(jogo["away_id"])
    h2h = confrontos(jogo["home_id"], jogo["away_id"])

    gols_home = 0
    gols_away = 0

    for g in home_last:
        gols_home += g["goals"]["home"] or 0

    for g in away_last:
        gols_away += g["goals"]["away"] or 0

    media_home = gols_home / max(len(home_last), 1)
    media_away = gols_away / max(len(away_last), 1)

    p_home = clamp(0.40 + media_home * 0.1 - media_away * 0.05, 0.15, 0.75)
    p_away = clamp(0.30 + media_away * 0.1 - media_home * 0.05, 0.10, 0.55)
    p_draw = 1 - p_home - p_away

    p_dupla_1x = p_home + p_draw
    p_dupla_x2 = p_away + p_draw

    p_over15 = clamp((media_home + media_away) / 3, 0.25, 0.9)
    p_over25 = clamp((media_home + media_away) / 4, 0.15, 0.8)

    mercados = {
        "Dupla Chance: Casa ou Empate": p_dupla_1x,
        "Dupla Chance: Empate ou Fora": p_dupla_x2,
        "Total de Gols: Mais de 1.5": p_over15,
        "Total de Gols: Mais de 2.5": p_over25,
        f"{jogo['home']} Mais de 0.5 Gol": clamp(0.5 + media_home * 0.15, 0.4, 0.9),
        f"{jogo['away']} Mais de 0.5 Gol": clamp(0.4 + media_away * 0.15, 0.3, 0.8),
    }

    return mercados

# =========================
# ANALISE JOGO
# =========================
def analisar_jogo(jogo):

    mercados = calc_prob(jogo)

    ordenado = sorted(
        mercados.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return ordenado[:5]

# =========================
# SCANNER
# =========================
def scanner():

    jogos = jogos_hoje_formatados()

    apostas = []

    for j in jogos:

        try:

            mercados = calc_prob(j)

            for nome, prob in mercados.items():

                if prob >= 0.70:

                    apostas.append({
                        "jogo": f"{j['home']} x {j['away']}",
                        "mercado": nome,
                        "prob": prob
                    })

        except:
            continue

    apostas.sort(key=lambda x: x["prob"], reverse=True)

    return apostas[:10]

# =========================
# TOP10 JOGOS
# =========================
def top10():

    jogos = jogos_hoje_formatados()

    ranking = []

    for j in jogos:

        try:

            melhor = analisar_jogo(j)[0]

            ranking.append({
                "jogo": f"{j['home']} x {j['away']}",
                "mercado": melhor[0],
                "prob": melhor[1]
            })

        except:
            continue

    ranking.sort(key=lambda x: x["prob"], reverse=True)

    return ranking[:10]

# =========================
# FORMATAÇÃO
# =========================
def format_scanner(apostas):

    msg = "🔥 ELITE 10.0 — SCANNER DO DIA\n\n"

    for i, a in enumerate(apostas, start=1):

        msg += f"{i}. {a['jogo']}\n"
        msg += f"{a['mercado']}\n"
        msg += f"Probabilidade: {int(a['prob']*100)}%\n\n"

    return msg

def format_top10(ranking):

    msg = "🔥 TOP 10 JOGOS DO DIA\n\n"

    for i, a in enumerate(ranking, start=1):

        msg += f"{i}. {a['jogo']}\n"
        msg += f"{a['mercado']}\n"
        msg += f"Probabilidade: {int(a['prob']*100)}%\n\n"

    return msg

# =========================
# FLASK
# =========================
@app.route("/")
def home():
    return "ELITE 10.0 online"

@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.get_json(silent=True) or {}
    message = data.get("message", {})
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id:
        return {"ok": True}

    if text == "/teste":
        send(chat_id, "ELITE 10.0 funcionando")

    elif text == "/jogoshoje":

        jogos = jogos_hoje_formatados()

        msg = "Jogos de hoje:\n\n"

        for j in jogos[:20]:
            msg += f"{j['home']} x {j['away']}\n"
            msg += f"id: {j['id']}\n\n"

        send(chat_id, msg)

    elif text.startswith("/analise"):

        parts = text.split()

        if len(parts) < 2:
            send(chat_id, "Use: /analise ID_DO_JOGO")
        else:

            fixture_id = int(parts[1])

            jogos = jogos_hoje_formatados()

            jogo = next((j for j in jogos if j["id"] == fixture_id), None)

            if not jogo:
                send(chat_id, "Jogo não encontrado.")
            else:

                top = analisar_jogo(jogo)

                msg = f"📊 {jogo['home']} x {jogo['away']}\n\n"

                for i, (mercado, prob) in enumerate(top, start=1):
                    msg += f"{i}. {mercado}\n"
                    msg += f"{int(prob*100)}%\n\n"

                send(chat_id, msg)

    elif text == "/top10":

        ranking = top10()

        send(chat_id, format_top10(ranking))

    elif text == "/scanner":

        apostas = scanner()

        send(chat_id, format_scanner(apostas))

    else:

        send(
            chat_id,
            "Comandos:\n"
            "/teste\n"
            "/jogoshoje\n"
            "/analise ID\n"
            "/top10\n"
            "/scanner"
        )

    return {"ok": True}

try:
    set_webhook()
except:
    pass
