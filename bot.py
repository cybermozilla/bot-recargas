import os
import requests
import psycopg2
from flask import Flask, request, jsonify
from datetime import datetime

TOKEN_BOT = "7864266536:AAHW3BMrhRqDzeUsaydQQ6Pum5KbCpG8GEM"
API_KEY_TIENDA = "2fc6bc5920314acce1467adb2e95dbd369e7312f31a7c465f6aef0fb86d7537d"
URL_TELEGRAM = f"https://api.telegram.org/bot{TOKEN_BOT}"
URL_TIENDA = "https://tiendagiftven.tech/api/v1"
DATABASE_URL = "postgresql://postgres:BDMICRO88ec@db.djicdsioescrhoydlvdz.supabase.co:5432/postgres"

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

def db():
    return psycopg2.connect(DATABASE_URL)

def get_usuario(nombre):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT nombre, password, saldo, es_admin FROM usuarios WHERE nombre=%s", (nombre,))
    row = cur.fetchone()
    con.close()
    if row:
        return {"nombre": row[0], "password": row[1], "saldo": row[2], "es_admin": row[3]}
    return None

def descontar_saldo(nombre, monto):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE usuarios SET saldo = saldo - %s WHERE nombre=%s", (monto, nombre))
    con.commit()
    con.close()

def recargar_saldo(nombre, monto):
    con = db()
    cur = con.cursor()
    cur.execute("UPDATE usuarios SET saldo = saldo + %s WHERE nombre=%s", (monto, nombre))
    con.commit()
    con.close()

def guardar_recarga(usuario, producto, monto, id_jugador, pedido_id):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO recargas (usuario, producto, monto, id_jugador, pedido_id) VALUES (%s,%s,%s,%s,%s)",
        (usuario, producto, monto, id_jugador, pedido_id)
    )
    con.commit()
    con.close()

def get_recargas_hoy(usuario=None):
    con = db()
    cur = con.cursor()
    hoy = datetime.now().strftime("%Y-%m-%d")
    if usuario:
        cur.execute("SELECT usuario, producto, monto, id_jugador, pedido_id, fecha FROM recargas WHERE usuario=%s AND DATE(fecha)=%s ORDER BY fecha DESC", (usuario, hoy))
    else:
        cur.execute("SELECT usuario, producto, monto, id_jugador, pedido_id, fecha FROM recargas WHERE DATE(fecha)=%s ORDER BY fecha DESC", (hoy,))
    rows = cur.fetchall()
    con.close()
    return rows

def enviar(chat_id, texto, teclado=None):
    datos = {"chat_id": chat_id, "text": texto, "parse_mode": "HTML"}
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
    sesiones[chat_id] = {"paso": "login_nombre"}
    enviar(chat_id, "👤 Escribe tu nombre de usuario:")

def menu_principal(chat_id, usuario, saldo):
    if usuario == "Admin":
        enviar(chat_id, f"👑 Bienvenido Admin\n\n/recargar - Nueva recarga\n/saldo - Saldo tienda\n/reporte - Reporte completo\n/asignar - Asignar saldo a local")
    else:
        enviar(chat_id, f"✅ Bienvenido <b>{usuario}</b>\n💰 Tu saldo: <b>${saldo}</b>\n\n/recargar - Nueva recarga\n/saldo - Ver mi saldo\n/reporte - Mis recargas de hoy")

