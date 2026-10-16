import os
import json
import hmac
import hashlib
import time
import uuid
import requests
from flask import Flask, request
from datetime import datetime

TOKEN_BOT = os.environ.get("TOKEN_BOT")
API_KEY_TIENDA = os.environ.get("API_KEY_TIENDA")
URL_TELEGRAM = f"https://api.telegram.org/bot{TOKEN_BOT}"
URL_TIENDA = "https://tiendagiftven.tech/api/v1"
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ===== LioGames (opcion 2, solo Admin) =====
LIO_PASSWORD = os.environ.get("LIO_PASSWORD")
LIO_MEMBER_CODE = os.environ.get("LIO_MEMBER_CODE")
LIO_SECRET = os.environ.get("LIO_SECRET")
LIO_KEY_ID = os.environ.get("LIO_KEY_ID")
LIO_SANDBOX = os.environ.get("LIO_SANDBOX") == "1"
URL_LIO = "https://distribution.liogames.com/api/v1"
LIO_PRODUCT_ID = 65871  # Free Fire (LATAM)
LIO_GAME_SLUG = "free-fire-global"  # Username API: no existe slug LATAM

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

LIO_PRODUCTOS = [
    {"variation_id": 533711, "nombre": "110 Diamantes",   "precio": 0.67},
    {"variation_id": 533713, "nombre": "341 Diamantes",   "precio": 2.01},
    {"variation_id": 533715, "nombre": "572 Diamantes",   "precio": 3.40},
    {"variation_id": 533717, "nombre": "1166 Diamantes",  "precio": 6.31},
    {"variation_id": 533719, "nombre": "2398 Diamantes",  "precio": 12.52},
    {"variation_id": 533720, "nombre": "6160 Diamantes",  "precio": 31.88},
    {"variation_id": 533724, "nombre": "Tarjeta Mensual", "precio": 9.69},
]

def lio_firmar(cuerpo_bytes):
    return hmac.new(LIO_SECRET.encode(), cuerpo_bytes, hashlib.sha256).hexdigest()

def lio_post(ruta, payload, timeout=30):
    cuerpo = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "x-liog-sign": lio_firmar(cuerpo)}
    if LIO_KEY_ID:
        headers["X-LIOG-KEY-ID"] = LIO_KEY_ID
    return requests.post(f"{URL_LIO}{ruta}", data=cuerpo, headers=headers, timeout=timeout).json()

def lio_productos_con_precio():
    """Precios GOLD en vivo; si falla, usa los precios fijos."""
    productos = [dict(p) for p in LIO_PRODUCTOS]
    try:
        r = requests.get(f"{URL_LIO}/products/{LIO_PRODUCT_ID}/price-matrix", timeout=10).json()
        precios = {row["variation_id"]: row.get("prices", {}).get("gold") for row in r.get("data", {}).get("rows", [])}
        for p in productos:
            if precios.get(p["variation_id"]):
                p["precio"] = round(float(precios[p["variation_id"]]), 2)
    except Exception:
        pass
    return productos

def lio_etiqueta(p):
    return f"{p['nombre']} ${p['precio']:.2f}"

def lio_estado(resp):
    """Devuelve (estado_en_mayusculas, order_id) desde la respuesta de LioGames."""
    data = resp.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("order"), dict):
        data = data["order"]
    estado = str(data.get("status") or resp.get("code") or "").upper() if isinstance(data, dict) else str(resp.get("code", "")).upper()
    order_id = None
    if isinstance(data, dict):
        order_id = data.get("order_id") or data.get("id")
    return estado, order_id

LIO_EXITO = ("COMPLETED", "COMPLETE", "SUCCESS", "SUCCESSFUL", "DELIVERED", "DONE")
LIO_PENDIENTE = ("PROCESSING", "PENDING", "ON-HOLD", "ON_HOLD", "QUEUED", "IN_PROGRESS")

