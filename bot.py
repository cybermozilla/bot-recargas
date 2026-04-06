import os
import requests
from flask import Flask, request, jsonify

TOKEN_BOT = os.environ.get("7864266536:AAHW3BMrhRqDzeUsaydQQ6Pum5KbCpG8GEM")
API_KEY_TIENDA = os.environ.get("2fc6bc5920314acce1467adb2e95dbd369e7312f31a7c465f6aef0fb86d7537d")
URL_TELEGRAM = f"https://api.telegram.org/bot{TOKEN_BOT}"
URL_TIENDA = "https://tiendagiftven.tech/api/v1"

app = Flask(__name__)

def enviar_mensaje(chat_id, texto):
    resp = requests.post(f"{URL_TELEGRAM}/sendMessage", json={
        "chat_id": chat_id,
        "text": texto
    })
    print(f"Telegram response: {resp.status_code} {resp.text}")

def consultar_saldo(chat_id):
    resp = requests.get(f"{URL_TIENDA}/saldo", headers={"X-API-Key": API_KEY_TIENDA})
    datos = resp.json()
    if datos.get("ok"):
        enviar_mensaje(chat_id, f"💰 Saldo disponible: ${datos['saldo']}")
    else:
        enviar_mensaje(chat_id, f"❌ Error: {datos.get('error')}")

@app.route("/webhook", methods=["POST"])
def webhook():
    datos = request.json
    if not datos or "message" not in datos:
        return jsonify({"status": "ok"})

    chat_id = datos["message"]["chat"]["id"]
    texto = datos["message"].get("text", "")

    if texto == "/start":
        enviar_mensaje(chat_id, "✅ Sistema Conectado.\nComandos:\n/saldo - Ver saldo")
    elif texto == "/saldo":
        consultar_saldo(chat_id)
    else:
        enviar_mensaje(chat_id, "Comandos disponibles:\n/saldo - Ver saldo")

    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return "Bot activo", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
