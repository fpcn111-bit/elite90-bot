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

session = requests.Session()
session.headers.update(HEADERS)

# =========================================================
# HELPERS
# =========================================================
def af_get(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
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

def parse_fixture_id(text: str):
    parts = text.strip().split()
    if len(parts) < 2:
        return None

    # aceita:
    # /analise 1416107
    # /analise id 1416107
    # /analise ID 1416107
    ultimo = parts[-1].strip()
    if ultimo.isdigit():
        return ultimo

    # fallback simples para id:1416107
    ultimo = ultimo.replace("id:", "").replace("ID:", "").strip()
    if ultimo.isdigit():
        return ultimo

    return None

# =========================================================
# JOGOS DO DIA
# =========================================================
def jogos_do_dia(max_jogos=100):
    hoje = datetime.date.today().isoformat()

    data = af_get("/fixtures", {
        "date": hoje,
        "timezone": "America/Sao_Paulo"
    })

    jogos = []

    for item in data.get("response", []):
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        league = item.get("league", {})

        status = ((fixture.get("status") or {}).get("short") or "").upper()

        # só jogos que ainda NÃO começaram
        if status not in ("NS", "TBD"):
            continue

        jogos.append({
            "id": fixture.get("id"),
            "home": (teams.get("home") or {}).get("name", "Casa"),
            "away": (teams.get("away") or {}).get("name", "Fora"),
            "home_id": (teams.get("home") or {}).get("id"),
            "away_id": (teams.get("away") or {}).get("id"),
            "league": league.get("name", ""),
            "country": league.get("country", ""),
            "timestamp": fixture.get("timestamp", 0),
            "league_id": league.get("id"),
            "season": league.get("season"),
            "status": status
        })

    jogos.sort(key=lambda x: x["timestamp"])
    return jogos[:max_jogos]

def format_jogos(jogos, limit=100):
    if not jogos:
        return "⚽ Jogos de hoje:\n\nNenhum jogo futuro encontrado para hoje."

    msg = "⚽ Jogos de hoje:\n\n"

    for j in jogos[:limit]:
        msg += f"{j['home']} x {j['away']}\n"
        msg += f"{j['country']} - {j['league']}\n"
        msg += f"id: {j['id']}\n\n"

    msg += "Use: /analise 1416107"
    return msg

# =========================================================
# HISTÓRICO
# =========================================================
def ultimos_jogos_time(team_id, last=10):
    data = af_get("/fixtures", {"team": team_id, "last": last})
    return data.get("response", [])

def confrontos_diretos(home_id, away_id, last=10):
    data = af_get("/fixtures/headtohead", {
        "h2h": f"{home_id}-{away_id}",
        "last": last
    })
    return data.get("response", [])

def predictions(fixture_id):
    try:
        data = af_get("/predictions", {"fixture": fixture_id})
        resp = data.get("response", [])
        return resp[0] if resp else {}
    except Exception:
        return {}

def fixture_statistics(fixture_id):
    try:
        data = af_get("/fixtures/statistics", {"fixture": fixture_id})
        return data.get("response", [])
    except Exception:
        return []

# =========================================================
# EXTRAÇÃO DE MÉDIAS
# =========================================================
def extrair_stats_time(fixtures, team_id):
    jogos_validos = 0
    gols_pro = gols_contra = 0
    over15 = over25 = 0

    for f in fixtures:
        teams = f.get("teams", {})
        goals = f.get("goals", {})

        home_id = (teams.get("home") or {}).get("id")
        away_id = (teams.get("away") or {}).get("id")
        hg = goals.get("home")
        ag = goals.get("away")

        if hg is None or ag is None:
            continue

        jogos_validos += 1

        if team_id == home_id:
            pro = hg
            contra = ag
        else:
            pro = ag
            contra = hg

        gols_pro += pro
        gols_contra += contra

        total_gols = pro + contra
        if total_gols >= 2:
            over15 += 1
        if total_gols >= 3:
            over25 += 1

    if jogos_validos == 0:
        jogos_validos = 1

    return {
        "gols_pro": round(gols_pro / jogos_validos, 2),
        "gols_contra": round(gols_contra / jogos_validos, 2),
        "over15": round(over15 / jogos_validos, 2),
        "over25": round(over25 / jogos_validos, 2),
    }

def extrair_stats_h2h(fixtures):
    jogos_validos = 0
    soma_gols = 0
    over15 = over25 = 0

    for f in fixtures:
        goals = f.get("goals", {})
        hg = goals.get("home")
        ag = goals.get("away")
        if hg is None or ag is None:
            continue

        jogos_validos += 1
        soma_gols += hg + ag

        if hg + ag >= 2:
            over15 += 1
        if hg + ag >= 3:
            over25 += 1

    if jogos_validos == 0:
        jogos_validos = 1

    return {
        "media_gols": round(soma_gols / jogos_validos, 2),
        "over15": round(over15 / jogos_validos, 2),
        "over25": round(over25 / jogos_validos, 2),
    }

# =========================================================
# TOP GOLS
# =========================================================
def calcular_prob_gols(jogo):
    home_last = ultimos_jogos_time(jogo["home_id"], 10)
    away_last = ultimos_jogos_time(jogo["away_id"], 10)
    h2h_last = confrontos_diretos(jogo["home_id"], jogo["away_id"], 10)

    hs = extrair_stats_time(home_last, jogo["home_id"])
    aws = extrair_stats_time(away_last, jogo["away_id"])
    h2h = extrair_stats_h2h(h2h_last)

    media_total = (
        hs["gols_pro"] + hs["gols_contra"] +
        aws["gols_pro"] + aws["gols_contra"]
    ) / 2

    p_over15 = clamp(
        hs["over15"] * 0.34 +
        aws["over15"] * 0.34 +
        h2h["over15"] * 0.20 +
        (0.10 if media_total >= 2.0 else 0.03),
        0.20, 0.92
    )

    p_over25 = clamp(
        hs["over25"] * 0.34 +
        aws["over25"] * 0.34 +
        h2h["over25"] * 0.20 +
        (0.08 if media_total >= 2.4 else 0.02),
        0.15, 0.84
    )

    p_under35 = clamp(0.88 - p_over25 * 0.42, 0.35, 0.90)

    mercados = [
        ("Total de Gols: Mais de 1.5", p_over15),
        ("Total de Gols: Mais de 2.5", p_over25),
        ("Total de Gols: Menos de 3.5", p_under35),
    ]

    return mercados

def gerar_topgols():
    jogos = jogos_do_dia(max_jogos=100)
    ranking = []

    for j in jogos:
        try:
            mercados = calcular_prob_gols(j)
            for nome, prob in mercados:
                ranking.append({
                    "jogo": f"{j['home']} x {j['away']}",
                    "mercado": nome,
                    "prob": prob
                })
        except Exception:
            continue

    ranking.sort(key=lambda x: x["prob"], reverse=True)
    return ranking[:10]

def format_topgols(ranking):
    if not ranking:
        return "🔥 TOP GOLS\n\nNenhuma oportunidade encontrada."

    msg = "🔥 TOP 10 GOLS\n\n"

    for item in ranking:
        msg += f"{item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"Probabilidade: {int(item['prob'] * 100)}%\n\n"

    return msg

# =========================================================
# TOP ESCANTEIOS
# =========================================================
def calcular_prob_escanteios(jogo):
    home_last = ultimos_jogos_time(jogo["home_id"], 10)
    away_last = ultimos_jogos_time(jogo["away_id"], 10)
    h2h_last = confrontos_diretos(jogo["home_id"], jogo["away_id"], 10)
    pred = predictions(jogo["id"])

    hs = extrair_stats_time(home_last, jogo["home_id"])
    aws = extrair_stats_time(away_last, jogo["away_id"])

    pred_percent = pred.get("percent", {}) if pred else {}

    def parse_percent(x):
        try:
            return float(str(x).replace("%", "").strip()) / 100.0
        except Exception:
            return None

    p_home = parse_percent(pred_percent.get("home"))
    p_away = parse_percent(pred_percent.get("away"))

    base_corners = (
        hs["gols_pro"] * 1.1 +
        aws["gols_pro"] * 1.1 +
        hs["over15"] * 1.8 +
        aws["over15"] * 1.8
    )

    bonus = 0
    if p_home is not None and p_away is not None:
        if abs(p_home - p_away) < 0.20:
            bonus = 0.02

    p_over75 = clamp(0.42 + base_corners * 0.045 + bonus, 0.20, 0.88)
    p_over85 = clamp(0.32 + base_corners * 0.040 + bonus, 0.15, 0.82)
    p_over95 = clamp(0.22 + base_corners * 0.035 + bonus, 0.10, 0.74)

    mercados = [
        ("Total de Escanteios: Mais de 7.5", p_over75),
        ("Total de Escanteios: Mais de 8.5", p_over85),
        ("Total de Escanteios: Mais de 9.5", p_over95),
    ]

    return mercados

def gerar_topescanteios():
    jogos = jogos_do_dia(max_jogos=100)
    ranking = []

    for j in jogos:
        try:
            mercados = calcular_prob_escanteios(j)
            for nome, prob in mercados:
                ranking.append({
                    "jogo": f"{j['home']} x {j['away']}",
                    "mercado": nome,
                    "prob": prob
                })
        except Exception:
            continue

    ranking.sort(key=lambda x: x["prob"], reverse=True)
    return ranking[:10]

def format_topescanteios(ranking):
    if not ranking:
        return "🚩 TOP ESCANTEIOS\n\nNenhuma oportunidade encontrada."

    msg = "🚩 TOP 10 ESCANTEIOS\n\n"

    for item in ranking:
        msg += f"{item['jogo']}\n"
        msg += f"{item['mercado']}\n"
        msg += f"Probabilidade: {int(item['prob'] * 100)}%\n\n"

    return msg

# =========================================================
# ANALISE INDIVIDUAL
# =========================================================
def analisar_jogo(fixture_id):
    fixture_data = af_get("/fixtures", {"id": fixture_id})
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

# =========================================================
# ROTAS
# =========================================================
@app.route("/")
def home():
    return "ELITE 10.0 online"

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
            "🤖 ELITE 10.0 online ✅\n\n"
            "Comandos:\n"
            "/teste\n"
            "/jogoshoje\n"
            "/topgols\n"
            "/topescanteios\n"
            "/analise 1416107"
        )

    elif text == "/teste":
        send(chat_id, "✅ ELITE 10.0 funcionando")

    elif text == "/jogoshoje":
        try:
            jogos = jogos_do_dia(max_jogos=100)
            send(chat_id, format_jogos(jogos, limit=100))
        except Exception as e:
            send(chat_id, f"Erro ao buscar jogos: {type(e).__name__} - {e}")

    elif text == "/topgols":
        try:
            ranking = gerar_topgols()
            send(chat_id, format_topgols(ranking))
        except Exception as e:
            send(chat_id, f"Erro no topgols: {type(e).__name__} - {e}")

    elif text == "/topescanteios":
        try:
            ranking = gerar_topescanteios()
            send(chat_id, format_topescanteios(ranking))
        except Exception as e:
            send(chat_id, f"Erro no topescanteios: {type(e).__name__} - {e}")

    elif text.lower().startswith("/analise"):
        fixture_id = parse_fixture_id(text)

        if not fixture_id:
            send(chat_id, "Use: /analise 1416107")
        else:
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
            "/topgols\n"
            "/topescanteios\n"
            "/analise 1416107"
        )

    return {"ok": True}

try:
    set_webhook()
except Exception:
    pass
