import os
import requests
from flask import Flask, request
from datetime import datetime

TOKEN_BOT = os.environ.get("TOKEN_BOT")
API_KEY_TIENDA = os.environ.get("API_KEY_TIENDA")
URL_TELEGRAM = f"https://api.telegram.org/bot{TOKEN_BOT}"
URL_TIENDA = "https://tiendagiftven.tech/api/v1"
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

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
    {"id": 155, "nombre": "Tarjeta Basica",  "precio": 1},
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
def sb_crear_usuario(nombre, password):
    requests.post(
        f"{SUPABASE_URL}/rest/v1/usuarios",
        headers=HEADERS_SB,
        json={"nombre": nombre, "password": password, "saldo": 0, "es_admin": False}
    )

def sb_guardar_recarga(usuario, producto, monto, id_jugador, pedido_id):
    from datetime import datetime, timezone, timedelta
    
    # Calculamos la hora exacta en UTC-5
    zona = timezone(timedelta(hours=-5))
    ahora_local = datetime.now(zona).strftime("%Y-%m-%dT%H:%M:%S")
    
    requests.post(
        f"{SUPABASE_URL}/rest/v1/recargas",
        headers=HEADERS_SB,
        json={
            "usuario": usuario,
            "producto": producto,
            "monto": monto,
            "id_jugador": id_jugador,
            "pedido_id": pedido_id,
            "fecha": ahora_local  # Forzamos la hora local aquí
        }
    )

