import os
import datetime
import requests
from flask import Flask, request

app = Flask(__name__)

# ====== CONFIG TELEGRAM ======
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip()

if not TELEGRAM_TOKEN:
    raise RuntimeError("Faltou a variável TELEGRAM_TOKEN no ambiente (Render).")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ====== SOFASCORE / PROXY ======
PROXY_BASE = os.environ.get("SOFA_PROXY_BASE", "").strip()

class SofaProxyError(Exception):
    pass

def sc_get(path: str):
    if not PROXY_BASE:
        raise RuntimeError("Faltou SOFA_PROXY_BASE no Render.")

    url = f"{PROXY_BASE}/proxy"

    try:
        r = requests.get(url, params={"path": path}, timeout=25)
    except requests.RequestException as e:
        raise SofaProxyError(f"Falha de conexão com o proxy: {e}")

    if r.status_code == 403:
        raise SofaProxyError(
            "SofaScore bloqueou a requisição (403 Forbidden). "
            "O bot está online, mas a fonte de dados recusou o acesso."
        )

    try:
        r.raise_for_status()
    except requests.RequestException as e:
        raise SofaProxyError(f"Erro HTTP no proxy: {e}")

    try:
        return r.json()
    except Exception:
        raise SofaProxyError("O proxy respondeu, mas não retornou JSON válido.")

def jogos_hoje():
    hoje = datetime.date.today().isoformat()
    data = sc_get(f"/sport/football/scheduled-events/{hoje}")
    events = data.get("events", [])
    jogos = []

    for e in events:
        t = (e.get("tournament") or {})
        c = (t.get("category") or {})
        home = (e.get("homeTeam") or {}).get("name", "Casa")
        away = (e.get("awayTeam") or {}).get("name", "Fora")
        event_id = e.get("id")
        league = t.get("name", "")
        country = c.get("name", "")
        start_ts = e.get("startTimestamp") or 0
        jogos.append((event_id, home, away, country, league, start_ts))

    jogos.sort(key=lambda x: x[5])
    return jogos

def format_jogos(jogos, limit=15):
    if not jogos:
        return "⚽ Nenhum jogo encontrado para hoje."
    linhas = ["⚽ Jogos de hoje:"]
    for (eid, home, away, country, league, _ts) in jogos[:limit]:
        linhas.append(f"- {home} x {away} | {country} - {league} | id: {eid}")
    linhas.append("\nUse: /stats ID_DO_JOGO")
    return "\n".join(linhas)

def stats_evento(event_id: int):
    info = sc_get(f"/event/{event_id}")
    e = info.get("event", {})
    home = (e.get("homeTeam") or {})
    away = (e.get("awayTeam") or {})

    home_name = home.get("name", "Casa")
    away_name = away.get("name", "Fora")

    stats = None
    lineups = None

    try:
        stats = sc_get(f"/event/{event_id}/statistics")
    except Exception:
        pass

    try:
        lineups = sc_get(f"/event/{event_id}/lineups")
    except Exception:
        pass

    return {
        "match": f"{home_name} x {away_name}",
        "stats": stats,
        "lineups": lineups,
    }

def resumo_stats(stats_json):
    if not stats_json:
        return "Sem estatísticas disponíveis."

    out = []
    statistics = stats_json.get("statistics", [])
    groups = []

    if statistics and isinstance(statistics[0], dict) and "groups" in statistics[0]:
        groups = statistics[0].get("groups", [])
    elif statistics and isinstance(statistics[0], dict) and "statisticsItems" in statistics[0]:
        groups = [{"statisticsItems": statistics}]
    elif isinstance(statistics, list):
        groups = statistics

    wanted = {
        "Shots on target": "Chutes no gol",
        "Total shots": "Finalizações",
        "Corner kicks": "Escanteios",
        "Fouls": "Faltas",
        "Yellow cards": "Cartões amarelos",
        "Red cards": "Cartões vermelhos",
        "Offsides": "Impedimentos",
        "Throw-ins": "Laterais",
    }

    for g in groups:
        items = g.get("statisticsItems", []) or g.get("items", [])
        for it in items:
            name = it.get("name")
            if name in wanted:
                home = it.get("home")
                away = it.get("away")
                out.append(f"{wanted[name]}: {home} x {away}")

    if not out:
        return "Estatísticas vieram em formato diferente."
    return "\n".join(out)

def resumo_lineups(lineups_json):
    if not lineups_json:
        return "👥 Escalações: ainda não disponíveis."

    home = (lineups_json.get("home") or {})
    away = (lineups_json.get("away") or {})
    hp = home.get("players", [])
    ap = away.get("players", [])

    def top_names(players, n=11):
        names = []
        for p in players[:n]:
            player = p.get("player") or {}
            nm = player.get("name")
            if nm:
                names.append(nm)
        return ", ".join(names) if names else "(não veio lista)"

    return (
        "👥 Escalações:\n"
        f"Casa: {top_names(hp)}\n"
        f"Fora: {top_names(ap)}"
    )

# ====== TELEGRAM HELPERS ======
def send_message(chat_id: int, text: str):
    payload = {"chat_id": chat_id, "text": text}
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=25)
    r.raise_for_status()

def set_webhook():
    if not PUBLIC_URL:
        return
    webhook_url = f"{PUBLIC_URL}/webhook"
    r = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url}, timeout=25)
    r.raise_for_status()

# ====== ROUTES ======
@app.get("/")
def home():
    proxy_info = PROXY_BASE if PROXY_BASE else "NÃO CONFIGURADO"
    return f"Elite90 bot online ✅ | Proxy: {proxy_info}", 200

@app.post("/webhook")
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}, 200

    if text in ("/start", "start"):
        send_message(
            chat_id,
            "🤖 Elite90 BetBot online ✅\n\nComandos:\n/teste\n/jogoshoje\n/stats ID_DO_JOGO\n/status"
        )

    elif text.startswith("/teste"):
        send_message(chat_id, "✅ Teste OK! Bot online e recebendo mensagens.")

    elif text.startswith("/status"):
        send_message(
            chat_id,
            f"✅ Bot online\nProxy configurado: {'SIM' if PROXY_BASE else 'NÃO'}\nBase: {PROXY_BASE or 'vazia'}"
        )

    elif text.startswith("/jogoshoje"):
        try:
            jogos = jogos_hoje()
            send_message(chat_id, format_jogos(jogos, limit=15))
        except Exception as e:
            send_message(chat_id, f"⚠️ Fonte de dados indisponível no momento.\nDetalhe: {e}")

    elif text.startswith("/stats"):
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_message(chat_id, "Use assim: /stats 123456")
        else:
            eid = int(parts[1])
            try:
                data = stats_evento(eid)
                msg = (
                    f"📌 {data['match']}\n\n"
                    f"📊 Estatísticas:\n{resumo_stats(data['stats'])}\n\n"
                    f"{resumo_lineups(data['lineups'])}"
                )
                send_message(chat_id, msg)
            except Exception as e:
                send_message(chat_id, f"⚠️ Não consegui buscar as stats.\nDetalhe: {e}")

    else:
        send_message(chat_id, "Comandos:\n/teste\n/jogoshoje\n/stats ID_DO_JOGO\n/status")

    return {"ok": True}, 200

try:
    set_webhook()
except Exception:
    pass
