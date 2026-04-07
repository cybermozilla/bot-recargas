import os  # v2


import requests
from flask import Flask, request, jsonify


TOKEN_BOT = "7864266536:AAHW3BMrhRqDzeUsaydQQ6Pum5KbCpG8GEM"
API_KEY_TIENDA = "2fc6bc5920314acce1467adb2e95dbd369e7312f31a7c465f6aef0fb86d7537d"
URL_TELEGRAM = f"https://api.telegram.org/bot{TOKEN_BOT}"
URL_TIENDA = "https://tiendagiftven.tech/api/v1"

app = Flask(__name__)

# Usuarios autorizados: nombre -> chat_id de Telegram
USUARIOS = {
    "MD": None,
    "Albo": None,
    "Ocho": None
}

# Sesiones activas
sesiones = {}

# Productos Free Fire
PRODUCTOS = [
    {"id": 1,   "nombre": "100+10 💎",    "precio": 1},
    {"id": 127, "nombre": "200+20 💎",    "precio": 2},
    {"id": 2,   "nombre": "310+31 💎",    "precio": 3},
    {"id": 3,   "nombre": "520+52 💎",    "precio": 5},
    {"id": 4,   "nombre": "1060+106 💎",  "precio": 10},
    {"id": 5,   "nombre": "2180+218 💎",  "precio": 20},
    {"id": 6,   "nombre": "5600+560 💎",  "precio": 50},
    {"id": 155, "nombre": "Tarjeta Básica",   "precio": 1},
    {"id": 156, "nombre": "Tarjeta Semanal",  "precio": 3},
    {"id": 157, "nombre": "Tarjeta Mensual",  "precio": 11},
    {"id": 158, "nombre": "Pase Booyah",      "precio": 4},
]

def enviar_mensaje(chat_id, texto, teclado=None):
    datos = {"chat_id": chat_id, "text": texto}
    if teclado:
        datos["reply_markup"] = teclado
    requests.post(f"{URL_TELEGRAM}/sendMessage", json=datos)

def teclado_opciones(opciones):
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

def menu_productos():
    return teclado_opciones([f"{p['nombre']} ${p['precio']}" for p in PRODUCTOS])