def sb_get_recargas_hoy(usuario=None):
    from datetime import datetime, timezone, timedelta
    
    zona = timezone(timedelta(hours=-5))
    ahora = datetime.now(zona)
    
    # Creamos los límites del día actual en hora local
    inicio_local = ahora.strftime("%Y-%m-%dT00:00:00")
    fin_local = ahora.strftime("%Y-%m-%dT23:59:59")
    
    url = f"{SUPABASE_URL}/rest/v1/recargas?fecha=gte.{inicio_local}&fecha=lte.{fin_local}&select=*&order=fecha.desc"
    
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
        enviar(chat_id, f"Bienvenido Admin\n\n/recargar - Nueva recarga\n/saldo - Saldo tienda\n/reporte - Reportes\n/usuarios - Saldo por local\n/asignar - Asignar saldo a local\n/nuevo - Crear usuario")
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
        enviar(chat_id, "Escribe tu nombre de usuario:")
        return {"status": "ok"}

    if not sesion:
        sesiones[chat_id] = {"paso": "login_nombre"}
        enviar(chat_id, "Escribe tu nombre de usuario:")
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

    if texto == "/usuarios":
        if not es_admin:
            enviar(chat_id, "Solo el admin puede ver esto.")
            return {"status": "ok"}
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/usuarios?select=nombre,saldo&es_admin=eq.false",
            headers=HEADERS_SB
        )
        usuarios_db = r.json()
        msg = "Saldos por local:\n\n"
        for u in usuarios_db:
            msg += f"👤 {u['nombre']}: ${u['saldo']}\n"
        enviar(chat_id, msg)
        return {"status": "ok"}

    if texto == "/reporte":
        if es_admin:
            sesiones[chat_id]["paso"] = "reporte_tipo"
            enviar(chat_id, "Que reporte deseas ver?", botones(["Ventas de hoy", "Saldos por local"]))
        else:
            recargas = sb_get_recargas_hoy(usuario)
            if not recargas:
                enviar(chat_id, "No hay recargas hoy.")
                return {"status": "ok"}
            msg = "Recargas de hoy:\n\n"
            total = 0
            for r in recargas:
                msg += f"{r['producto']} | ${r['monto']} | ID: {r['id_jugador']} | Pedido #{r['pedido_id']}\n"
                total += float(r['monto'])
            msg += f"\nTotal: ${total:.2f}"
            enviar(chat_id, msg)
        return {"status": "ok"}

    if paso == "reporte_tipo":
        if texto == "Saldos por local":
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/usuarios?select=nombre,saldo&es_admin=eq.false",
                headers=HEADERS_SB
            )
            usuarios_db = r.json()
            msg = "Saldos por local:\n\n"
            for u in usuarios_db:
                msg += f"👤 {u['nombre']}: ${u['saldo']}\n"
            enviar(chat_id, msg)
            sesiones[chat_id]["paso"] = "menu"
        elif texto == "Ventas de hoy":
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/usuarios?select=nombre&es_admin=eq.false",
                headers=HEADERS_SB
            )
            usuarios_db = [u["nombre"] for u in r.json()]
            opciones = ["Todos"] + usuarios_db
            sesiones[chat_id]["paso"] = "reporte_elegir"
            enviar(chat_id, "De que usuario?", botones(opciones))
        return {"status": "ok"}

    if paso == "reporte_elegir":
        filtro = None if texto == "Todos" else texto
        recargas = sb_get_recargas_hoy(filtro)
        titulo = f"Ventas de hoy - {texto}:"
        if not recargas:
            enviar(chat_id, f"No hay recargas hoy para {texto}.")
            sesiones[chat_id]["paso"] = "menu"
            return {"status": "ok"}
        msg = f"{titulo}\n\n"
        total = 0
        for r in recargas:
            msg += f"{r['usuario']} | {r['producto']} | ${r['monto']} | ID: {r['id_jugador']} | Pedido #{r['pedido_id']}\n"
            total += float(r['monto'])
        msg += f"\nTotal: ${total:.2f}"
        enviar(chat_id, msg)
        sesiones[chat_id]["paso"] = "menu"
        return {"status": "ok"}
    if texto == "/nuevo":
        if not es_admin:
            enviar(chat_id, "Solo el admin puede crear usuarios.")
            return {"status": "ok"}
        sesiones[chat_id]["paso"] = "nuevo_nombre"
        enviar(chat_id, "Escribe el nombre del nuevo usuario:")
        return {"status": "ok"}

    if paso == "nuevo_nombre":
        nombre_nuevo = texto
        u = sb_get_usuario(nombre_nuevo)
        if u:
            enviar(chat_id, f"Ya existe un usuario con ese nombre. Escribe otro:")
            return {"status": "ok"}
        import random, string
        letras = random.choices(string.ascii_uppercase, k=2)
        numeros = random.choices(string.digits, k=2)
        pwd_sugerida = "".join(letras + numeros)
        sesiones[chat_id]["nuevo_nombre"] = nombre_nuevo
        sesiones[chat_id]["pwd_sugerida"] = pwd_sugerida
        sesiones[chat_id]["paso"] = "nuevo_password"
        enviar(chat_id, 
            f"Usuario: {nombre_nuevo}\n"
            f"Contrasena sugerida: {pwd_sugerida}\n\n"
            f"Escribe una contrasena o envía 'ok' para usar la sugerida:",
        )
        return {"status": "ok"}

    if paso == "nuevo_password":
        texto_limpio = texto.strip().lower().replace("👍", "ok").replace("✅", "ok")
        if texto_limpio == "ok":
            pwd_final = sesiones[chat_id]["pwd_sugerida"]
        elif len(texto) < 4:
            enviar(chat_id, "La contrasena debe tener al menos 4 caracteres. Intenta de nuevo o escribe 'ok' para usar la sugerida:")
            return {"status": "ok"}
        else:
            import re
            if not re.match(r'^[a-zA-Z0-9]+$', texto):
                enviar(chat_id, "Solo letras y numeros permitidos. Intenta de nuevo o escribe 'ok' para usar la sugerida:")
                return {"status": "ok"}
            pwd_final = texto
        
        nombre_nuevo = sesiones[chat_id]["nuevo_nombre"]
        sesiones[chat_id]["paso"] = "nuevo_saldo"
        sesiones[chat_id]["nuevo_password"] = pwd_final
        enviar(chat_id, f"Cuanto saldo inicial para {nombre_nuevo}? (escribe 0 si ninguno)")
        return {"status": "ok"}

    if paso == "nuevo_saldo":
        try:
            saldo_inicial = float(texto)
            nombre_nuevo = sesiones[chat_id]["nuevo_nombre"]
            pwd_final = sesiones[chat_id]["nuevo_password"]
            sb_crear_usuario(nombre_nuevo, pwd_final)
            if saldo_inicial > 0:
                sb_recargar_saldo(nombre_nuevo, saldo_inicial)
            sesiones[chat_id]["paso"] = "menu"
            enviar(chat_id,
                f"Usuario creado!\n\n"
                f"Nombre: {nombre_nuevo}\n"
                f"Contrasena: {pwd_final}\n"
                f"Saldo inicial: ${saldo_inicial}"
            )
        except:
            enviar(chat_id, "Escribe un numero valido.")
        return {"status": "ok"}
    
    if texto == "/asignar":
        if not es_admin:
            enviar(chat_id, "Solo el admin puede asignar saldo.")
            return {"status": "ok"}
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/usuarios?select=nombre&es_admin=eq.false",
            headers=HEADERS_SB
        )
        usuarios_db = [u["nombre"] for u in r.json()]
        sesiones[chat_id]["paso"] = "asignar_local"
        enviar(chat_id, "A que local asignar saldo?", botones(usuarios_db))
        return {"status": "ok"}

    if paso == "asignar_local":
        u = sb_get_usuario(texto)
        if u and not u["es_admin"]:
            sesiones[chat_id]["asignar_a"] = texto
            sesiones[chat_id]["paso"] = "asignar_monto"
            enviar(chat_id, f"Cuanto saldo asignar a {texto}?")
        else:
            enviar(chat_id, "Local no valido.")
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
    return "Bot activo v6", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
