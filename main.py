import os
import datetime
import requests
from zoneinfo import ZoneInfo
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
TIMEZONE = "America/Sao_Paulo"

HEADERS = {
    "x-apisports-key": API_KEY
}

def af_get(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=25)
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

def hoje_sp():
    return datetime.datetime.now(ZoneInfo(TIMEZONE)).date()

def jogos_por_data(data_str):
    data = af_get("/fixtures", {"date": data_str, "timezone": TIMEZONE})
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
            "country": league.get("country", ""),
            "status": ((fixture.get("status") or {}).get("short") or "")
        })

    return jogos

def jogos_hoje():
    base = hoje_sp()
    datas_teste = [
        base.isoformat(),
        (base + datetime.timedelta(days=1)).isoformat(),
        (base - datetime.timedelta(days=1)).isoformat(),
    ]

    for data_str in datas_teste:
        jogos = jogos_por_data(data_str)
        if jogos:
            return data_str, jogos

    return datas_teste[0], []

def format_jogos(data_usada, jogos, limit=15):
    if not jogos:
        return (
            "⚽ Jogos do dia:\n\n"
            f"Nenhum jogo encontrado.\n"
            f"Data usada: {data_usada}\n"
            f"Timezone: {TIMEZONE}\n\n"
            "Use /debugjogos para ver o que a API está retornando."
        )

    msg = f"⚽ Jogos do dia ({data_usada}):\n\n"

    for j in jogos[:limit]:
        msg += f"{j['home']} x {j['away']}\n"
        msg += f"{j['country']} - {j['league']}\n"
        msg += f"id: {j['id']} | status: {j['status']}\n\n"

    msg += "Use: /stats ID_DO_JOGO\n"
    msg += "ou: /analise ID_DO_JOGO"
    return msg

def debug_jogos():
    base = hoje_sp()
    datas_teste = [
        base.isoformat(),
        (base + datetime.timedelta(days=1)).isoformat(),
        (base - datetime.timedelta(days=1)).isoformat(),
    ]

    linhas = [f"🛠 Debug jogos | timezone={TIMEZONE}\n"]

    for d in datas_teste:
        try:
            jogos = jogos_por_data(d)
            linhas.append(f"{d}: {len(jogos)} jogos")
        except Exception as e:
            linhas.append(f"{d}: erro -> {type(e).__name__}: {e}")

    return "\n".join(linhas)

def analisar_jogo(fixture_id):
    fixture_data = af_get("/fixtures", {"id": fixture_id, "timezone": TIMEZONE})
    fixtures = fixture_data.get("response", [])

    if not fixtures:
        return None

    item = fixtures[0]
    teams = item.get("teams", {})
    league = item.get("league", {})

    home = (teams.get("home") or {}).get("name", "Casa")
    away = (teams.get("away") or {}).get("name", "Fora")

    stats_data = af_get("/fixtures/statistics", {"fixture": fixture_id})
    stats_resp = stats_data.get("response", [])

    lines = []
    lines.append(f"📊 {home} x {away}\n")
    lines.append(f"🏆 {league.get('country', '')} - {league.get('name', '')}\n")

    if not stats_resp:
        lines.append("Ainda não há estatísticas disponíveis para esse jogo.")
        return "\n".join(lines)

    for team_block in stats_resp:
        team_name = (team_block.get("team") or {}).get("name", "Time")
        lines.append(f"{team_name}:")

        for stat in team_block.get("statistics", []):
            stat_type = stat.get("type")
            stat_value = stat.get("value")
            if stat_value is not None:
                lines.append(f"- {stat_type}: {stat_value}")

        lines.append("")

    return "\n".join(lines)

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

    if text in ("/start", "start"):
        send(
            chat_id,
            "🤖 ELITE online ✅\n\n"
            "Comandos:\n"
            "/teste\n"
            "/jogoshoje\n"
            "/stats ID_DO_JOGO\n"
            "/analise ID_DO_JOGO\n"
            "/debugjogos"
        )

    elif text == "/teste":
        send(chat_id, "✅ ELITE funcionando")

    elif text == "/jogoshoje":
        try:
            data_usada, jogos = jogos_hoje()
            send(chat_id, format_jogos(data_usada, jogos, limit=15))
        except Exception as e:
            send(chat_id, f"Erro ao buscar jogos: {type(e).__name__} - {e}")

    elif text == "/debugjogos":
        try:
            send(chat_id, debug_jogos())
        except Exception as e:
            send(chat_id, f"Erro no debug: {type(e).__name__} - {e}")

    elif text.startswith("/stats") or text.startswith("/analise"):
        parts = text.split()

        if len(parts) < 2:
            send(chat_id, "Use: /stats ID_DO_JOGO")
        else:
            fixture_id = parts[1]
            try:
                resultado = analisar_jogo(fixture_id)
                if not resultado:
                    send(chat_id, "Jogo não encontrado.")
                else:
                    send(chat_id, resultado)
            except Exception as e:
                send(chat_id, f"Erro na análise: {type(e).__name__} - {e}")

    else:
        send(
            chat_id,
            "Comandos:\n"
            "/teste\n"
            "/jogoshoje\n"
            "/stats ID_DO_JOGO\n"
            "/analise ID_DO_JOGO\n"
            "/debugjogos"
        )

    return {"ok": True}

try:
    set_webhook()
except Exception:
    pass
