import os  # v3
import requests
from flask import Flask, request, jsonify

TOKEN_BOT = "7864266536:AAHW3BMrhRqDzeUsaydQQ6Pum5KbCpG8GEM"
API_KEY_TIENDA = "2fc6bc5920314acce1467adb2e95dbd369e7312f31a7c465f6aef0fb86d7537d"
URL_TELEGRAM = f"https://api.telegram.org/bot{TOKEN_BOT}"
URL_TIENDA = "https://tiendagiftven.tech/api/v1"

app = Flask(__name__)
sesiones = {}

PRODUCTOS = [
    {"id": 1,   "nombre": "100+10 💎",       "precio": 1},
    {"id": 127, "nombre": "200+20 💎",       "precio": 2},
    {"id": 2,   "nombre": "310+31 💎",       "precio": 3},
    {"id": 3,   "nombre": "520+52 💎",       "precio": 5},
    {"id": 4,   "nombre": "1060+106 💎",     "precio": 10},
    {"id": 5,   "nombre": "2180+218 💎",     "precio": 20},
    {"id": 6,   "nombre": "5600+560 💎",     "precio": 50},
    {"id": 155, "nombre": "Tarjeta Básica",  "precio": 1},
    {"id": 156, "nombre": "Tarjeta Semanal", "precio": 3},
    {"id": 157, "nombre": "Tarjeta Mensual", "precio": 11},
    {"id": 158, "nombre": "Pase Booyah",     "precio": 4},
]

def enviar(chat_id, texto, teclado=None):
    datos = {"chat_id": chat_id, "text": texto}
    if teclado:
        datos["reply_markup"] = teclado
    requests.post(f"{URL_TELEGRAM}/sendMessage", json=datos)

def botones(opciones):
    filas = []
    fila = []
    for i, op in enumerate(opciones):
        fila.append({"text": op})
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    return {"keyboard": filas, "resize_keyboard": True, "one_time_keyboard": True}

def pedir_usuario(chat_id):
    sesiones[chat_id] = {"paso": "login"}
    enviar(chat_id, "👤 ¿Quién eres?", botones(["MD", "Albo", "Ocho"]))

def menu_principal(chat_id, usuario):
    enviar(chat_id, f"✅ Bienvenido {usuario}!\n\n/recargar - Nueva recarga\n/saldo - Ver saldo\n/reporte - Recargas de hoy")

@app.route("/webhook", methods=["POST"])
def webhook():
    datos = request.json
    if not datos or "message" not in datos:
        return {"status": "ok"}

    chat_id = datos["message"]["chat"]["id"]
    texto = datos["message"].get("text", "").strip()
    sesion = sesiones.get(chat_id, {})

    # SIEMPRE reinicia con /start
    if texto == "/start":
        pedir_usuario(chat_id)
        return {"status": "ok"}

    # Sin sesión activa
    if not sesion:
        pedir_usuario(chat_id)
        return {"status": "ok"}

    paso = sesion.get("paso", "")
    usuario = sesion.get("usuario", "")

    # PASO: login
    if paso == "login":
        if texto in ["MD", "Albo", "Ocho"]:
            sesiones[chat_id]["usuario"] = texto
            sesiones[chat_id]["paso"] = "menu"
            menu_principal(chat_id, texto)
        else:
            enviar(chat_id, "❌ Elige una opción válida.", botones(["MD", "Albo", "Ocho"]))
        return {"status": "ok"}

    # COMANDOS CON SESIÓN ACTIVA
    if texto == "/saldo":
        resp = requests.get(f"{URL_TIENDA}/saldo", headers={"X-API-Key": API_KEY_TIENDA}).json()
        enviar(chat_id, f"💰 Saldo: ${resp.get('saldo', 'error')}")
        return {"status": "ok"}

    if texto == "/reporte":
        resp = requests.get(f"{URL_TIENDA}/pedidos", headers={"X-API-Key": API_KEY_TIENDA}).json()
        from datetime import datetime
        hoy = datetime.now().strftime("%Y-%m-%d")
        conteo = {}
        for p in resp.get("pedidos", []):
            if hoy in p.get("fecha_pedido", "") and p.get("estado") == "completado":
                op = p.get("producto", "?")
                conteo[op] = conteo.get(op, 0) + 1
        if conteo:
            msg = "📊 Recargas de hoy:\n" + "\n".join(f"• {k}: {v}" for k, v in conteo.items())
        else:
            msg = "📊 No hay recargas completadas hoy."
        enviar(chat_id, msg)
        return {"status": "ok"}

    if texto == "/recargar":
        sesiones[chat_id]["paso"] = "elegir_producto"
        ops = [f"{p['nombre']} ${p['precio']}" for p in PRODUCTOS]
        enviar(chat_id, "💎 Elige el monto:", botones(ops))
        return {"status": "ok"}

    # PASO: elegir producto
    if paso == "elegir_producto":
        producto = next((p for p in PRODUCTOS if f"{p['nombre']} ${p['precio']}" == texto), None)
        if not producto:
            ops = [f"{p['nombre']} ${p['precio']}" for p in PRODUCTOS]
            enviar(chat_id, "❌ Elige una opción válida.", botones(ops))
            return {"status": "ok"}
        sesiones[chat_id]["producto"] = producto
        sesiones[chat_id]["paso"] = "pedir_id"
        enviar(chat_id, f"✅ {producto['nombre']} ${producto['precio']}\n\n🔢 Escribe el ID del jugador en Free Fire:")
        return {"status": "ok"}

    # PASO: pedir ID
    if paso == "pedir_id":
        sesiones[chat_id]["id_jugador"] = texto
        sesiones[chat_id]["paso"] = "confirmar"
        p = sesion["producto"]
        enviar(chat_id,
            f"⚠️ Confirma la recarga:\n\n"
            f"👤 ID: {texto}\n"
            f"💎 {p['nombre']}\n"
            f"💵 ${p['precio']}\n\n"
            f"¿Confirmas?",
            botones(["✅ Confirmar", "❌ Cancelar"])
        )
        return {"status": "ok"}

    # PASO: confirmar
    if paso == "confirmar":
        if texto == "✅ Confirmar":
            p = sesion["producto"]
            id_jugador = sesion["id_jugador"]
            enviar(chat_id, "⏳ Procesando recarga...")
            resp = requests.post(f"{URL_TIENDA}/comprar",
                headers={"X-API-Key": API_KEY_TIENDA},
                json={"producto_id": p["id"], "id_juego": id_jugador}
            ).json()
            if resp.get("ok"):
                enviar(chat_id,
                    f"✅ ¡Recarga exitosa!\n\n"
                    f"👤 {resp.get('nombre_jugador', id_jugador)}\n"
                    f"💎 {p['nombre']}\n"
                    f"🧾 Pedido #: {resp.get('pedido_id')}\n"
                    f"💰 Saldo restante: ${resp.get('saldo_restante')}\n"
                    f"👨‍💼 Operador: {usuario}"
                )
            else:
                enviar(chat_id, f"❌ Error: {resp.get('error')}")
        else:
            enviar(chat_id, "❌ Recarga cancelada.")
        sesiones[chat_id]["paso"] = "menu"
        return {"status": "ok"}

    enviar(chat_id, "Usa /recargar, /saldo o /reporte")
    return {"status": "ok"}

@app.route("/")
def index():
    return "Bot activo v3", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