def lio_consultar(order_id=None, client_ref=None):
    ruta = "/sandbox/order-status" if LIO_SANDBOX else "/order-status"
    payload = {"member_code": LIO_MEMBER_CODE}
    if order_id:
        payload["order_id"] = order_id
    if client_ref:
        payload["client_ref"] = client_ref
    return lio_post(ruta, payload, timeout=20)

def lio_nombre_jugador(id_jugador):
    """Devuelve ("ok", nombre), ("no", None) si el ID no existe, o ("na", None) si no se pudo consultar."""
    try:
        resp = lio_post("/username-check", {"member_code": LIO_MEMBER_CODE, "game": LIO_GAME_SLUG, "user_id": id_jugador}, timeout=15)
    except Exception:
        return "na", None
    if not isinstance(resp, dict):
        return "na", None
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    found = resp.get("found", data.get("found"))
    nombre = None
    for fuente in (resp, data):
        for k in ("username", "nickname", "name"):
            if fuente.get(k):
                nombre = str(fuente[k])
                break
        if nombre:
            break
    code = str(resp.get("code", "")).upper()
    if resp.get("ok") and nombre and found is not False:
        return "ok", nombre
    if found is False or "NOT_FOUND" in code:
        return "no", None
    return "na", None

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
        enviar(chat_id, f"Bienvenido Admin\n\n/recargar - Nueva recarga\n/saldo - Saldo tienda\n/reporte - Reportes\n/usuarios - Saldo por local\n/asignar - Asignar saldo a local\n/nuevo - Crear usuario\n\nLioGames (opcion 2):\n/lio - Recarga por LioGames\n/liosaldo - Saldo LioGames\n/lioestado <ref> - Estado de pedido LioGames")
    else:
        enviar(chat_id, f"Bienvenido {usuario}\nTu saldo: ${saldo}\n\n/recargar - Nueva recarga\n/saldo - Ver mi saldo\n/reporte - Mis recargas de hoy")

