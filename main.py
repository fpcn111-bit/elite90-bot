import os
import math
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
# HELPERS API
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
# FIXTURES
# =========================
def jogos_hoje_raw():
    hoje = datetime.date.today().isoformat()
    data = af_get("/fixtures", {"date": hoje})
    return data.get("response", [])

def jogos_hoje_formatados(limit=30):
    jogos = []
    for item in jogos_hoje_raw():
        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        league = item.get("league", {})

        status = ((fixture.get("status") or {}).get("short") or "").upper()
        if status in ("FT", "AET", "PEN", "CANC", "PST", "ABD", "AWD", "WO"):
            continue

        jogos.append({
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
            "status": status
        })

    jogos.sort(key=lambda x: x["timestamp"])
    return jogos[:limit]

# =========================
# HISTÓRICO / H2H / TABELA
# =========================
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

def odds_for_fixture(fixture_id):
    try:
        data = af_get("/odds", {"fixture": fixture_id})
        return data.get("response", [])
    except Exception:
        return []

# =========================
# ESTATÍSTICAS RESUMIDAS
# =========================
def extrair_stats_time(fixtures, team_id):
    total = len(fixtures)
    if total == 0:
        return {
            "jogos": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "gols_pro": 0.0,
            "gols_contra": 0.0,
            "over15": 0.0,
            "over25": 0.0,
            "btts": 0.0,
        }

    wins = draws = losses = 0
    gols_pro = gols_contra = 0
    over15 = over25 = btts = 0

    for f in fixtures:
        teams = f.get("teams", {})
        goals = f.get("goals", {})

        home_id = (teams.get("home") or {}).get("id")
        away_id = (teams.get("away") or {}).get("id")
        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        if team_id == home_id:
            pro = home_goals
            contra = away_goals
        else:
            pro = away_goals
            contra = home_goals

        gols_pro += pro
        gols_contra += contra

        if pro > contra:
            wins += 1
        elif pro == contra:
            draws += 1
        else:
            losses += 1

        total_goals = pro + contra
        if total_goals >= 2:
            over15 += 1
        if total_goals >= 3:
            over25 += 1
        if pro > 0 and contra > 0:
            btts += 1

    return {
        "jogos": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "gols_pro": round(gols_pro / total, 2),
        "gols_contra": round(gols_contra / total, 2),
        "over15": round(over15 / total, 2),
        "over25": round(over25 / total, 2),
        "btts": round(btts / total, 2),
    }

def extrair_stats_h2h(fixtures, home_id, away_id):
    total = len(fixtures)
    if total == 0:
        return {
            "jogos": 0,
            "media_gols": 0.0,
            "btts": 0.0,
            "over15": 0.0,
            "over25": 0.0,
        }

    soma_gols = 0
    btts = 0
    over15 = 0
    over25 = 0

    for f in fixtures:
        goals = f.get("goals", {})
        hg = goals.get("home")
        ag = goals.get("away")
        if hg is None or ag is None:
            continue

        soma_gols += (hg + ag)
        if hg > 0 and ag > 0:
            btts += 1
        if hg + ag >= 2:
            over15 += 1
        if hg + ag >= 3:
            over25 += 1

    return {
        "jogos": total,
        "media_gols": round(soma_gols / total, 2),
        "btts": round(btts / total, 2),
        "over15": round(over15 / total, 2),
        "over25": round(over25 / total, 2),
    }

def posicoes_liga(standings_data, home_id, away_id):
    home_pos = away_pos = None
    try:
        league_block = standings_data[0]["league"]["standings"][0]
        for row in league_block:
            team_id = (row.get("team") or {}).get("id")
            rank = row.get("rank")
            if team_id == home_id:
                home_pos = rank
            elif team_id == away_id:
                away_pos = rank
    except Exception:
        pass
    return home_pos, away_pos

