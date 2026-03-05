import os
from flask import Flask, request

import requests

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip()  # ex: https://seu-servico.onrender.com

if not TELEGRAM_TOKEN:
    raise RuntimeError("Faltou a variável TELEGRAM_TOKEN no ambiente (Render).")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def send_message(chat_id: int, text: str):
    payload = {"chat_id": chat_id, "text": text}
    r = requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=20)
    r.raise_for_status()

def set_webhook():
    if not PUBLIC_URL:
        # Sem PUBLIC_URL, não dá para setar webhook automaticamente.
        # Você vai setar depois pelo painel do Telegram (ou colocar a env e redeploy).
        return
    webhook_url = f"{PUBLIC_URL}/webhook"
    r = requests.post(f"{TELEGRAM_API}/setWebhook", json={"url": webhook_url}, timeout=20)
    r.raise_for_status()

@app.get("/")
def home():
    return "Elite90 bot online ✅", 200

@app.post("/webhook")
def webhook():
    update = request.get_json(silent=True) or {}

    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}, 200

    # Comandos básicos
    if text in ("/start", "start"):
        send_message(chat_id, "🤖 Elite90 BetBot online ✅\nUse /teste para checar.")
    elif text.startswith("/teste"):
        send_message(chat_id, "✅ Teste OK! Bot está funcionando e recebendo mensagens.")
    elif text.startswith("/jogoshoje"):
        try:
            jogos = jogos_hoje()
            send_message(chat_id, format_jogos(jogos, limit=15))
        except Exception:
            send_message(chat_id, "Erro ao buscar jogos de hoje no Sofascore. Tenta de novo daqui a pouco.")

    elif text.startswith("/stats"):
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_message(chat_id, "Use assim: /stats 123456 (id do jogo)")
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
            except Exception:
                send_message(chat_id, "Não consegui puxar stats desse jogo. Confere se o ID está certo ou se o jogo já apareceu no Sofascore.")
    else:
        send_message(
            chat_id,
            "Recebi sua mensagem ✅\nPor enquanto tenho /teste.\nEm breve: /jogoshoje /top10 /betbuilder"
        )

    return {"ok": True}, 200

# Quando o Render iniciar, tenta setar o webhook (se PUBLIC_URL estiver definida)
try:
    set_webhook()
except Exception:
    # Se falhar, não derruba o app; depois setamos manualmente.
    pass