@app.route("/webhook", methods=["POST"])
def webhook():
    datos = request.json
    if not datos or "message" not in datos:
        return {"status": "ok"}

    chat_id = datos["message"]["chat"]["id"]
    texto = datos["message"].get("text", "").strip()
    sesion = sesiones.get(chat_id, {})

    if texto == "/start":
        pedir_usuario(chat_id)
        return {"status": "ok"}

    if not sesion:
        pedir_usuario(chat_id)
        return {"status": "ok"}

    paso = sesion.get("paso", "")
    usuario = sesion.get("usuario", "")
    es_admin = sesion.get("es_admin", False)

    # LOGIN - pedir nombre
    if paso == "login_nombre":
        sesiones[chat_id]["nombre_tmp"] = texto
        sesiones[chat_id]["paso"] = "login_password"
        enviar(chat_id, "🔑 Escribe tu contraseña:")
        return {"status": "ok"}

    # LOGIN - verificar password
    if paso == "login_password":
        nombre = sesion.get("nombre_tmp")
        u = get_usuario(nombre)
        if u and u["password"] == texto:
            sesiones[chat_id] = {
                "paso": "menu",
                "usuario": u["nombre"],
                "es_admin": u["es_admin"]
            }
            menu_principal(chat_id, u["nombre"], u["saldo"])
        else:
            enviar(chat_id, "❌ Usuario o contraseña incorrectos. Escribe /start para intentar de nuevo.")
            sesiones.pop(chat_id, None)
        return {"status": "ok"}

    # COMANDO: ver saldo
    if texto == "/saldo":
        if es_admin:
            resp = requests.get(f"{URL_TIENDA}/saldo", headers={"X-API-Key": API_KEY_TIENDA}).json()
            enviar(chat_id, f"💰 Saldo en tienda: <b>${resp.get('saldo')}</b>")
        else:
            u = get_usuario(usuario)
            enviar(chat_id, f"💰 Tu saldo disponible: <b>${u['saldo']}</b>")
        return {"status": "ok"}

    # COMANDO: reporte
    if texto == "/reporte":
        recargas = get_recargas_hoy(None if es_admin else usuario)
        if not recargas:
            enviar(chat_id, "📊 No hay recargas hoy.")
            return {"status": "ok"}
        msg = "📊 <b>Recargas de hoy:</b>\n\n"
        total = 0
        for r in recargas:
            msg += f"👤 {r[0]} | {r[1]} | ${r[2]} | ID: {r[3]} | Pedido #{r[4]}\n"
            total += float(r[2])
        msg += f"\n💵 <b>Total: ${total:.2f}</b>"
        enviar(chat_id, msg)
        return {"status": "ok"}

    # COMANDO: asignar saldo (solo admin)
    if texto == "/asignar":
        if not es_admin:
            enviar(chat_id, "❌ Solo el admin puede asignar saldo.")
            return {"status": "ok"}
        sesiones[chat_id]["paso"] = "asignar_local"
        enviar(chat_id, "¿A qué local asignar saldo?", botones(["MD", "Albo", "Ocho"]))
        return {"status": "ok"}

    if paso == "asignar_local":
        if texto in ["MD", "Albo", "Ocho"]:
            sesiones[chat_id]["asignar_a"] = texto
            sesiones[chat_id]["paso"] = "asignar_monto"
            enviar(chat_id, f"💵 ¿Cuánto saldo asignar a {texto}?")
        else:
            enviar(chat_id, "❌ Local no válido.", botones(["MD", "Albo", "Ocho"]))
        return {"status": "ok"}

    if paso == "asignar_monto":
        try:
            monto = float(texto)
            local = sesion["asignar_a"]
            recargar_saldo(local, monto)
            sesiones[chat_id]["paso"] = "menu"
            enviar(chat_id, f"✅ Se asignaron ${monto} a {local}.")
        except:
            enviar(chat_id, "❌ Escribe un número válido.")
        return {"status": "ok"}

    # COMANDO: recargar
    if texto == "/recargar":
        if not es_admin:
            u = get_usuario(usuario)
            if float(u["saldo"]) <= 0:
                enviar(chat_id, "❌ No tienes saldo disponible. Contacta al admin.")
                return {"status": "ok"}
        sesiones[chat_id]["paso"] = "elegir_producto"
        ops = [f"{p['nombre']} ${p['precio']}" for p in PRODUCTOS]
        enviar(chat_id, "💎 Elige el monto:", botones(ops))
        return {"status": "ok"}

    if paso == "elegir_producto":
        producto = next((p for p in PRODUCTOS if f"{p['nombre']} ${p['precio']}" == texto), None)
        if not producto:
            ops = [f"{p['nombre']} ${p['precio']}" for p in PRODUCTOS]
            enviar(chat_id, "❌ Elige una opción válida.", botones(ops))
            return {"status": "ok"}
        if not es_admin:
            u = get_usuario(usuario)
            if float(u["saldo"]) < producto["precio"]:
                enviar(chat_id, f"❌ Saldo insuficiente. Tu saldo: ${u['saldo']}")
                sesiones[chat_id]["paso"] = "menu"
                return {"status": "ok"}
        sesiones[chat_id]["producto"] = producto
        sesiones[chat_id]["paso"] = "pedir_id"
        enviar(chat_id, f"✅ {producto['nombre']} ${producto['precio']}\n\n🔢 Escribe el ID del jugador en Free Fire:")
        return {"status": "ok"}

    if paso == "pedir_id":
        sesiones[chat_id]["id_jugador"] = texto
        sesiones[chat_id]["paso"] = "confirmar"
        p = sesion["producto"]
        enviar(chat_id,
            f"⚠️ <b>Confirma la recarga:</b>\n\n"
            f"👤 ID: {texto}\n"
            f"💎 {p['nombre']}\n"
            f"💵 ${p['precio']}\n\n"
            f"¿Confirmas?",
            botones(["✅ Confirmar", "❌ Cancelar"])
        )
        return {"status": "ok"}

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
                if not es_admin:
                    descontar_saldo(usuario, p["precio"])
                guardar_recarga(usuario, p["nombre"], p["precio"], id_jugador, resp.get("pedido_id"))
                u = get_usuario(usuario)
                saldo_local = u["saldo"] if not es_admin else "-"
                enviar(chat_id,
                    f"✅ <b>¡Recarga exitosa!</b>\n\n"
                    f"👤 Jugador: {resp.get('nombre_jugador', id_jugador)}\n"
                    f"💎 {p['nombre']}\n"
                    f"🧾 Pedido #: {resp.get('pedido_id')}\n"
                    f"💰 Tu saldo restante: ${saldo_local}\n"
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
    return "Bot activo v4", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