# =========================
# MODELO ELITE 10.0
# =========================
def calc_probabilidades(jogo):
    home_id = jogo["home_id"]
    away_id = jogo["away_id"]
    league_id = jogo["league_id"]
    season = jogo["season"]
    fixture_id = jogo["id"]

    home_last = ultimos_jogos_time(home_id, 10)
    away_last = ultimos_jogos_time(away_id, 10)
    h2h_last = confrontos_diretos(home_id, away_id, 10)
    table = standings(league_id, season)
    pred = predictions(fixture_id)

    hs = extrair_stats_time(home_last, home_id)
    aws = extrair_stats_time(away_last, away_id)
    h2h = extrair_stats_h2h(h2h_last, home_id, away_id)
    home_pos, away_pos = posicoes_liga(table, home_id, away_id)

    # Força simples
    home_strength = (
        hs["gols_pro"] * 1.3
        - hs["gols_contra"] * 0.8
        + hs["wins"] * 0.15
    )

    away_strength = (
        aws["gols_pro"] * 1.15
        - aws["gols_contra"] * 0.9
        + aws["wins"] * 0.12
    )

    # Ajuste por tabela
    pos_factor = 0
    if home_pos and away_pos:
        diff = away_pos - home_pos
        pos_factor = clamp(diff * 0.015, -0.18, 0.18)

    # Predictions da API
    pred_percent = pred.get("percent", {}) if pred else {}
    p_home_api = pred_percent.get("home")
    p_draw_api = pred_percent.get("draw")
    p_away_api = pred_percent.get("away")

    def parse_percent(x):
        try:
            return float(str(x).replace("%", "").strip()) / 100.0
        except Exception:
            return None

    p_home_api = parse_percent(p_home_api)
    p_draw_api = parse_percent(p_draw_api)
    p_away_api = parse_percent(p_away_api)

    # Probabilidades próprias
    base_home = 0.40 + (home_strength - away_strength) * 0.07 + pos_factor
    base_away = 0.28 + (away_strength - home_strength) * 0.05 - pos_factor / 2
    base_draw = 1 - base_home - base_away

    base_home = clamp(base_home, 0.15, 0.75)
    base_away = clamp(base_away, 0.10, 0.55)
    base_draw = clamp(base_draw, 0.12, 0.35)

    total = base_home + base_draw + base_away
    base_home /= total
    base_draw /= total
    base_away /= total

    # Mistura com prediction da API, se existir
    if p_home_api is not None and p_draw_api is not None and p_away_api is not None:
        p_home = 0.55 * base_home + 0.45 * p_home_api
        p_draw = 0.55 * base_draw + 0.45 * p_draw_api
        p_away = 0.55 * base_away + 0.45 * p_away_api
        total = p_home + p_draw + p_away
        p_home /= total
        p_draw /= total
        p_away /= total
    else:
        p_home, p_draw, p_away = base_home, base_draw, base_away

    # Mercados
    p_dupla_1x = p_home + p_draw
    p_dupla_x2 = p_away + p_draw

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

    p_under35 = clamp(
        0.88 - p_over25 * 0.45,
        0.35, 0.90
    )

    p_btts = clamp(
        (hs["btts"] * 0.4) + (aws["btts"] * 0.4) + (h2h["btts"] * 0.2),
        0.15, 0.85
    )

    p_home_goal = clamp(
        0.48 + hs["gols_pro"] * 0.18 - aws["gols_contra"] * 0.02,
        0.40, 0.94
    )

    p_away_goal = clamp(
        0.40 + aws["gols_pro"] * 0.16 - hs["gols_contra"] * 0.01,
        0.25, 0.88
    )

    analise = {
        "fixture_id": fixture_id,
        "home": jogo["home"],
        "away": jogo["away"],
        "league": jogo["league"],
        "country": jogo["country"],
        "home_pos": home_pos,
        "away_pos": away_pos,
        "home_stats": hs,
        "away_stats": aws,
        "h2h_stats": h2h,
        "mercados": {
            "Resultado Final: Casa": round(p_home, 3),
            "Resultado Final: Empate": round(p_draw, 3),
            "Resultado Final: Fora": round(p_away, 3),
            "Dupla Chance: Casa ou Empate": round(p_dupla_1x, 3),
            "Dupla Chance: Empate ou Fora": round(p_dupla_x2, 3),
            "Total de Gols: Mais de 1.5": round(p_over15, 3),
            "Total de Gols: Mais de 2.5": round(p_over25, 3),
            "Total de Gols: Menos de 3.5": round(p_under35, 3),
            "Ambas as Equipes Marcam: Sim": round(p_btts, 3),
            f"Total de Gols da Equipe: {jogo['home']} Mais de 0.5": round(p_home_goal, 3),
            f"Total de Gols da Equipe: {jogo['away']} Mais de 0.5": round(p_away_goal, 3),
        }
    }

    return analise