@app.route("/webhook", methods=["POST"])
def webhook():
    datos = request.json
    if not datos or "message" not in datos:
        return {"status": "ok"}

    chat_id = datos["message"]["chat"]["id"]
    texto = datos["message"].get("text", "").strip()
    message_id = datos["message"].get("message_id")
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

    # Un comando ("/...") en medio de un flujo lo cancela y se ejecuta el comando.
    # Excepto en el login y en la contrasena de LioGames; 'procesando' se respeta.
    if texto.startswith("/"):
        if paso == "lio_password":
            sesiones[chat_id]["paso"] = "menu"
            enviar(chat_id, "Operacion cancelada.")
            menu_principal(chat_id, usuario, "-")
            return {"status": "ok"}
        if paso not in ("menu", "procesando"):
            sesiones[chat_id]["paso"] = "menu"
            paso = "menu"

    if texto == "/saldo":
        if es_admin:
            try:
                resp = requests.get(f"{URL_TIENDA}/saldo", headers={"X-API-Key": API_KEY_TIENDA}, timeout=20).json()
                enviar(chat_id, f"Saldo en tienda: ${resp.get('saldo')}")
            except Exception:
                enviar(chat_id, "No se pudo consultar el saldo de la tienda. Intenta de nuevo.")
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
            sesiones[chat_id]["paso"] = "procesando"
            enviar(chat_id, "Procesando recarga...")
            try:
                resp = requests.post(f"{URL_TIENDA}/comprar",
                    headers={"X-API-Key": API_KEY_TIENDA},
                    json={"producto_id": p["id"], "id_juego": id_jugador},
                    timeout=60
                ).json()
            except Exception:
                enviar(chat_id, "La tienda no respondio. Revisa con /reporte o en la tienda antes de reintentar, la recarga pudo haberse hecho.")
                sesiones[chat_id]["paso"] = "menu"
                return {"status": "ok"}
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

    # ===== LioGames (solo Admin) =====
    lio_activo = bool(es_admin and LIO_PASSWORD)

    if texto == "/lio" and lio_activo:
        sesiones[chat_id]["paso"] = "lio_password"
        enviar(chat_id, "Escribe la contrasena de LioGames:")
        return {"status": "ok"}

    if paso == "lio_password" and lio_activo:
        if hmac.compare_digest(texto.encode(), LIO_PASSWORD.encode()):
            sesiones[chat_id]["lio_ok"] = True
            try:
                if message_id:
                    requests.post(f"{URL_TELEGRAM}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=10)
            except Exception:
                pass
            productos = lio_productos_con_precio()
            sesiones[chat_id]["lio_productos"] = productos
            sesiones[chat_id]["paso"] = "lio_elegir"
            modo = " (SANDBOX)" if LIO_SANDBOX else ""
            enviar(chat_id, f"LioGames{modo}\nElige el monto:", botones([lio_etiqueta(p) for p in productos]))
        else:
            sesiones[chat_id]["paso"] = "menu"
            sesiones[chat_id].pop("lio_ok", None)
            enviar(chat_id, "Contrasena incorrecta. Operacion cancelada.")
            menu_principal(chat_id, usuario, "-")
        return {"status": "ok"}

    if paso == "lio_elegir" and lio_activo:
        productos = sesion.get("lio_productos", [])
        producto = next((p for p in productos if lio_etiqueta(p) == texto), None)
        if not producto:
            enviar(chat_id, "Elige una opcion valida.", botones([lio_etiqueta(p) for p in productos]))
            return {"status": "ok"}
        sesiones[chat_id]["lio_producto"] = producto
        sesiones[chat_id]["paso"] = "lio_pedir_id"
        enviar(chat_id, f"[LIO] {lio_etiqueta(producto)}\n\nEscribe el ID del jugador en Free Fire:")
        return {"status": "ok"}

    if paso == "lio_pedir_id" and lio_activo:
        estado_nombre, nombre_jugador = lio_nombre_jugador(texto)
        if estado_nombre == "no":
            enviar(chat_id, "ID no encontrado. Escribe el ID del jugador de nuevo:")
            return {"status": "ok"}
        linea_nombre = f"Jugador: {nombre_jugador}" if estado_nombre == "ok" else "Nombre: no disponible"
        sesiones[chat_id]["lio_id_jugador"] = texto
        sesiones[chat_id]["lio_nombre"] = nombre_jugador
        sesiones[chat_id]["paso"] = "lio_confirmar"
        p = sesion["lio_producto"]
        enviar(chat_id,
            f"Confirma la recarga LioGames:\n\n"
            f"ID: {texto}\n"
            f"{linea_nombre}\n"
            f"{p['nombre']}\n"
            f"${p['precio']:.2f}\n\n"
            f"Confirmas?",
            botones(["Confirmar", "Cancelar"])
        )
        return {"status": "ok"}

    if paso == "lio_confirmar" and lio_activo:
        if texto != "Confirmar":
            sesiones[chat_id]["paso"] = "menu"
            enviar(chat_id, "Recarga cancelada.")
            return {"status": "ok"}
        sesiones[chat_id]["paso"] = "procesando"
        p = sesion["lio_producto"]
        id_jugador = sesion["lio_id_jugador"]
        client_ref = str(uuid.uuid4())
        enviar(chat_id, "Procesando recarga LioGames...")
        payload = {
            "member_code": LIO_MEMBER_CODE,
            "product_id": LIO_PRODUCT_ID,
            "variation_id": p["variation_id"],
            "user_id": id_jugador,
            "client_ref": client_ref,
        }
        ruta = "/sandbox/order-create" if LIO_SANDBOX else "/order-create"
        try:
            resp = lio_post(ruta, payload, timeout=30)
        except Exception:
            sesiones[chat_id]["paso"] = "menu"
            enviar(chat_id, f"LioGames no respondio. Ref: {client_ref}\nRevisa con /lioestado {client_ref} antes de reintentar.")
            return {"status": "ok"}

        estado, order_id = lio_estado(resp)
        if not resp.get("ok") and estado not in LIO_PENDIENTE:
            sesiones[chat_id]["paso"] = "menu"
            enviar(chat_id, f"Error LioGames: {resp.get('code', '')} {resp.get('message', '')}".strip())
            return {"status": "ok"}

        intentos = 0
        while estado in LIO_PENDIENTE and intentos < 5:
            time.sleep(3)
            intentos += 1
            try:
                r2 = lio_consultar(order_id=order_id, client_ref=client_ref)
                e2, o2 = lio_estado(r2)
                if e2:
                    estado = e2
                order_id = order_id or o2
            except Exception:
                pass

        pedido = order_id or client_ref
        if estado in LIO_EXITO or estado in LIO_PENDIENTE or resp.get("ok"):
            sb_guardar_recarga(usuario, f"[LIO] {p['nombre']}", p["precio"], id_jugador, pedido)
        if estado in LIO_EXITO:
            enviar(chat_id,
                f"Recarga LioGames exitosa!\n\n"
                f"Jugador: {id_jugador}\n"
                f"{p['nombre']}\n"
                f"Pedido #: {pedido}\n"
                f"Operador: {usuario}"
            )
        elif estado in LIO_PENDIENTE:
            enviar(chat_id,
                f"Pedido LioGames en proceso.\n\n"
                f"{p['nombre']} | ID: {id_jugador}\n"
                f"Ref: {client_ref}\n\n"
                f"Consulta luego con:\n/lioestado {client_ref}"
            )
        else:
            enviar(chat_id, f"Pedido LioGames: {estado or 'estado desconocido'}\nRef: {client_ref}\nConsulta con /lioestado {client_ref}")
        sesiones[chat_id]["paso"] = "menu"
        return {"status": "ok"}

    if texto == "/liosaldo" and lio_activo:
        if not sesion.get("lio_ok"):
            enviar(chat_id, "Primero desbloquea LioGames con /lio.")
            return {"status": "ok"}
        try:
            resp = lio_post("/balance", {"member_code": LIO_MEMBER_CODE}, timeout=20)
            data = resp.get("data") or {}
            saldo = data.get("balance", data.get("wallet_balance", data)) if isinstance(data, dict) else data
            if resp.get("ok"):
                enviar(chat_id, f"Saldo LioGames: ${saldo}")
            else:
                enviar(chat_id, f"Error LioGames: {resp.get('code', '')} {resp.get('message', '')}".strip())
        except Exception:
            enviar(chat_id, "No se pudo consultar el saldo de LioGames.")
        return {"status": "ok"}

    if texto.startswith("/lioestado") and lio_activo:
        if not sesion.get("lio_ok"):
            enviar(chat_id, "Primero desbloquea LioGames con /lio.")
            return {"status": "ok"}
        partes = texto.split()
        if len(partes) < 2:
            enviar(chat_id, "Uso: /lioestado <ref>")
            return {"status": "ok"}
        ref = partes[1]
        try:
            # Si es un uuid es nuestro client_ref; si no, el ID de pedido de LioGames
            try:
                uuid.UUID(ref)
                resp = lio_consultar(client_ref=ref)
            except ValueError:
                resp = lio_consultar(order_id=ref)
            estado, order_id = lio_estado(resp)
            enviar(chat_id, f"Pedido LioGames\nRef: {ref}\nPedido #: {order_id or '-'}\nEstado: {estado or resp.get('message', 'desconocido')}")
        except Exception:
            enviar(chat_id, "No se pudo consultar el estado en LioGames.")
        return {"status": "ok"}

    enviar(chat_id, "Usa /recargar, /saldo o /reporte")
    return {"status": "ok"}

@app.route("/")
def index():
    return "Bot activo v6", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
