import os
import requests
from flask import Flask, request
from datetime import datetime

TOKEN_BOT = "7864266536:AAHW3BMrhRqDzeUsaydQQ6Pum5KbCpG8GEM"
API_KEY_TIENDA = "2fc6bc5920314acce1467adb2e95dbd369e7312f31a7c465f6aef0fb86d7537d"
URL_TELEGRAM = f"https://api.telegram.org/bot{TOKEN_BOT}"
URL_TIENDA = "https://tiendagiftven.tech/api/v1"
SUPABASE_URL = "https://djicdsioescrhoydlvdz.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRqaWNkc2lvZXNjcmhveWRsdmR6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYzNzEzNTUsImV4cCI6MjA5MTk0NzM1NX0.dPfDVoM7-GyjvsWyCSzczlYYjMwWByhL2Z8PQ7HeTzI"

HEADERS_SB = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

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

def sb_get_usuario(nombre):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/usuarios?nombre=eq.{nombre}&select=*",
        headers=HEADERS_SB
    )
    data = r.json()
    return data[0] if data else None

def sb_descontar_saldo(nombre, monto):
    u = sb_get_usuario(nombre)
    nuevo = float(u["saldo"]) - monto
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/usuarios?nombre=eq.{nombre}",
        headers=HEADERS_SB,
        json={"saldo": nuevo}
    )

def sb_recargar_saldo(nombre, monto):
    u = sb_get_usuario(nombre)
    nuevo = float(u["saldo"]) + monto
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/usuarios?nombre=eq.{nombre}",
        headers=HEADERS_SB,
        json={"saldo": nuevo}
    )

def sb_guardar_recarga(usuario, producto, monto, id_jugador, pedido_id):
    requests.post(
        f"{SUPABASE_URL}/rest/v1/recargas",
        headers=HEADERS_SB,
        json={
            "usuario": usuario,
            "producto": producto,
            "monto": monto,
            "id_jugador": id_jugador,
            "pedido_id": pedido_id
        }
    )

def sb_get_recargas_hoy(usuario=None):
    hoy = datetime.now().strftime("%Y-%m-%d")
    url = f"{SUPABASE_URL}/rest/v1/recargas?fecha=gte.{hoy}&select=*&order=fecha.desc"
    if usuario:
        url += f"&usuario=eq.{usuario}"
    r = requests.get(url, headers=HEADERS_SB)
    return r.json()

def enviar(chat_id, texto, teclado=None):
    datos = {"chat_id": chat_id, "text": texto}
    if teclado:
        datos["reply_markup"] = teclado
    requests.post(f"{URL_TELEGRAM}/sendMessage", json=datos)

def botones(opciones):
    filas = []
    fila = []
    for op in opciones:
        fila.append({"text": op})
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    return {"keyboard": filas, "resize_keyboard": True, "one_time_keyboard": True}

def menu_principal(chat_id, usuario, saldo):
    if usuario == "Admin":
        enviar(chat_id, f"👑 Bienvenido Admin\n\n/recargar - Nueva recarga\n/saldo - Saldo tienda\n/reporte - Reporte completo\n/asignar - Asignar saldo a local")
    else:
        enviar(chat_id, f"Bienvenido {usuario}\nTu saldo: ${saldo}\n\n/recargar - Nueva recarga\n/saldo - Ver mi saldo\n/reporte - Mis recargas de hoy")