def classificar_sinais(analise):
    sinais = 0
    hs = analise["home_stats"]
    aws = analise["away_stats"]
    h2h = analise["h2h_stats"]
    home_pos = analise["home_pos"]
    away_pos = analise["away_pos"]

    if hs["wins"] >= 5 or aws["wins"] >= 5:
        sinais += 1
    if h2h["jogos"] >= 3 and (h2h["over15"] >= 0.70 or h2h["btts"] >= 0.65):
        sinais += 1
    if hs["gols_pro"] >= 1.4 or aws["gols_pro"] >= 1.4:
        sinais += 1
    if hs["over15"] >= 0.70 or aws["over15"] >= 0.70:
        sinais += 1
    if home_pos and away_pos and abs(home_pos - away_pos) >= 5:
        sinais += 1

    if sinais >= 3:
        return sinais, "🟩 Aposta Forte"
    elif sinais == 2:
        return sinais, "🟨 Aposta Boa"
    return sinais, "⬜ Evitar"

def top_mercados(analise, n=5):
    mercados = analise["mercados"]
    ordenados = sorted(mercados.items(), key=lambda x: x[1], reverse=True)
    return ordenados[:n]

def melhor_mercado(analise):
    return top_mercados(analise, 1)[0]

# =========================
# FORMATADORES
# =========================
def format_jogos(jogos, limit=20):
    linhas = ["⚽️ Jogos de hoje:\n"]
    for j in jogos[:limit]:
        linhas.append(f"{j['home']} x {j['away']}")
        linhas.append(f"{j['country']} - {j['league']}")
        linhas.append(f"id: {j['id']}\n")
    linhas.append("Use: /analise ID_DO_JOGO")
    return "\n".join(linhas)

def format_analise(analise):
    sinais, classificacao = classificar_sinais(analise)
    tops = top_mercados(analise, 5)

    hs = analise["home_stats"]
    aws = analise["away_stats"]
    h2h = analise["h2h_stats"]

    linhas = []
    linhas.append(f"📊 ELITE 10.0 — {analise['home']} x {analise['away']}\n")
    linhas.append(f"🏆 {analise['country']} - {analise['league']}")
    linhas.append(f"📍 Posição: {analise['home']} #{analise['home_pos'] or '-'} | {analise['away']} #{analise['away_pos'] or '-'}\n")

    linhas.append("📌 Resumo estatístico:")
    linhas.append(f"- Últimos 10 {analise['home']}: {hs['wins']}V {hs['draws']}E {hs['losses']}D | gols pró {hs['gols_pro']} | gols contra {hs['gols_contra']}")
    linhas.append(f"- Últimos 10 {analise['away']}: {aws['wins']}V {aws['draws']}E {aws['losses']}D | gols pró {aws['gols_pro']} | gols contra {aws['gols_contra']}")
    linhas.append(f"- H2H últimos {h2h['jogos']}: média gols {h2h['media_gols']} | over 1.5 {int(h2h['over15']*100)}% | BTTS {int(h2h['btts']*100)}%\n")

    linhas.append("🟢 Top 5 opções:")
    for i, (mercado, prob) in enumerate(tops, start=1):
        linhas.append(f"{i}. {mercado} — {int(prob*100)}%")

    linhas.append(f"\n🔥 Sinais fortes: {sinais}")
    linhas.append(f"{classificacao}")

    return "\n".join(linhas)

