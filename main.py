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

def agora_sp():
    return datetime.datetime.now(ZoneInfo(TIMEZONE))

def hoje_sp():
    return agora_sp().date()

def normalizar_jogo(item, data_ref):
    fixture = item.get("fixture", {})
    teams = item.get("teams", {})
    league = item.get("league", {})

    ts = fixture.get("timestamp") or 0
    status = ((fixture.get("status") or {}).get("short") or "").upper()

    try:
        dt_local = datetime.datetime.fromtimestamp(ts, ZoneInfo(TIMEZONE))
        hora_local = dt_local.strftime("%H:%M")
        data_local = dt_local.date().isoformat()
    except Exception:
        hora_local = "--:--"
        data_local = data_ref

    return {
        "id": fixture.get("id"),
        "home": (teams.get("home") or {}).get("name", "Casa"),
        "away": (teams.get("away") or {}).get("name", "Fora"),
        "league": league.get("name", ""),
        "country": league.get("country", ""),
        "status": status,
        "timestamp": ts,
        "hora_local": hora_local,
        "data_local": data_local,
    }

def jogos_por_data(data_str):
    data = af_get("/fixtures", {
        "date": data_str,
        "timezone": TIMEZONE
    })
    jogos = []

    for item in data.get("response", []):
        jogos.append(normalizar_jogo(item, data_str))

    return jogos

def jogos_hoje():
    hoje = hoje_sp()
    amanha = hoje + datetime.timedelta(days=1)

    jogos_hoje_lista = jogos_por_data(hoje.isoformat())
    jogos_amanha_lista = jogos_por_data(amanha.isoformat())

    todos = jogos_hoje_lista + jogos_amanha_lista

    # remove duplicados por id
    unicos = {}
    for j in todos:
        jid = j.get("id")
        if jid is not None:
            unicos[jid] = j

    jogos = list(unicos.values())
    jogos.sort(key=lambda x: x["timestamp"])

    return hoje.isoformat(), amanha.isoformat(), jogos

def format_jogos(data_hoje, data_amanha, jogos, limit=30):
    if not jogos:
        return (
            "⚽ Jogos do dia:\n\n"
            "Nenhum jogo encontrado.\n"
            f"Hoje: {data_hoje}\n"
            f"Amanhã: {data_amanha}\n"
            f"Timezone: {TIMEZONE}"
        )

    linhas = [f"⚽ Jogos encontrados ({TIMEZONE}):\n"]

    for j in jogos[:limit]:
        marcador = "Hoje"
        if j["data_local"] == data_amanha:
            marcador = "Amanhã"

        linhas.append(f"{j['home']} x {j['away']}")
        linhas.append(f"{j['country']} - {j['league']}")
        linhas.append(f"{marcador}, {j['hora_local']} | id: {j['id']} | status: {j['status']}")
        linhas.append("")

    linhas.append("Use: /stats ID_DO_JOGO")
    linhas.append("ou: /analise ID_DO_JOGO")

    return "\n".join(linhas)

def debug_jogos():
    hoje = hoje_sp()
    amanha = hoje + datetime.timedelta(days=1)
    ontem = hoje - datetime.timedelta(days=1)

    datas = [ontem.isoformat(), hoje.isoformat(), amanha.isoformat()]
    linhas = [f"🛠 Debug jogos | timezone={TIMEZONE}\n"]

    for d in datas:
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
            data_hoje, data_amanha, jogos = jogos_hoje()
            send(chat_id, format_jogos(data_hoje, data_amanha, jogos, limit=30))
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
