import os
import datetime
import requests
from flask import Flask, request

app = Flask(__name__)

# =====================================
# CONFIG
# =====================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
API_KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("Faltou TELEGRAM_TOKEN")

if not API_KEY:
    raise RuntimeError("Faltou API_FOOTBALL_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
BASE_URL = "https://v3.football.api-sports.io"

session = requests.Session()
session.headers.update({
    "x-apisports-key": API_KEY
})

# =====================================
# HELPERS
# =====================================
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

# =====================================
# JOGOS DO DIA
# =====================================
def jogos_hoje_raw():
    hoje = datetime.date.today().isoformat()
    data = af_get("/fixtures", {"date": hoje})
    return data.get("response", [])

def jogo_eh_bloqueado(jogo):
    texto = f"{jogo['country']} {jogo['league']} {jogo['home']} {jogo['away']}".lower()

    bloqueados = [
        "u17", "u18", "u19", "u20", "u21", "u23",
        "reserve", "reserves"
    ]

    for b in bloqueados:
        if b in texto:
            return True
    return False

def jogos_hoje_formatados(limit=None):
    jogos = []

    for item in jogos_hoje_raw():
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        league = item.get("league", {})

        status = ((fixture.get("status") or {}).get("short") or "").upper()
        if status in ("FT", "AET", "PEN", "CANC", "PST", "ABD", "AWD", "WO"):
            continue

        jogo = {
            "id": fixture.get("id"),
            "home_id": (teams.get("home") or {}).get("id"),
            "away_id": (teams.get("away") or {}).get("id"),
            "home": (teams.get("home") or {}).get("name", "Casa"),
            "away": (teams.get("away") or {}).get("name", "Fora"),
            "league_id": league.get("id"),
            "league": league.get("name", ""),
            "country": league.get("country", ""),
            "season": league.get("season"),
            "timestamp": fixture.get("timestamp", 0),
        }

        if jogo_eh_bloqueado(jogo):
            continue

        jogos.append(jogo)

    jogos.sort(key=lambda x: x["timestamp"])

    if limit:
        return jogos[:limit]
    return jogos

def format_jogos(jogos, limit=20):
    linhas = ["⚽️ Jogos de hoje:\n"]
    for j in jogos[:limit]:
        linhas.append(f"{j['home']} x {j['away']}")
        linhas.append(f"{j['country']} - {j['league']}")
        linhas.append(f"id: {j['id']}\n")
    linhas.append("Use: /analise ID_DO_JOGO")
    return "\n".join(linhas)

# =====================================
# DADOS POR TIME / H2H / TABELA
# =====================================
def ultimos_jogos_time(team_id, last=10):
    data = af_get("/fixtures", {"team": team_id, "last": last})
    return data.get("response", [])

def confrontos_diretos(home_id, away_id, last=10):
    data = af_get("/fixtures/headtohead", {
        "h2h": f"{home_id}-{away_id}",
        "last": last
    })
    return data.get("response", [])

def standings(league_id, season):
    try:
        data = af_get("/standings", {"league": league_id, "season": season})
        return data.get("response", [])
    except Exception:
        return []

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

# =====================================
# EXTRAÇÃO DE MÉDIAS
# =====================================
def extrair_stats_time(fixtures, team_id):
    jogos_validos = 0
    wins = draws = losses = 0
    gols_pro = gols_contra = 0
    over15 = over25 = btts = 0

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

        if pro > contra:
            wins += 1
        elif pro == contra:
            draws += 1
        else:
            losses += 1

        total_gols = pro + contra
        if total_gols >= 2:
            over15 += 1
        if total_gols >= 3:
            over25 += 1
        if pro > 0 and contra > 0:
            btts += 1

    if jogos_validos == 0:
        jogos_validos = 1

    return {
        "jogos": jogos_validos,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "gols_pro": round(gols_pro / jogos_validos, 2),
        "gols_contra": round(gols_contra / jogos_validos, 2),
        "over15": round(over15 / jogos_validos, 2),
        "over25": round(over25 / jogos_validos, 2),
        "btts": round(btts / jogos_validos, 2),
    }

def extrair_stats_h2h(fixtures):
    jogos_validos = 0
    soma_gols = 0
    over15 = over25 = btts = 0

    for f in fixtures:
        goals = f.get("goals", {})
        hg = goals.get("home")
        ag = goals.get("away")
        if hg is None or ag is None:
            continue

        jogos_validos += 1
        soma_gols += (hg + ag)

        if hg + ag >= 2:
            over15 += 1
        if hg + ag >= 3:
            over25 += 1
        if hg > 0 and ag > 0:
            btts += 1

    if jogos_validos == 0:
        jogos_validos = 1

    return {
        "jogos": jogos_validos,
        "media_gols": round(soma_gols / jogos_validos, 2),
        "over15": round(over15 / jogos_validos, 2),
        "over25": round(over25 / jogos_validos, 2),
        "btts": round(btts / jogos_validos, 2),
    }

def posicoes_liga(standings_data, home_id, away_id):
    home_pos = away_pos = None
    try:
        tabela = standings_data[0]["league"]["standings"][0]
        for row in tabela:
            team_id = (row.get("team") or {}).get("id")
            rank = row.get("rank")
            if team_id == home_id:
                home_pos = rank
            if team_id == away_id:
                away_pos = rank
    except Exception:
        pass
    return home_pos, away_pos

# =====================================
# ESTATÍSTICAS DO JOGO AVULSO
# =====================================
def parse_stat_value(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("%", "")
    try:
        return float(s)
    except Exception:
        return None

def resumir_stats_fixture(stats_response, home_name, away_name):
    resultado = {
        "home": {},
        "away": {}
    }

    if not stats_response or len(stats_response) < 2:
        return resultado

    for item in stats_response:
        team = item.get("team", {})
        team_name = team.get("name", "")
        bucket = None

        if team_name == home_name:
            bucket = resultado["home"]
        elif team_name == away_name:
            bucket = resultado["away"]
        else:
            continue

        for stat in item.get("statistics", []):
            tipo = stat.get("type", "")
            valor = parse_stat_value(stat.get("value"))
            if valor is None:
                continue
            bucket[tipo] = valor

    return resultado

# =====================================
# MODELO TOP10 - GOLS E ESCANTEIOS
# =====================================
def calcular_modelo_top10(jogo):
    home_last = ultimos_jogos_time(jogo["home_id"], 10)
    away_last = ultimos_jogos_time(jogo["away_id"], 10)
    h2h_last = confrontos_diretos(jogo["home_id"], jogo["away_id"], 10)
    pred = predictions(jogo["id"])
    table = standings(jogo["league_id"], jogo["season"])

    hs = extrair_stats_time(home_last, jogo["home_id"])
    aws = extrair_stats_time(away_last, jogo["away_id"])
    h2h = extrair_stats_h2h(h2h_last)
    home_pos, away_pos = posicoes_liga(table, jogo["home_id"], jogo["away_id"])

    pred_percent = pred.get("percent", {}) if pred else {}

    def parse_percent(x):
        try:
            return float(str(x).replace("%", "").strip()) / 100.0
        except Exception:
            return None

    p_home_api = parse_percent(pred_percent.get("home"))
    p_draw_api = parse_percent(pred_percent.get("draw"))
    p_away_api = parse_percent(pred_percent.get("away"))

    media_total = (
        hs["gols_pro"] + hs["gols_contra"] +
        aws["gols_pro"] + aws["gols_contra"]
    ) / 2

    # Total de Gols
    p_over15 = clamp(
        (hs["over15"] * 0.30) +
        (aws["over15"] * 0.30) +
        (h2h["over15"] * 0.20) +
        (0.20 if media_total >= 2.0 else 0.08 if media_total >= 1.6 else 0.0),
        0.25, 0.92
    )

    p_over25 = clamp(
        (hs["over25"] * 0.32) +
        (aws["over25"] * 0.32) +
        (h2h["over25"] * 0.18) +
        (0.14 if media_total >= 2.6 else 0.05 if media_total >= 2.2 else 0.0),
        0.15, 0.82
    )

    p_under35 = clamp(
        0.88 - p_over25 * 0.45,
        0.35, 0.90
    )

    # Escanteios - modelo leve por proxy ofensiva
    base_corners = (
        hs["gols_pro"] * 1.2 +
        aws["gols_pro"] * 1.1 +
        hs["over15"] * 2.0 +
        aws["over15"] * 2.0
    )

    p_corner_over75 = clamp(0.42 + base_corners * 0.045, 0.35, 0.88)
    p_corner_over85 = clamp(0.32 + base_corners * 0.040, 0.22, 0.82)
    p_corner_over95 = clamp(0.22 + base_corners * 0.036, 0.15, 0.74)

    # pequeno ajuste por prediction/tabela
    bonus = 0.0
    if p_home_api is not None and p_away_api is not None:
        diff = abs(p_home_api - p_away_api)
        if diff < 0.18:
            bonus += 0.02  # jogo mais equilibrado tende a gerar mais pressão dos dois lados
    if home_pos and away_pos and abs(home_pos - away_pos) <= 4:
        bonus += 0.01

    p_corner_over75 = clamp(p_corner_over75 + bonus, 0.35, 0.90)
    p_corner_over85 = clamp(p_corner_over85 + bonus, 0.22, 0.84)
    p_corner_over95 = clamp(p_corner_over95 + bonus, 0.15, 0.76)

    mercados = [
        ("Total de Gols: Mais de 1.5", p_over15),
        ("Total de Gols: Mais de 2.5", p_over25),
        ("Total de Gols: Menos de 3.5", p_under35),
        ("Total de Escanteios: Mais de 7.5", p_corner_over75),
        ("Total de Escanteios: Mais de 8.5", p_corner_over85),
        ("Total de Escanteios: Mais de 9.5", p_corner_over95),
    ]

    return {
        "jogo": jogo,
        "home_stats": hs,
        "away_stats": aws,
        "h2h_stats": h2h,
        "mercados": mercados
    }

def classificar_sinais_top10(modelo):
    hs = modelo["home_stats"]
    aws = modelo["away_stats"]
    h2h = modelo["h2h_stats"]

    sinais = 0
    if hs["over15"] >= 0.70 or aws["over15"] >= 0.70:
        sinais += 1
    if h2h["over15"] >= 0.65:
        sinais += 1
    if hs["gols_pro"] >= 1.3 or aws["gols_pro"] >= 1.3:
        sinais += 1
    if h2h["media_gols"] >= 2.2:
        sinais += 1

    if sinais >= 3:
        return "🟩 Aposta Forte"
    if sinais == 2:
        return "🟨 Aposta Boa"
    return "⬜ Moderada"

def gerar_top10_apostas():
    jogos = jogos_hoje_formatados()

    apostas = []

    for jogo in jogos:
        try:
            modelo = calcular_modelo_top10(jogo)
            classificacao = classificar_sinais_top10(modelo)

            for nome, prob in modelo["mercados"]:
                if prob < 0.69:
                    continue

                apostas.append({
                    "jogo": f"{jogo['home']} x {jogo['away']}",
                    "liga": f"{jogo['country']} - {jogo['league']}",
                    "mercado": nome,
                    "prob": prob,
                    "classificacao": classificacao
                })
        except Exception:
            continue

    apostas.sort(key=lambda x: x["prob"], reverse=True)
    return apostas[:10]

def format_top10_apostas(apostas):
    if not apostas:
        return "Não encontrei oportunidades fortes hoje."

    linhas = ["🔥 TOP 10 DO DIA — GOLS E ESCANTEIOS\n"]

    for i, item in enumerate(apostas, start=1):
        linhas.append(f"{i}. {item['jogo']}")
        linhas.append(item["mercado"])
        linhas.append(f"Probabilidade: {int(item['prob'] * 100)}%")
        linhas.append(item["classificacao"])
        linhas.append("")

    return "\n".join(linhas)

# =====================================
# ANÁLISE DE JOGO AVULSO
# =====================================
def calcular_analise_avulsa(jogo):
    home_last = ultimos_jogos_time(jogo["home_id"], 10)
    away_last = ultimos_jogos_time(jogo["away_id"], 10)
    h2h_last = confrontos_diretos(jogo["home_id"], jogo["away_id"], 10)
    pred = predictions(jogo["id"])
    table = standings(jogo["league_id"], jogo["season"])
    stats_fixture = fixture_statistics(jogo["id"])

    hs = extrair_stats_time(home_last, jogo["home_id"])
    aws = extrair_stats_time(away_last, jogo["away_id"])
    h2h = extrair_stats_h2h(h2h_last)
    home_pos, away_pos = posicoes_liga(table, jogo["home_id"], jogo["away_id"])

    pred_percent = pred.get("percent", {}) if pred else {}

    def parse_percent(x):
        try:
            return float(str(x).replace("%", "").strip()) / 100.0
        except Exception:
            return None

    p_home_api = parse_percent(pred_percent.get("home"))
    p_draw_api = parse_percent(pred_percent.get("draw"))
    p_away_api = parse_percent(pred_percent.get("away"))

    # dupla chance
    if p_home_api is None or p_draw_api is None or p_away_api is None:
        p_home_api = 0.40
        p_draw_api = 0.28
        p_away_api = 0.32

    p_1x = clamp(p_home_api + p_draw_api, 0.35, 0.92)
    p_x2 = clamp(p_away_api + p_draw_api, 0.30, 0.90)

    # gols
    media_total = (
        hs["gols_pro"] + hs["gols_contra"] +
        aws["gols_pro"] + aws["gols_contra"]
    ) / 2

    p_over15 = clamp(
        (hs["over15"] * 0.30) +
        (aws["over15"] * 0.30) +
        (h2h["over15"] * 0.20) +
        (0.20 if media_total >= 2.0 else 0.08 if media_total >= 1.6 else 0.0),
        0.25, 0.92
    )

    p_over25 = clamp(
        (hs["over25"] * 0.32) +
        (aws["over25"] * 0.32) +
        (h2h["over25"] * 0.18) +
        (0.14 if media_total >= 2.6 else 0.05 if media_total >= 2.2 else 0.0),
        0.15, 0.82
    )

    p_under35 = clamp(0.88 - p_over25 * 0.45, 0.35, 0.90)

    # stats reais do fixture, se tiver
    resumo_fixture = resumir_stats_fixture(stats_fixture, jogo["home"], jogo["away"])
    home_stats_now = resumo_fixture["home"]
    away_stats_now = resumo_fixture["away"]

    home_shots = home_stats_now.get("Shots on Goal", 0) + home_stats_now.get("Total Shots", 0) * 0.45
    away_shots = away_stats_now.get("Shots on Goal", 0) + away_stats_now.get("Total Shots", 0) * 0.45
    total_shots_proxy = home_shots + away_shots

    home_fouls = home_stats_now.get("Fouls", 0)
    away_fouls = away_stats_now.get("Fouls", 0)
    total_fouls_proxy = home_fouls + away_fouls

    home_yellow = home_stats_now.get("Yellow Cards", 0)
    away_yellow = away_stats_now.get("Yellow Cards", 0)
    total_cards_proxy = home_yellow + away_yellow

    home_corners = home_stats_now.get("Corner Kicks", 0)
    away_corners = away_stats_now.get("Corner Kicks", 0)
    total_corners_proxy = home_corners + away_corners

    # se ainda não houver stats do fixture, usa modelo leve
    if total_corners_proxy <= 0:
        base_corners = (
            hs["gols_pro"] * 1.2 +
            aws["gols_pro"] * 1.1 +
            hs["over15"] * 2.0 +
            aws["over15"] * 2.0
        )
        p_corner_over75 = clamp(0.42 + base_corners * 0.045, 0.35, 0.88)
        p_corner_over85 = clamp(0.32 + base_corners * 0.040, 0.22, 0.82)
    else:
        p_corner_over75 = clamp(0.40 + total_corners_proxy * 0.035, 0.30, 0.90)
        p_corner_over85 = clamp(0.28 + total_corners_proxy * 0.032, 0.18, 0.84)

    if total_shots_proxy <= 0:
        total_shots_proxy = (
            hs["gols_pro"] * 4.2 +
            aws["gols_pro"] * 4.0 +
            hs["over15"] * 6.0 +
            aws["over15"] * 6.0
        )

    if total_fouls_proxy <= 0:
        total_fouls_proxy = 21 + (h2h["media_gols"] * 1.5)

    if total_cards_proxy <= 0:
        total_cards_proxy = 3.2 + (total_fouls_proxy / 18)

    mercados = [
        ("Total de Gols: Mais de 1.5", p_over15),
        ("Total de Gols: Mais de 2.5", p_over25),
        ("Total de Gols: Menos de 3.5", p_under35),
        ("Total de Escanteios: Mais de 7.5", p_corner_over75),
        ("Total de Escanteios: Mais de 8.5", p_corner_over85),
        ("Dupla Chance: Casa ou Empate", p_1x),
        ("Dupla Chance: Empate ou Fora", p_x2),
        ("Total de Finalizações: Mais de 19.5", clamp(0.35 + total_shots_proxy * 0.020, 0.25, 0.88)),
        ("Total de Finalizações: Mais de 23.5", clamp(0.22 + total_shots_proxy * 0.017, 0.15, 0.78)),
        ("Total de Cartões: Mais de 2.5", clamp(0.40 + total_cards_proxy * 0.09, 0.30, 0.92)),
        ("Total de Cartões: Mais de 3.5", clamp(0.26 + total_cards_proxy * 0.08, 0.18, 0.84)),
        ("Total de Faltas: Mais de 19.5", clamp(0.42 + total_fouls_proxy * 0.015, 0.30, 0.92)),
        ("Total de Faltas: Mais de 23.5", clamp(0.28 + total_fouls_proxy * 0.013, 0.18, 0.84)),
    ]

    # remove duplicidade de dupla chance: mantém só a melhor
    mercados.sort(key=lambda x: x[1], reverse=True)
    escolhidos = []
    grupo_usado = set()

    def grupo(nome):
        if nome.startswith("Dupla Chance"):
            return "dupla_chance"
        if nome.startswith("Total de Gols: Mais de 1.5"):
            return "gols15"
        if nome.startswith("Total de Gols: Mais de 2.5"):
            return "gols25"
        if nome.startswith("Total de Gols: Menos de 3.5"):
            return "golsu35"
        if nome.startswith("Total de Escanteios"):
            return nome
        if nome.startswith("Total de Finalizações"):
            return nome
        if nome.startswith("Total de Cartões"):
            return nome
        if nome.startswith("Total de Faltas"):
            return nome
        return nome

    for nome, prob in mercados:
        g = grupo(nome)
        if g in grupo_usado:
            continue
        grupo_usado.add(g)
        escolhidos.append((nome, prob))

    escolhidos.sort(key=lambda x: x[1], reverse=True)

    return escolhidos[:6]

def format_analise_avulsa(jogo, picks):
    linhas = [f"📊 {jogo['home']} x {jogo['away']}\n"]
    linhas.append(f"🏆 {jogo['country']} - {jogo['league']}\n")
    linhas.append("🟢 Melhores opções:\n")

    for i, (mercado, prob) in enumerate(picks, start=1):
        linhas.append(f"{i}. {mercado}")
        linhas.append(f"Probabilidade: {int(prob * 100)}%\n")

    return "\n".join(linhas)

# =====================================
# BUSCAR JOGO POR ID
# =====================================
def buscar_jogo_por_id(fixture_id):
    jogos = jogos_hoje_formatados()
    for j in jogos:
        if str(j["id"]) == str(fixture_id):
            return j

    try:
        data = af_get("/fixtures", {"id": fixture_id})
        resp = data.get("response", [])
        if not resp:
            return None

        item = resp[0]
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        league = item.get("league", {})

        jogo = {
            "id": fixture.get("id"),
            "home_id": (teams.get("home") or {}).get("id"),
            "away_id": (teams.get("away") or {}).get("id"),
            "home": (teams.get("home") or {}).get("name", "Casa"),
            "away": (teams.get("away") or {}).get("name", "Fora"),
            "league_id": league.get("id"),
            "league": league.get("name", ""),
            "country": league.get("country", ""),
            "season": league.get("season"),
            "timestamp": fixture.get("timestamp", 0),
        }
        return jogo
    except Exception:
        return None

# =====================================
# ROTAS
# =====================================
@app.route("/")
def home():
    return "ELITE 10.0 online"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id:
        return {"ok": True}

    if text in ("/start", "start"):
        send(
            chat_id,
            "🤖 ELITE 10.0 online ✅\n\n"
            "Comandos:\n"
            "/teste\n"
            "/jogoshoje\n"
            "/top10\n"
            "/analise ID_DO_JOGO"
        )

    elif text == "/teste":
        send(chat_id, "✅ ELITE 10.0 funcionando")

    elif text == "/jogoshoje":
        try:
            jogos = jogos_hoje_formatados()
            send(chat_id, format_jogos(jogos, limit=20))
        except Exception as e:
            send(chat_id, f"Erro ao buscar jogos: {type(e).__name__} - {e}")

    elif text == "/top10":
        try:
            apostas = gerar_top10_apostas()
            send(chat_id, format_top10_apostas(apostas))
        except Exception as e:
            send(chat_id, f"Erro no top10: {type(e).__name__} - {e}")

    elif text.startswith("/analise"):
        parts = text.split()
        if len(parts) < 2:
            send(chat_id, "Use: /analise ID_DO_JOGO")
        else:
            fixture_id = parts[1]
            try:
                jogo = buscar_jogo_por_id(fixture_id)
                if not jogo:
                    send(chat_id, "Jogo não encontrado.")
                else:
                    picks = calcular_analise_avulsa(jogo)
                    send(chat_id, format_analise_avulsa(jogo, picks))
            except Exception as e:
                send(chat_id, f"Erro na análise: {type(e).__name__} - {e}")

    else:
        send(
            chat_id,
            "Comandos:\n"
            "/teste\n"
            "/jogoshoje\n"
            "/top10\n"
            "/analise ID_DO_JOGO"
        )

    return {"ok": True}

try:
    set_webhook()
except Exception:
    pass