def format_top10(resultados):
    linhas = ["🔥 TOP 10 DO DIA — ELITE 10.0\n"]
    for i, item in enumerate(resultados[:10], start=1):
        analise = item["analise"]
        mercado, prob = item["melhor"]
        _, classificacao = classificar_sinais(analise)

        linhas.append(f"{i}) {analise['home']} x {analise['away']}")
        linhas.append(f"- {mercado}")
        linhas.append(f"- Probabilidade: {int(prob*100)}%")
        linhas.append(f"- {classificacao}\n")
    return "\n".join(linhas)

# =========================
# REGRAS DE FILTRO
# =========================
def jogo_eh_analisavel(jogo):
    texto = f"{jogo['country']} {jogo['league']} {jogo['home']} {jogo['away']}".lower()

    bloqueados = [
        "u17", "u18", "u19", "u20", "u21", "u23",
        "reserves", "reserve", "women friendlies"
    ]

    for b in bloqueados:
        if b in texto:
            return False

    return True

# =========================
# COMANDOS
# =========================
def buscar_jogo_por_id(fixture_id):
    jogos = jogos_hoje_formatados(limit=100)
    for j in jogos:
        if str(j["id"]) == str(fixture_id):
            return j

    # fallback: tenta puxar direto
    data = af_get("/fixtures", {"id": fixture_id})
    resp = data.get("response", [])
    if not resp:
        return None

    item = resp[0]
    fixture = item.get("fixture", {})
    teams = item.get("teams", {})
    league = item.get("league", {})

    return {
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
        "status": ((fixture.get("status") or {}).get("short") or "").upper()
    }

def gerar_top10():
    jogos = jogos_hoje_formatados(limit=80)
    jogos = [j for j in jogos if jogo_eh_analisavel(j)]

    resultados = []
    for j in jogos:
        try:
            analise = calc_probabilidades(j)
            melhor = melhor_mercado(analise)
            resultados.append({
                "jogo": j,
                "analise": analise,
                "melhor": melhor
            })
        except Exception:
            continue

    resultados.sort(key=lambda x: x["melhor"][1], reverse=True)
    return resultados

# =========================
# FLASK
# =========================
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
            "🤖 ELITE 10.0 online ✅\n\nComandos:\n"
            "/teste\n"
            "/jogoshoje\n"
            "/analise ID_DO_JOGO\n"
            "/top10"
        )

    elif text == "/teste":
        send(chat_id, "✅ ELITE 10.0 funcionando com API-Football")

    elif text == "/jogoshoje":
        try:
            jogos = jogos_hoje_formatados(limit=20)
            send(chat_id, format_jogos(jogos, limit=20))
        except Exception as e:
            send(chat_id, f"Erro ao buscar jogos: {type(e).__name__} - {e}")

    elif text.startswith("/analise"):
        parts = text.split()
        if len(parts) < 2:
            send(chat_id, "Use assim: /analise 123456")
        else:
            fixture_id = parts[1]
            try:
                jogo = buscar_jogo_por_id(fixture_id)
                if not jogo:
                    send(chat_id, "Não encontrei esse jogo.")
                else:
                    analise = calc_probabilidades(jogo)
                    send(chat_id, format_analise(analise))
            except Exception as e:
                send(chat_id, f"Erro na análise: {type(e).__name__} - {e}")

    elif text == "/top10":
        try:
            ranking = gerar_top10()
            if not ranking:
                send(chat_id, "Não encontrei jogos analisáveis para hoje.")
            else:
                send(chat_id, format_top10(ranking))
        except Exception as e:
            send(chat_id, f"Erro no top10: {type(e).__name__} - {e}")

    else:
        send(
            chat_id,
            "Comandos:\n"
            "/teste\n"
            "/jogoshoje\n"
            "/analise ID_DO_JOGO\n"
            "/top10"
        )

    return {"ok": True}

try:
    set_webhook()
except Exception:
    pass