@app.route("/webhook", methods=["POST"])
def webhook():
    datos = request.json
    if not datos or "message" not in datos:
        return jsonify({"status": "ok"})

    chat_id = datos["message"]["chat"]["id"]
    texto = datos["message"].get("text", "").strip()
    sesion = sesiones.get(chat_id, {})

    # LOGIN
    if texto == "/start" or not sesion.get("usuario"):
        enviar_mensaje(chat_id, "👤 ¿Quién eres?", teclado_opciones(["MD", "Albo", "Ocho"]))
        sesiones[chat_id] = {"paso": "login"}
        return jsonify({"status": "ok"})

    if sesion.get("paso") == "login":
        if texto in ["MD", "Albo", "Ocho"]:
            sesiones[chat_id] = {"usuario": texto, "paso": "menu"}
            enviar_mensaje(chat_id, f"✅ Bienvenido {texto}!\n\nElige un comando:\n/recargar - Nueva recarga\n/reporte - Ver recargas de hoy\n/saldo - Ver saldo")
        else:
            enviar_mensaje(chat_id, "❌ Usuario no válido.", teclado_opciones(["MD", "Albo", "Ocho"]))
        return jsonify({"status": "ok"})

    usuario = sesion.get("usuario")

    # COMANDOS PRINCIPALES
    if texto == "/saldo":
        resp = requests.get(f"{URL_TIENDA}/saldo", headers={"X-API-Key": API_KEY_TIENDA}).json()
        enviar_mensaje(chat_id, f"💰 Saldo disponible: ${resp.get('saldo', 'error')}")
        return jsonify({"status": "ok"})

    if texto == "/reporte":
        resp = requests.get(f"{URL_TIENDA}/pedidos", headers={"X-API-Key": API_KEY_TIENDA}).json()
        pedidos = resp.get("pedidos", [])
        from datetime import datetime
        hoy = datetime.now().strftime("%Y-%m-%d")
        reporte = {}
        for p in pedidos:
            if hoy in p.get("fecha_pedido", "") and p.get("estado") == "completado":
                op = p.get("descripcion", "desconocido")
                reporte[op] = reporte.get(op, 0) + 1
        if reporte:
            texto_reporte = "📊 Recargas de hoy:\n"
            for k, v in reporte.items():
                texto_reporte += f"• {k}: {v}\n"
        else:
            texto_reporte = "📊 No hay recargas completadas hoy."
        enviar_mensaje(chat_id, texto_reporte)
        return jsonify({"status": "ok"})

    if texto == "/recargar":
        sesiones[chat_id]["paso"] = "elegir_producto"
        enviar_mensaje(chat_id, "💎 Elige el monto de recarga:", menu_productos())
        return jsonify({"status": "ok"})

    # FLUJO DE RECARGA
    if sesion.get("paso") == "elegir_producto":
        producto = next((p for p in PRODUCTOS if f"{p['nombre']} ${p['precio']}" == texto), None)
        if not producto:
            enviar_mensaje(chat_id, "❌ Elige una opción válida.", menu_productos())
            return jsonify({"status": "ok"})
        sesiones[chat_id]["producto"] = producto
        sesiones[chat_id]["paso"] = "pedir_id"
        enviar_mensaje(chat_id, f"✅ Seleccionaste: {producto['nombre']} ${producto['precio']}\n\n🔢 Escribe el ID del jugador en Free Fire:")
        return jsonify({"status": "ok"})

    if sesion.get("paso") == "pedir_id":
        id_jugador = texto
        # Verificar ID consultando el nombre del jugador
        sesiones[chat_id]["id_jugador"] = id_jugador
        sesiones[chat_id]["paso"] = "confirmar"
        producto = sesion["producto"]
        enviar_mensaje(chat_id,
            f"⚠️ Confirma la recarga:\n\n"
            f"👤 ID: {id_jugador}\n"
            f"💎 Producto: {producto['nombre']}\n"
            f"💵 Precio: ${producto['precio']}\n\n"
            f"¿Confirmas?",
            teclado_opciones(["✅ Confirmar", "❌ Cancelar"])
        )
        return jsonify({"status": "ok"})

    if sesion.get("paso") == "confirmar":
        if texto == "✅ Confirmar":
            producto = sesion["producto"]
            id_jugador = sesion["id_jugador"]
            enviar_mensaje(chat_id, "⏳ Procesando recarga...")
            resp = requests.post(f"{URL_TIENDA}/comprar", 
                headers={"X-API-Key": API_KEY_TIENDA},
                json={"producto_id": producto["id"], "id_juego": id_jugador}
            ).json()
            if resp.get("ok"):
                enviar_mensaje(chat_id,
                    f"✅ ¡Recarga exitosa!\n\n"
                    f"👤 Jugador: {resp.get('nombre_jugador', id_jugador)}\n"
                    f"💎 {producto['nombre']}\n"
                    f"🧾 Pedido #: {resp.get('pedido_id')}\n"
                    f"💰 Saldo restante: ${resp.get('saldo_restante')}\n"
                    f"👨‍💼 Operador: {usuario}"
                )
            else:
                enviar_mensaje(chat_id, f"❌ Error: {resp.get('error')}")
            sesiones[chat_id]["paso"] = "menu"
        elif texto == "❌ Cancelar":
            sesiones[chat_id]["paso"] = "menu"
            enviar_mensaje(chat_id, "❌ Recarga cancelada.\n\n/recargar - Nueva recarga\n/saldo - Ver saldo")
        return jsonify({"status": "ok"})

    enviar_mensaje(chat_id, "Usa /recargar para nueva recarga\n/saldo para ver saldo\n/reporte para ver recargas de hoy")
    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return "Bot activo", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
    