@app.route("/webhook", methods=["POST"])
def webhook():
    datos = request.json
    if not datos or "message" not in datos:
        return {"status": "ok"}

    chat_id = datos["message"]["chat"]["id"]
    texto = datos["message"].get("text", "").strip()
    sesion = sesiones.get(chat_id, {})

    if texto == "/start":
        sesiones[chat_id] = {"paso": "login_nombre"}
        enviar(chat_id, "👤 Escribe tu nombre de usuario:")
        return {"status": "ok"}

    if not sesion:
        sesiones[chat_id] = {"paso": "login_nombre"}
        enviar(chat_id, "👤 Escribe tu nombre de usuario:")
        return {"status": "ok"}

    paso = sesion.get("paso", "")
    usuario = sesion.get("usuario", "")
    es_admin = sesion.get("es_admin", False)

    if paso == "login_nombre":
        sesiones[chat_id]["nombre_tmp"] = texto
        sesiones[chat_id]["paso"] = "login_password"
        enviar(chat_id, "Escribe tu contrasena:")
        return {"status": "ok"}

    if paso == "login_password":
        nombre = sesion.get("nombre_tmp")
        u = sb_get_usuario(nombre)
        if u and u["password"] == texto:
            sesiones[chat_id] = {
                "paso": "menu",
                "usuario": u["nombre"],
                "es_admin": u["es_admin"]
            }
            menu_principal(chat_id, u["nombre"], u["saldo"])
        else:
            enviar(chat_id, "Usuario o contrasena incorrectos. Escribe /start para intentar de nuevo.")
            sesiones.pop(chat_id, None)
        return {"status": "ok"}

    if texto == "/saldo":
        if es_admin:
            resp = requests.get(f"{URL_TIENDA}/saldo", headers={"X-API-Key": API_KEY_TIENDA}).json()
            enviar(chat_id, f"Saldo en tienda: ${resp.get('saldo')}")
        else:
            u = sb_get_usuario(usuario)
            enviar(chat_id, f"Tu saldo: ${u['saldo']}")
        return {"status": "ok"}

    if texto == "/reporte":
        recargas = sb_get_recargas_hoy(None if es_admin else usuario)
        if not recargas:
            enviar(chat_id, "No hay recargas hoy.")
            return {"status": "ok"}
        msg = "Recargas de hoy:\n\n"
        total = 0
        for r in recargas:
            msg += f"{r['usuario']} | {r['producto']} | ${r['monto']} | ID: {r['id_jugador']} | Pedido #{r['pedido_id']}\n"
            total += float(r['monto'])
        msg += f"\nTotal: ${total:.2f}"
        enviar(chat_id, msg)
        return {"status": "ok"}

    if texto == "/asignar":
        if not es_admin:
            enviar(chat_id, "Solo el admin puede asignar saldo.")
            return {"status": "ok"}
        sesiones[chat_id]["paso"] = "asignar_local"
        enviar(chat_id, "A que local asignar saldo?", botones(["MD", "Albo", "Ocho"]))
        return {"status": "ok"}

    if paso == "asignar_local":
        if texto in ["MD", "Albo", "Ocho"]:
            sesiones[chat_id]["asignar_a"] = texto
            sesiones[chat_id]["paso"] = "asignar_monto"
            enviar(chat_id, f"Cuanto saldo asignar a {texto}?")
        else:
            enviar(chat_id, "Local no valido.", botones(["MD", "Albo", "Ocho"]))
        return {"status": "ok"}

    if paso == "asignar_monto":
        try:
            monto = float(texto)
            local = sesion["asignar_a"]
            sb_recargar_saldo(local, monto)
            sesiones[chat_id]["paso"] = "menu"
            enviar(chat_id, f"Se asignaron ${monto} a {local}.")
        except:
            enviar(chat_id, "Escribe un numero valido.")
        return {"status": "ok"}

    if texto == "/recargar":
        if not es_admin:
            u = sb_get_usuario(usuario)
            if float(u["saldo"]) <= 0:
                enviar(chat_id, "No tienes saldo. Contacta al admin.")
                return {"status": "ok"}
        sesiones[chat_id]["paso"] = "elegir_producto"
        ops = [f"{p['nombre']} ${p['precio']}" for p in PRODUCTOS]
        enviar(chat_id, "Elige el monto:", botones(ops))
        return {"status": "ok"}

    if paso == "elegir_producto":
        producto = next((p for p in PRODUCTOS if f"{p['nombre']} ${p['precio']}" == texto), None)
        if not producto:
            ops = [f"{p['nombre']} ${p['precio']}" for p in PRODUCTOS]
            enviar(chat_id, "Elige una opcion valida.", botones(ops))
            return {"status": "ok"}
        if not es_admin:
            u = sb_get_usuario(usuario)
            if float(u["saldo"]) < producto["precio"]:
                enviar(chat_id, f"Saldo insuficiente. Tu saldo: ${u['saldo']}")
                sesiones[chat_id]["paso"] = "menu"
                return {"status": "ok"}
        sesiones[chat_id]["producto"] = producto
        sesiones[chat_id]["paso"] = "pedir_id"
        enviar(chat_id, f"{producto['nombre']} ${producto['precio']}\n\nEscribe el ID del jugador en Free Fire:")
        return {"status": "ok"}

    if paso == "pedir_id":
        sesiones[chat_id]["id_jugador"] = texto
        sesiones[chat_id]["paso"] = "confirmar"
        p = sesion["producto"]
        enviar(chat_id,
            f"Confirma la recarga:\n\n"
            f"ID: {texto}\n"
            f"{p['nombre']}\n"
            f"${p['precio']}\n\n"
            f"Confirmas?",
            botones(["Confirmar", "Cancelar"])
        )
        return {"status": "ok"}

    if paso == "confirmar":
        if texto == "Confirmar":
            p = sesion["producto"]
            id_jugador = sesion["id_jugador"]
            enviar(chat_id, "Procesando recarga...")
            resp = requests.post(f"{URL_TIENDA}/comprar",
                headers={"X-API-Key": API_KEY_TIENDA},
                json={"producto_id": p["id"], "id_juego": id_jugador}
            ).json()
            if resp.get("ok"):
                if not es_admin:
                    sb_descontar_saldo(usuario, p["precio"])
                sb_guardar_recarga(usuario, p["nombre"], p["precio"], id_jugador, resp.get("pedido_id"))
                u = sb_get_usuario(usuario)
                saldo_local = u["saldo"] if not es_admin else "-"
                enviar(chat_id,
                    f"Recarga exitosa!\n\n"
                    f"Jugador: {resp.get('nombre_jugador', id_jugador)}\n"
                    f"{p['nombre']}\n"
                    f"Pedido #: {resp.get('pedido_id')}\n"
                    f"Tu saldo restante: ${saldo_local}\n"
                    f"Operador: {usuario}"
                )
            else:
                enviar(chat_id, f"Error: {resp.get('error')}")
        else:
            enviar(chat_id, "Recarga cancelada.")
        sesiones[chat_id]["paso"] = "menu"
        return {"status": "ok"}

    enviar(chat_id, "Usa /recargar, /saldo o /reporte")
    return {"status": "ok"}

@app.route("/")
def index():
    return "Bot activo v5", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
