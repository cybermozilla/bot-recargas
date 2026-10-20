import os
import json
import hmac
import hashlib
import time
import uuid
import re
import threading
from decimal import Decimal, ROUND_HALF_UP
import requests
from flask import Flask, request
from datetime import datetime

TOKEN_BOT = os.environ.get("TOKEN_BOT")
API_KEY_TIENDA = os.environ.get("API_KEY_TIENDA")
URL_TELEGRAM = f"https://api.telegram.org/bot{TOKEN_BOT}"
URL_TIENDA = "https://tiendagiftven.tech/api/v1"
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ===== TCG (Tu Codigo Gamer) = proveedor LioGames (opcion 2) =====
LIO_MEMBER_CODE = os.environ.get("LIO_MEMBER_CODE")
LIO_SECRET = os.environ.get("LIO_SECRET")
LIO_KEY_ID = os.environ.get("LIO_KEY_ID")
LIO_SANDBOX = os.environ.get("LIO_SANDBOX") == "1"
# 1 (por defecto) = solo Admin. 0 = cualquier usuario logueado
LIO_SOLO_ADMIN = os.environ.get("LIO_SOLO_ADMIN", "1") != "0"
URL_LIO = "https://distribution.liogames.com/api/v1"
LIO_PRODUCT_ID = 65871  # Free Fire (LATAM)
LIO_GAME_SLUG = "free-fire-global"  # Username API: no existe slug LATAM
LIO_NAME_SERVER = os.environ.get("LIO_NAME_SERVER", "SAC")  # se envia como server_id (prueba LATAM)
LIO_NAME_CHECK = os.environ.get("LIO_NAME_CHECK", "1") != "0"  # 0 = no consultar el nombre
TCG_PREFIJO = "[TCG] "
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")  # chat de Telegram del Admin para avisos de revision manual
CHECK_TOKEN = os.environ.get("CHECK_TOKEN")      # opcional: protege /check-pendientes
TCG_WATCHER = os.environ.get("TCG_WATCHER", "1") != "0"  # 0 = no iniciar el hilo vigilante
TCG_WATCH_SEGUNDOS = int(os.environ.get("TCG_WATCH_SEGUNDOS", "30"))
TCG_MAX_HORAS = 24

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

# costo = precio GOLD de LioGames (respaldo si falla la consulta en vivo); markup = ganancia de reventa
LIO_PRODUCTOS = [
    {"variation_id": 533711, "nombre": "110 Diamantes",   "costo": 0.67,  "markup": "0.21"},
    {"variation_id": 533713, "nombre": "341 Diamantes",   "costo": 2.01,  "markup": "0.21"},
    {"variation_id": 533715, "nombre": "572 Diamantes",   "costo": 3.40,  "markup": "0.15"},
    {"variation_id": 533717, "nombre": "1166 Diamantes",  "costo": 6.31,  "markup": "0.15"},
    {"variation_id": 533719, "nombre": "2398 Diamantes",  "costo": 12.52, "markup": "0.15"},
    {"variation_id": 533720, "nombre": "6160 Diamantes",  "costo": 31.88, "markup": "0.11"},
    {"variation_id": 533724, "nombre": "Tarjeta Mensual", "costo": 9.69,  "markup": "0.15"},
]

# ===== TCG Roblox (US): tarjetas de regalo en USD (NO Robux). Sin ID de jugador. =====
ROBLOX_PRODUCT_ID = 535408
# costo = GOLD de LioGames (respaldo); markup en % para que el precio siga al costo si Lio lo cambia.
# 75/100/200 USD (535419/535420/535421) y 5 USD (535412) quedan fuera del menu.
ROBLOX_PRODUCTOS = [
    {"variation_id": 535413, "nombre": "Roblox US 10 USD", "costo": 8.95,  "markup": "0.10"},
    {"variation_id": 535414, "nombre": "Roblox US 15 USD", "costo": 14.01, "markup": "0.0635"},
    {"variation_id": 535415, "nombre": "Roblox US 20 USD", "costo": 18.69, "markup": "0.0647"},
    {"variation_id": 535416, "nombre": "Roblox US 25 USD", "costo": 22.25, "markup": "0.10"},
    {"variation_id": 535417, "nombre": "Roblox US 30 USD", "costo": 28.15, "markup": "0.0568"},
    {"variation_id": 535418, "nombre": "Roblox US 50 USD", "costo": 45.48, "markup": "0.0774"},
]
for _p in ROBLOX_PRODUCTOS:
    _p.update(tipo="roblox", product_id=ROBLOX_PRODUCT_ID)

# Boton para volver al menu desde cualquier paso
MENU_BTN = "⬅️ Menu"
MENU_TEXTOS = ("menu", "/menu", "/start", "⬅️ menu", "⬅ menu", "volver", "volver al menu")

def es_menu(texto):
    t = (texto or "").strip().lower()
    return t in MENU_TEXTOS or t.replace("⬅️", "").replace("⬅", "").strip() == "menu"

def precio_reventa(costo, markup):
    valor = Decimal(str(costo)) * (Decimal("1") + Decimal(str(markup)))
    return float(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

# Un candado por usuario para el paso de confirmar/cobrar
_candados = {}
_candados_lock = threading.Lock()

def candado_usuario(nombre):
    with _candados_lock:
        if nombre not in _candados:
            _candados[nombre] = threading.Lock()
        return _candados[nombre]

def lio_firmar(cuerpo_bytes):
    return hmac.new(LIO_SECRET.encode(), cuerpo_bytes, hashlib.sha256).hexdigest()

def lio_post(ruta, payload, timeout=30):
    cuerpo = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "x-liog-sign": lio_firmar(cuerpo)}
    if LIO_KEY_ID:
        headers["X-LIOG-KEY-ID"] = LIO_KEY_ID
    return requests.post(f"{URL_LIO}{ruta}", data=cuerpo, headers=headers, timeout=timeout).json()

def lio_productos_con_precio(lista=None, product_id=None):
    """Precios GOLD en vivo; si falla, usa los precios fijos."""
    lista = LIO_PRODUCTOS if lista is None else lista
    product_id = product_id or LIO_PRODUCT_ID
    productos = [dict(p) for p in lista]
    try:
        r = requests.get(f"{URL_LIO}/products/{product_id}/price-matrix", timeout=10).json()
        precios = {row["variation_id"]: row.get("prices", {}).get("gold") for row in r.get("data", {}).get("rows", [])}
        for p in productos:
            if precios.get(p["variation_id"]):
                p["costo"] = round(float(precios[p["variation_id"]]), 2)
    except Exception:
        pass
    for p in productos:
        p["precio"] = precio_reventa(p["costo"], p["markup"])
    return productos

def roblox_productos_con_precio():
    return lio_productos_con_precio(ROBLOX_PRODUCTOS, ROBLOX_PRODUCT_ID)

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
        for k in ("order_id", "id"):
            v = data.get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                order_id = v
                break
            if isinstance(v, str) and v.strip().isdigit():
                order_id = int(v.strip())
                break
    return estado, order_id

def _a_entero(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None

def lio_numero_panel(resp):
    """Numero de pedido que muestra el panel de LioGames (p. ej. #678632). None si no viene."""
    if not isinstance(resp, dict):
        return None
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    fuentes = [d for d in (data.get("order") if isinstance(data.get("order"), dict) else None, data, resp) if d]
    for f in fuentes:
        for k in ("order_number", "number", "order_no", "wc_order_id", "display_id"):
            n = _a_entero(f.get(k))
            if n is not None:
                return n
    for f in fuentes:
        for k in ("reference", "order_reference", "dh_ref", "ref"):
            v = f.get(k)
            if isinstance(v, str):
                m = re.match(r"^DH-\d{8}-(\d+)$", v.strip(), re.I)
                if m:
                    return int(m.group(1))
    return None

_CLAVES_SECRETAS = ("secret", "sign", "key", "token", "password", "member_code", "authorization")

def _sin_secretos(obj):
    if isinstance(obj, dict):
        return {k: ("***" if any(c in str(k).lower() for c in _CLAVES_SECRETAS) else _sin_secretos(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sin_secretos(v) for v in obj]
    return obj

# ===== Codigo de tarjetas (Roblox): el campo exacto de LioGames aun no se conoce =====
_K_CODIGO = {"code", "codes", "pin", "pins", "pincode", "pinnumber", "voucher", "vouchers", "vouchercode",
             "vouchercodes", "serial", "serials", "serialnumber", "serialno", "sn", "cardcode", "cardcodes",
             "cardnumber", "cardpin", "redeemcode", "redemptioncode", "giftcode", "giftcardcode", "claimcode",
             "licensekey", "licensekeys", "cardkey", "productkey", "activationcode", "codigo", "codigos"}
_K_CONTENEDOR = {"delivery", "deliveries", "deliverydata", "deliverydetails", "deliveryinfo", "delivered",
                 "items", "cards", "giftcard", "giftcards", "voucherdata", "fulfillment", "fulfilment",
                 "result", "results", "lines", "entries"}
_K_NO_CODIGO = {"id", "orderid", "productid", "variationid", "status", "message", "name", "label", "title",
                "type", "currency", "createdat", "updatedat", "date", "expiresat", "expiry", "expiration",
                "product", "productname", "variation", "variationname", "url", "image", "note", "notes", "sku",
                "price", "amount", "total", "quantity", "qty", "clientref", "reference", "ordernumber", "number",
                "userid", "serverid", "membercode", "region", "country", "description", "instructions"}
_RE_CODIGO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\- ]{2,62})[A-Za-z0-9]$")
_RE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}")
_RE_GRUPOS = re.compile(r"^[A-Z0-9]{3,}(?:[- ][A-Z0-9]{3,})+$")
_RE_ETIQUETA = re.compile(r"(?i)\b(c[oó]digo|code|pin|serial|s/?n|voucher|card(?:\s*number)?)\s*(?:no\.?|number|#)?\s*[:=#]\s*([A-Za-z0-9][A-Za-z0-9\-]{3,62}[A-Za-z0-9])")

def _norm_clave(k):
    return re.sub(r"[^a-z0-9]", "", str(k).lower())

def _clave_no_codigo(k):
    """Campos que nunca son el codigo (ids, referencias, fechas...)."""
    if k in _K_CODIGO:
        return False
    return (k in _K_NO_CODIGO or k.endswith("id") or k.endswith("ids") or "ref" in k
            or "date" in k or "time" in k or k.endswith("at"))

def parece_codigo(v):
    """True si el valor parece un codigo de tarjeta (no un estado, fecha, uuid o id corto)."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v >= 100000
    if not isinstance(v, str):
        return False
    v = v.strip()
    if len(v) < 6 or len(v) > 64 or not _RE_CODIGO.match(v) or "  " in v:
        return False
    if _RE_UUID.match(v) or _RE_FECHA.match(v) or re.match(r"^DH-\d{8}-\d+$", v, re.I):
        return False
    return bool(re.search(r"\d", v)) or bool(_RE_GRUPOS.match(v))

def _etiqueta_codigo(clave):
    k = _norm_clave(clave)
    if k.startswith("pin") or k == "cardpin":
        return "PIN"
    if k.startswith("serial") or k == "sn":
        return "Serial"
    return "Codigo"

def _codigos_de_texto(texto, clave):
    hallados = []
    for m in _RE_ETIQUETA.finditer(texto):
        lab = m.group(1).lower()
        etiqueta = "PIN" if lab == "pin" else ("Serial" if lab.startswith("serial") or lab.replace("/", "") == "sn" else _etiqueta_codigo(clave))
        if parece_codigo(m.group(2)):
            hallados.append((etiqueta, m.group(2)))
    if not hallados and parece_codigo(texto):
        hallados.append((_etiqueta_codigo(clave), texto.strip()))
    return hallados

def extraer_codigos(resp, excluir=()):
    """Busca de forma recursiva los codigos/PIN/serial en la respuesta de LioGames.
    Devuelve [(etiqueta, valor, ruta)] sin repetidos."""
    excluir = {str(x) for x in excluir if x is not None}
    hallados = []

    def agregar(etiqueta, valor, ruta):
        valor = str(valor).strip()
        if valor in excluir or any(valor == h[1] for h in hallados):
            return
        hallados.append((etiqueta, valor, ruta))

    def visitar(obj, ruta, clave, en_contenedor, raiz):
        k = _norm_clave(clave) if clave is not None else ""
        if isinstance(obj, dict):
            for ck, cv in obj.items():
                if raiz and ck in ("code", "message", "ok"):
                    continue  # code de la raiz = codigo de estado de la API
                nk = _norm_clave(ck)
                visitar(cv, f"{ruta}.{ck}" if ruta else str(ck), ck,
                        en_contenedor or nk in _K_CONTENEDOR or nk in _K_CODIGO, False)
        elif isinstance(obj, list):
            for i, cv in enumerate(obj):
                visitar(cv, f"{ruta}[{i}]", clave, en_contenedor or k in _K_CONTENEDOR or k in _K_CODIGO, False)
        elif _clave_no_codigo(k):
            return
        elif k in _K_CODIGO or k in _K_CONTENEDOR or en_contenedor:
            if isinstance(obj, str):
                for etiqueta, valor in _codigos_de_texto(obj, clave):
                    agregar(etiqueta, valor, ruta)
            elif parece_codigo(obj) and k in _K_CODIGO:
                agregar(_etiqueta_codigo(clave), obj, ruta)

    try:
        visitar(resp, "", None, False, True)
    except Exception:
        pass
    return hallados

def _ocultar_codigos(obj, clave=None, en_contenedor=False):
    """Para los logs: deja ver el campo pero no el codigo completo (quien lo vea lo podria canjear)."""
    k = _norm_clave(clave) if clave is not None else ""
    if isinstance(obj, dict):
        return {ck: _ocultar_codigos(cv, ck, en_contenedor or _norm_clave(ck) in _K_CONTENEDOR or _norm_clave(ck) in _K_CODIGO)
                for ck, cv in obj.items()}
    if isinstance(obj, list):
        return [_ocultar_codigos(cv, clave, en_contenedor) for cv in obj]
    if _clave_no_codigo(k) or not (k in _K_CODIGO or en_contenedor):
        return obj
    if isinstance(obj, str) and (parece_codigo(obj) or _RE_ETIQUETA.search(obj)):
        return f"{obj.strip()[:3]}***({len(obj.strip())})"
    if isinstance(obj, int) and parece_codigo(obj):
        return f"{str(obj)[:3]}***({len(str(obj))})"
    return obj

def lio_log(etiqueta, resp):
    """Debug: imprime la respuesta completa en los logs de Render, sin secretos ni codigos completos."""
    try:
        print(f"[TCG DEBUG] {etiqueta}: {json.dumps(_ocultar_codigos(_sin_secretos(resp)), ensure_ascii=False)}", flush=True)
    except Exception:
        pass

def _texto_codigos(codigos):
    return "\n".join(f"{e}: {v}" for e, v, _ in codigos)

LIO_EXITO = ("COMPLETED", "COMPLETE", "SUCCESS", "SUCCESSFUL", "DELIVERED", "DONE")
LIO_PENDIENTE = ("PROCESSING", "PENDING", "ON-HOLD", "ON_HOLD", "QUEUED", "IN_PROGRESS")

def lio_consultar(order_id=None, client_ref=None):
    ruta = "/sandbox/order-status" if LIO_SANDBOX else "/order-status"
    payload = {"member_code": LIO_MEMBER_CODE}
    if order_id:
        payload["order_id"] = order_id
    if client_ref:
        payload["client_ref"] = client_ref
    resp = lio_post(ruta, payload, timeout=20)
    lio_log("order-status", resp)
    return resp

def lio_nombre_jugador(id_jugador):
    """Nombre solo informativo. Devuelve el nombre, o None si no hay / no se pudo consultar."""
    if not LIO_NAME_CHECK:
        return None
    payload = {"member_code": LIO_MEMBER_CODE, "game": LIO_GAME_SLUG, "user_id": id_jugador}
    if LIO_NAME_SERVER:
        payload["server_id"] = LIO_NAME_SERVER
    try:
        resp = lio_post("/username-check", payload, timeout=15)
    except Exception:
        return None
    if not isinstance(resp, dict) or not resp.get("ok"):
        return None
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    if resp.get("found", data.get("found")) is False:
        return None
    for fuente in (resp, data):
        for k in ("username", "nickname", "name"):
            if fuente.get(k):
                return str(fuente[k])
    return None

def sb_get_usuario(nombre):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/usuarios?nombre=eq.{nombre}&select=*",
        headers=HEADERS_SB
    )
    data = r.json()
    return data[0] if data else None

def sb_rpc(funcion, nombre, monto):
    """Llama la funcion SQL. Devuelve (True, valor) o (False, None) si la funcion no existe (404)."""
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/{funcion}",
        headers=HEADERS_SB,
        json={"p_nombre": nombre, "p_monto": monto},
        timeout=15
    )
    if r.status_code == 404:
        return False, None
    r.raise_for_status()
    valor = r.json()
    if isinstance(valor, list):
        valor = valor[0] if valor else None
    if isinstance(valor, dict):
        valor = next(iter(valor.values()), None)
    return True, (float(valor) if valor is not None else None)

def sb_descontar_saldo(nombre, monto):
    """Descuenta de forma atomica. Devuelve el nuevo saldo, o None si no alcanzaba."""
    existe, nuevo = sb_rpc("descontar_saldo", nombre, monto)
    if existe:
        return nuevo
    # Respaldo (antes de ejecutar supabase_rpc.sql): leer y luego actualizar
    u = sb_get_usuario(nombre)
    if float(u["saldo"]) < monto:
        return None
    nuevo = float(u["saldo"]) - monto
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/usuarios?nombre=eq.{nombre}",
        headers=HEADERS_SB,
        json={"saldo": nuevo}
    )
    return nuevo

def sb_recargar_saldo(nombre, monto):
    existe, nuevo = sb_rpc("sumar_saldo", nombre, monto)
    if existe:
        return nuevo
    u = sb_get_usuario(nombre)
    nuevo = float(u["saldo"]) + monto
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/usuarios?nombre=eq.{nombre}",
        headers=HEADERS_SB,
        json={"saldo": nuevo}
    )
    return nuevo
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

def teclado_menu():
    """Teclado solo con el boton de menu (para pasos donde se escribe: ID, monto, nombre...)."""
    return {"keyboard": [[{"text": MENU_BTN}]], "resize_keyboard": True, "one_time_keyboard": True}

def botones(opciones, menu=True):
    filas = []
    fila = []
    for op in opciones:
        fila.append({"text": op})
        if len(fila) == 2:
            filas.append(fila)
            fila = []
    if fila:
        filas.append(fila)
    if menu:
        filas.append([{"text": MENU_BTN}])
    return {"keyboard": filas, "resize_keyboard": True, "one_time_keyboard": True}

QUITAR_TECLADO = {"remove_keyboard": True}

def menu_principal(chat_id, usuario, saldo, es_admin=False):
    if usuario == "Admin" or es_admin:
        enviar(chat_id,
            f"Bienvenido {usuario}\n\n"
            f"/recargar - Nueva recarga\n/saldo - Saldo tienda\n/reporte - Reportes\n/usuarios - Saldo por local\n"
            f"/asignar - Asignar saldo a local\n/nuevo - Crear usuario\n\n"
            f"TCG (opcion 2):\n/tcg - Recarga TCG Free Fire\n/tcgroblox - Tarjeta Roblox USD TCG\n"
            f"/tcgsaldo - Saldo TCG\n/tcgestado <pedido> - Estado de pedido TCG\n\n"
            f"/menu - Volver a este menu\n/salir - Cerrar sesion", QUITAR_TECLADO)
    else:
        extra = ("\n/tcg - Recarga TCG Free Fire\n/tcgroblox - Tarjeta Roblox USD TCG\n/tcgestado <pedido> - Estado de pedido TCG"
                 if not LIO_SOLO_ADMIN else "")
        enviar(chat_id,
            f"Bienvenido {usuario}\nTu saldo: ${saldo}\n\n/recargar - Nueva recarga\n/saldo - Ver mi saldo\n"
            f"/reporte - Mis recargas de hoy{extra}\n\n/menu - Volver a este menu\n/salir - Cerrar sesion", QUITAR_TECLADO)

def volver_menu(chat_id, sesion):
    """Boton Menu / /menu / /start: deja la sesion en el menu (sin cerrar sesion) y muestra el menu segun el rol.
    Si hay un pedido en curso ('procesando') no se toca: el pedido sigue y avisa al terminar."""
    usuario, es_admin = sesion.get("usuario", ""), sesion.get("es_admin", False)
    if sesion.get("paso") == "procesando":
        enviar(chat_id, "Tu pedido sigue en proceso, te aviso por aqui cuando termine.")
    else:
        sesiones[chat_id] = {"paso": "menu", "usuario": usuario, "es_admin": es_admin}
    saldo = "-"
    try:
        u = sb_get_usuario(usuario)
        if u and u.get("saldo") is not None:
            saldo = u["saldo"]
    except Exception:
        pass
    menu_principal(chat_id, usuario, saldo, es_admin)
    return {"status": "ok"}

@app.route("/webhook", methods=["POST"])
def webhook():
    datos = request.json
    if not datos or "message" not in datos:
        return {"status": "ok"}

    chat_id = datos["message"]["chat"]["id"]
    texto = datos["message"].get("text", "").strip()
    message_id = datos["message"].get("message_id")
    sesion = sesiones.get(chat_id, {})

    if texto == "/salir":
        sesiones[chat_id] = {"paso": "login_nombre"}
        enviar(chat_id, "Sesion cerrada.\nEscribe tu nombre de usuario:", QUITAR_TECLADO)
        return {"status": "ok"}

    if sesion.get("usuario") and es_menu(texto):
        return volver_menu(chat_id, sesion)

    if texto == "/start" or (es_menu(texto) and sesion.get("paso") in ("login_nombre", "login_password")):
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
            menu_principal(chat_id, u["nombre"], u["saldo"], u.get("es_admin"))
        else:
            enviar(chat_id, "Usuario o contrasena incorrectos. Escribe /start para intentar de nuevo.")
            sesiones.pop(chat_id, None)
        return {"status": "ok"}

    # Un comando ("/...") en medio de un flujo lo cancela y se ejecuta el comando.
    # Excepto en el login; 'procesando' se respeta.
    if texto.startswith("/"):
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
        enviar(chat_id, "Escribe el nombre del nuevo usuario:", teclado_menu())
        return {"status": "ok"}

    if paso == "nuevo_nombre":
        nombre_nuevo = texto
        u = sb_get_usuario(nombre_nuevo)
        if u:
            enviar(chat_id, f"Ya existe un usuario con ese nombre. Escribe otro:", teclado_menu())
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
            botones(["ok"])
        )
        return {"status": "ok"}

    if paso == "nuevo_password":
        texto_limpio = texto.strip().lower().replace("👍", "ok").replace("✅", "ok")
        if texto_limpio == "ok":
            pwd_final = sesiones[chat_id]["pwd_sugerida"]
        elif len(texto) < 4:
            enviar(chat_id, "La contrasena debe tener al menos 4 caracteres. Intenta de nuevo o escribe 'ok' para usar la sugerida:", teclado_menu())
            return {"status": "ok"}
        else:
            import re
            if not re.match(r'^[a-zA-Z0-9]+$', texto):
                enviar(chat_id, "Solo letras y numeros permitidos. Intenta de nuevo o escribe 'ok' para usar la sugerida:", teclado_menu())
                return {"status": "ok"}
            pwd_final = texto
        
        nombre_nuevo = sesiones[chat_id]["nuevo_nombre"]
        sesiones[chat_id]["paso"] = "nuevo_saldo"
        sesiones[chat_id]["nuevo_password"] = pwd_final
        enviar(chat_id, f"Cuanto saldo inicial para {nombre_nuevo}? (escribe 0 si ninguno)", teclado_menu())
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
            enviar(chat_id, "Escribe un numero valido.", teclado_menu())
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
            enviar(chat_id, f"Cuanto saldo asignar a {texto}?", teclado_menu())
        else:
            enviar(chat_id, "Local no valido.", teclado_menu())
        return {"status": "ok"}

    if paso == "asignar_monto":
        try:
            monto = float(texto)
            local = sesion["asignar_a"]
            sb_recargar_saldo(local, monto)
            sesiones[chat_id]["paso"] = "menu"
            enviar(chat_id, f"Se asignaron ${monto} a {local}.")
        except:
            enviar(chat_id, "Escribe un numero valido.", teclado_menu())
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
        enviar(chat_id, f"{producto['nombre']} ${producto['precio']}\n\nEscribe el ID del jugador en Free Fire:", teclado_menu())
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
            with candado_usuario(usuario):
                return confirmar_tienda(chat_id, usuario, es_admin, p, id_jugador)
        else:
            enviar(chat_id, "Recarga cancelada.")
        sesiones[chat_id]["paso"] = "menu"
        return {"status": "ok"}

    return webhook_lio(chat_id, texto, sesion, paso, usuario, es_admin, message_id)


def confirmar_tienda(chat_id, usuario, es_admin, p, id_jugador):
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
    sesiones[chat_id]["paso"] = "menu"
    return {"status": "ok"}


def lio_cobra_saldo(usuario, es_admin):
    """Revendedores siempre pagan. El Admin solo si tiene un valor de saldo en su fila."""
    if not es_admin:
        return True
    u = sb_get_usuario(usuario)
    return bool(u) and u.get("saldo") is not None


TCG_CMD = ("/tcg", "/lio")
TCG_ROBLOX = ("/tcgroblox", "/roblox", "/lioroblox")
TCG_SALDO = ("/tcgsaldo", "/liosaldo")
TCG_ESTADO = ("/tcgestado", "/lioestado")
refs_cortos = {}  # ref corta (8) -> client_ref completo, para /tcgestado
panel_a_interno = {}  # numero del panel (#678632) -> id interno de la API (543453)


def webhook_lio(chat_id, texto, sesion, paso, usuario, es_admin, message_id):
    # ===== TCG (LioGames) =====
    lio_activo = bool(es_admin or not LIO_SOLO_ADMIN)

    modo = " (SANDBOX)" if LIO_SANDBOX else ""
    if texto in TCG_CMD and lio_activo:
        productos = lio_productos_con_precio()
        sesiones[chat_id]["lio_productos"] = productos
        sesiones[chat_id]["paso"] = "lio_elegir"
        enviar(chat_id, f"TCG{modo}\nElige el monto:", botones([lio_etiqueta(p) for p in productos]))
        return {"status": "ok"}

    if texto in TCG_ROBLOX and lio_activo:
        productos = roblox_productos_con_precio()
        sesiones[chat_id]["rbx_productos"] = productos
        sesiones[chat_id]["paso"] = "rbx_elegir"
        enviar(chat_id, f"TCG{modo} - Roblox (US) tarjeta de regalo en USD\nElige la tarjeta:", botones([lio_etiqueta(p) for p in productos]))
        return {"status": "ok"}

    if paso == "rbx_elegir" and lio_activo:
        productos = sesion.get("rbx_productos", [])
        producto = next((p for p in productos if lio_etiqueta(p) == texto), None)
        if not producto:
            enviar(chat_id, "Elige una opcion valida.", botones([lio_etiqueta(p) for p in productos]))
            return {"status": "ok"}
        saldo_txt = "-"
        if lio_cobra_saldo(usuario, es_admin):
            u = sb_get_usuario(usuario)
            if float(u["saldo"]) <= 0 or producto["precio"] > float(u["saldo"]):
                enviar(chat_id, f"Saldo insuficiente. Tu saldo: ${u['saldo']}")
                sesiones[chat_id]["paso"] = "menu"
                return {"status": "ok"}
            saldo_txt = u["saldo"]
        sesiones[chat_id]["lio_producto"] = producto
        sesiones[chat_id]["lio_id_jugador"] = "-"
        sesiones[chat_id]["lio_nombre"] = None
        sesiones[chat_id]["paso"] = "lio_confirmar"
        enviar(chat_id,
            f"Confirma la compra TCG:\n\n"
            f"{producto['nombre']} (tarjeta de regalo)\n"
            f"Precio: ${producto['precio']:.2f}\n"
            f"Tu saldo: ${saldo_txt}\n\n"
            f"Confirmas?",
            botones(["Confirmar", "Cancelar"])
        )
        return {"status": "ok"}

    if paso == "lio_elegir" and lio_activo:
        productos = sesion.get("lio_productos", [])
        producto = next((p for p in productos if lio_etiqueta(p) == texto), None)
        if not producto:
            enviar(chat_id, "Elige una opcion valida.", botones([lio_etiqueta(p) for p in productos]))
            return {"status": "ok"}
        if lio_cobra_saldo(usuario, es_admin):
            u = sb_get_usuario(usuario)
            if float(u["saldo"]) <= 0 or producto["precio"] > float(u["saldo"]):
                enviar(chat_id, f"Saldo insuficiente. Tu saldo: ${u['saldo']}")
                sesiones[chat_id]["paso"] = "menu"
                return {"status": "ok"}
        sesiones[chat_id]["lio_producto"] = producto
        sesiones[chat_id]["paso"] = "lio_pedir_id"
        enviar(chat_id, f"{TCG_PREFIJO}{lio_etiqueta(producto)}\n\nEscribe el ID del jugador en Free Fire:", teclado_menu())
        return {"status": "ok"}

    if paso == "lio_pedir_id" and lio_activo:
        nombre_jugador = lio_nombre_jugador(texto)
        linea_nombre = f"Jugador (verificar): {nombre_jugador}" if nombre_jugador else "Nombre: no disponible"
        sesiones[chat_id]["lio_id_jugador"] = texto
        sesiones[chat_id]["lio_nombre"] = nombre_jugador
        sesiones[chat_id]["paso"] = "lio_confirmar"
        p = sesion["lio_producto"]
        enviar(chat_id,
            f"Confirma la recarga TCG:\n\n"
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
        with candado_usuario(usuario):
            return confirmar_lio(chat_id, usuario, es_admin, sesion)

    if paso == "tcg_estado_pedir" and lio_activo:
        sesiones[chat_id]["paso"] = "menu"
        return tcg_estado(chat_id, texto.strip())

    return comandos_lio(chat_id, texto, sesion, usuario, es_admin, lio_activo)


LIO_FALLO = ("FAILED", "FAIL", "CANCELLED", "CANCELED", "REFUNDED", "REJECTED", "ERROR")

def es_roblox(p):
    return p.get("tipo") == "roblox" or str(p.get("producto") or p.get("nombre") or "").startswith("Roblox")

def _linea_producto(nombre, id_jugador, roblox):
    return nombre if roblox else f"{nombre} | ID: {id_jugador}"

def _sin_codigo(chat_id, usuario, nombre, pedido):
    """Completado pero sin codigo en la respuesta: el codigo esta en el panel de LioGames."""
    if ADMIN_CHAT_ID and str(ADMIN_CHAT_ID) != str(chat_id):
        _avisar_admin(f"Revisar: pedido TCG #{pedido} ({nombre}) de {usuario} completado pero el codigo no llego por la API. "
                      f"Buscalo en el panel de LioGames y enviaselo.")

def confirmar_lio(chat_id, usuario, es_admin, sesion):
    p = sesion["lio_producto"]
    roblox = es_roblox(p)
    id_jugador = "-" if roblox else sesion["lio_id_jugador"]
    cobra = lio_cobra_saldo(usuario, es_admin)
    # Cobro por adelantado (atomico): si no alcanza, no se hace el pedido
    if cobra:
        u = sb_get_usuario(usuario)
        if float(u["saldo"]) <= 0 or p["precio"] > float(u["saldo"]):
            enviar(chat_id, f"Saldo insuficiente. Tu saldo: ${u['saldo']}")
            sesiones[chat_id]["paso"] = "menu"
            return {"status": "ok"}
        try:
            nuevo = sb_descontar_saldo(usuario, p["precio"])
        except Exception:
            nuevo = None
        if nuevo is None:
            enviar(chat_id, "Saldo insuficiente o no se pudo cobrar. Recarga cancelada.")
            sesiones[chat_id]["paso"] = "menu"
            return {"status": "ok"}

    def devolver():
        if cobra:
            try:
                sb_recargar_saldo(usuario, p["precio"])
            except Exception:
                pass

    def saldo_restante():
        if not cobra:
            return "-"
        try:
            return sb_get_usuario(usuario)["saldo"]
        except Exception:
            return "?"

    client_ref = str(uuid.uuid4())
    ref_corta = client_ref[:8]
    refs_cortos[ref_corta] = client_ref
    enviar(chat_id, "Procesando compra TCG..." if roblox else "Procesando recarga TCG...")
    payload = {
        "member_code": LIO_MEMBER_CODE,
        "product_id": p.get("product_id", LIO_PRODUCT_ID),
        "variation_id": p["variation_id"],
    }
    if not roblox:
        payload["user_id"] = id_jugador  # tarjetas (perfil no_input): sin user_id
    payload["client_ref"] = client_ref
    tipo = "roblox" if roblox else "ff"
    respuestas = []
    ruta = "/sandbox/order-create" if LIO_SANDBOX else "/order-create"
    try:
        resp = lio_post(ruta, payload, timeout=30)
        lio_log("order-create", resp)
    except Exception:
        # No sabemos si el pedido entro: el cobro se mantiene y se registra para revisar
        sb_guardar_recarga(usuario, f"{TCG_PREFIJO}{p['nombre']} (sin confirmar)", p["precio"], id_jugador, ref_corta)
        vigilado = sb_pend_crear(chat_id, usuario, None, None, client_ref, ref_corta, p, cobra, id_jugador, tipo)
        sesiones[chat_id]["paso"] = "menu"
        aviso = "\nTe aviso por aqui cuando se confirme." if vigilado else ""
        enviar(chat_id, f"TCG no respondio. Ref: {ref_corta}\nRevisa con /tcgestado {ref_corta} antes de reintentar.\nTu saldo restante: ${saldo_restante()}{aviso}")
        return {"status": "ok"}

    respuestas.append(resp)
    estado, order_id = lio_estado(resp)
    panel = lio_numero_panel(resp)
    if not resp.get("ok") and estado not in LIO_PENDIENTE:
        devolver()
        sesiones[chat_id]["paso"] = "menu"
        enviar(chat_id, f"Error TCG: {resp.get('code', '')} {resp.get('message', '')}".strip() + f"\nNo se cobro. Tu saldo restante: ${saldo_restante()}")
        return {"status": "ok"}

    intentos = 0
    while estado in LIO_PENDIENTE and intentos < 5:
        time.sleep(3)
        intentos += 1
        try:
            r2 = lio_consultar(order_id=order_id, client_ref=client_ref)
            respuestas.append(r2)
            e2, o2 = lio_estado(r2)
            if e2:
                estado = e2
            order_id = order_id or o2
            panel = panel or lio_numero_panel(r2)
        except Exception:
            pass

    if panel is None:
        # Ultimo intento: buscar el numero del panel por client_ref
        try:
            r3 = lio_consultar(client_ref=client_ref)
            respuestas.append(r3)
            panel = lio_numero_panel(r3)
            if order_id is None:
                order_id = lio_estado(r3)[1]
        except Exception:
            pass

    if panel is not None and order_id is not None:
        panel_a_interno[panel] = order_id
    sesiones[chat_id]["tcg_ultimo"] = {"panel": panel, "interno": order_id, "client_ref": client_ref}
    pedido = panel if panel is not None else (order_id if order_id is not None else ref_corta)
    if estado in LIO_FALLO:
        devolver()
        enviar(chat_id, f"Pedido TCG #{pedido} fallido ({estado}). No se cobro.\nTu saldo restante: ${saldo_restante()}")
        sesiones[chat_id]["paso"] = "menu"
        return {"status": "ok"}
    sb_guardar_recarga(usuario, f"{TCG_PREFIJO}{p['nombre']}", p["precio"], id_jugador, pedido)
    nombre_jug = sesion.get("lio_nombre") or id_jugador
    if roblox and estado in LIO_EXITO:
        excluir = (client_ref, order_id, panel)
        codigos = [c for r in respuestas for c in extraer_codigos(r, excluir)]
        if not codigos:
            # La entrega (codigo / S/N) puede venir solo en order-status
            try:
                r4 = lio_consultar(order_id=order_id, client_ref=client_ref) if order_id else lio_consultar(client_ref=client_ref)
                codigos = extraer_codigos(r4, excluir)
            except Exception:
                pass
        codigos = list({c[1]: c for c in codigos}.values())
        if codigos:
            print(f"[TCG DEBUG] codigo encontrado en: {', '.join(c[2] for c in codigos)}", flush=True)
            enviar(chat_id,
                f"Compra TCG exitosa!\n\n"
                f"{p['nombre']}\n"
                f"{_texto_codigos(codigos)}\n"
                f"Pedido #: {pedido}\n"
                f"Tu saldo restante: ${saldo_restante()}\n"
                f"Operador: {usuario}"
            )
        else:
            print(f"[TCG DEBUG] pedido {pedido} completado sin codigo en la respuesta", flush=True)
            enviar(chat_id,
                f"Compra TCG completada, pero el codigo no llego por la API.\n\n"
                f"{p['nombre']}\n"
                f"Pedido #: {pedido}\n"
                f"Revisa el codigo en el panel de LioGames (pedido #{pedido}) o con /tcgestado {pedido}\n"
                f"Tu saldo restante: ${saldo_restante()}\n"
                f"Operador: {usuario}"
            )
            _sin_codigo(chat_id, usuario, p["nombre"], pedido)
    elif estado in LIO_EXITO:
        enviar(chat_id,
            f"Recarga TCG exitosa!\n\n"
            f"Jugador: {nombre_jug}\n"
            f"{p['nombre']}\n"
            f"Pedido #: {pedido}\n"
            f"Tu saldo restante: ${saldo_restante()}\n"
            f"Operador: {usuario}"
        )
    elif estado in LIO_PENDIENTE:
        vigilado = sb_pend_crear(chat_id, usuario, order_id, panel, client_ref, pedido, p, cobra, id_jugador, tipo)
        if roblox:
            aviso = "\nTe aviso y te envio el codigo por aqui cuando termine." if vigilado else ""
        else:
            aviso = "\nTe aviso por aqui cuando termine." if vigilado else ""
        enviar(chat_id,
            f"Pedido TCG en proceso.\n\n"
            f"{_linea_producto(p['nombre'], id_jugador, roblox)}\n"
            f"Pedido #{pedido}\n"
            f"Tu saldo restante: ${saldo_restante()}\n\n"
            f"Consulta luego con:\n/tcgestado {pedido}{aviso}"
        )
    else:
        vigilado = sb_pend_crear(chat_id, usuario, order_id, panel, client_ref, pedido, p, cobra, id_jugador, tipo)
        aviso = "\nTe aviso por aqui cuando termine." if vigilado else ""
        enviar(chat_id, f"Pedido TCG #{pedido}: {estado or 'estado desconocido'}\nTu saldo restante: ${saldo_restante()}\nConsulta con /tcgestado {pedido}{aviso}")
    sesiones[chat_id]["paso"] = "menu"
    return {"status": "ok"}


def comandos_lio(chat_id, texto, sesion, usuario, es_admin, lio_activo):
    if texto in TCG_SALDO and es_admin:
        try:
            resp = lio_post("/balance", {"member_code": LIO_MEMBER_CODE}, timeout=20)
            data = resp.get("data") or {}
            saldo = data.get("balance", data.get("wallet_balance", data)) if isinstance(data, dict) else data
            if resp.get("ok"):
                enviar(chat_id, f"Saldo TCG: ${saldo}")
            else:
                enviar(chat_id, f"Error TCG: {resp.get('code', '')} {resp.get('message', '')}".strip())
        except Exception:
            enviar(chat_id, "No se pudo consultar el saldo de TCG.")
        return {"status": "ok"}

    partes = texto.split()
    if partes and partes[0] in TCG_ESTADO and lio_activo:
        if len(partes) < 2:
            sesiones[chat_id]["paso"] = "tcg_estado_pedir"
            enviar(chat_id, "Escribe el numero de pedido TCG:", teclado_menu())
            return {"status": "ok"}
        return tcg_estado(chat_id, partes[1])

    enviar(chat_id, "Usa /recargar, /saldo o /reporte")
    return {"status": "ok"}


def _estado_valido(resp):
    estado, _ = lio_estado(resp)
    return bool(resp.get("ok")) and estado not in ("", "NOT_FOUND", "ORDER_NOT_FOUND")

def _es_respuesta_roblox(resp):
    try:
        t = json.dumps(resp).lower()
    except Exception:
        return False
    return "roblox" in t or str(ROBLOX_PRODUCT_ID) in t

def tcg_estado(chat_id, ref):
    ref = ref.lstrip("#")
    try:
        if ref.isdigit() and ref not in refs_cortos:
            n = int(ref)
            resp = lio_consultar(order_id=n)
            if not _estado_valido(resp) and n in panel_a_interno:
                resp = lio_consultar(order_id=panel_a_interno[n])
            if not _estado_valido(resp):
                enviar(chat_id, f"Pedido TCG #{ref} no encontrado.")
                return {"status": "ok"}
        else:
            completo = ref if len(ref) == 36 else refs_cortos.get(ref) or next((v for k, v in refs_cortos.items() if v.startswith(ref)), None)
            if not completo:
                enviar(chat_id, f"Pedido {ref} no encontrado.")
                return {"status": "ok"}
            resp = lio_consultar(client_ref=completo)
        estado, order_id = lio_estado(resp)
        panel = lio_numero_panel(resp) or next((p for p, i in panel_a_interno.items() if i == order_id), None)
        texto_estado = f"Pedido TCG #{panel or order_id or ref}\nEstado: {estado or resp.get('message', 'desconocido')}"
        if estado in LIO_EXITO and (_es_respuesta_roblox(resp) or str(LIO_PRODUCT_ID) not in json.dumps(resp)):
            codigos = extraer_codigos(resp, (order_id, panel))
            if codigos:
                texto_estado += "\n" + _texto_codigos(codigos)
        enviar(chat_id, texto_estado)
    except Exception:
        enviar(chat_id, "No se pudo consultar el estado en TCG.")
    return {"status": "ok"}

# ===== Vigilante de pedidos TCG pendientes (persistido en Supabase) =====
URL_PEND = f"{SUPABASE_URL}/rest/v1/pendientes_tcg"

def ahora_utc():
    from datetime import timezone
    return datetime.now(timezone.utc)

def _sb_tabla_falta(r):
    if r.status_code == 404:
        return True
    try:
        cuerpo = r.json()
        return isinstance(cuerpo, dict) and str(cuerpo.get("code", "")) in ("PGRST205", "PGRST204", "42P01", "PGRST202")
    except Exception:
        return False

def _falta_columna_tipo(r):
    try:
        cuerpo = r.json()
    except Exception:
        cuerpo = None
    texto = (json.dumps(cuerpo) if cuerpo is not None else str(getattr(r, "text", ""))).lower()
    return r.status_code in (400, 404) and ("pgrst204" in texto or "tipo" in texto or "42703" in texto)

def sb_pend_crear(chat_id, usuario, internal_id, panel, client_ref, pedido_ref, p, cobrado, id_jugador, tipo="ff"):
    """Guarda el pedido pendiente. Devuelve True si quedo vigilado; False si la tabla no existe o falla."""
    fila = {
        "chat_id": chat_id, "usuario": usuario,
        "internal_order_id": internal_id, "panel_id": panel,
        "client_ref": client_ref, "pedido_ref": str(pedido_ref),
        "producto": p["nombre"], "monto": p["precio"], "cobrado": bool(cobrado),
        "id_jugador": id_jugador, "estado": "pendiente", "intentos": 0,
    }
    if tipo and tipo != "ff":
        fila["tipo"] = tipo  # columna opcional; si no existe, el tipo se deduce del nombre del producto
    try:
        r = requests.post(URL_PEND, headers=dict(HEADERS_SB, Prefer="return=minimal"), json=fila, timeout=15)
        if r.status_code >= 300 and "tipo" in fila and _falta_columna_tipo(r):
            print("[TCG WATCH] falta la columna pendientes_tcg.tipo (ejecuta supabase_rpc.sql); guardando sin ella", flush=True)
            fila.pop("tipo")
            r = requests.post(URL_PEND, headers=dict(HEADERS_SB, Prefer="return=minimal"), json=fila, timeout=15)
        if r.status_code >= 300:
            print(f"[TCG WATCH] no se pudo guardar pendiente ({r.status_code}): {getattr(r, "text", "")[:300]}", flush=True)
            return False
        return True
    except Exception as e:
        print(f"[TCG WATCH] error guardando pendiente: {e}", flush=True)
        return False

def sb_pend_liberar_trabados():
    """Si un worker murio a mitad de revision, la fila vuelve a 'pendiente' tras 5 minutos."""
    from datetime import timedelta
    limite = (ahora_utc() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        requests.patch(f"{URL_PEND}?estado=eq.revisando&revisado=lt.{limite}",
                       headers=HEADERS_SB, json={"estado": "pendiente"}, timeout=15)
    except Exception:
        pass

def sb_pend_listar():
    sb_pend_liberar_trabados()
    try:
        r = requests.get(f"{URL_PEND}?estado=eq.pendiente&select=*&order=creado.asc&limit=50", headers=HEADERS_SB, timeout=15)
        if r.status_code >= 300:
            print(f"[TCG WATCH] tabla pendientes_tcg no disponible ({r.status_code}). Ejecuta supabase_rpc.sql", flush=True)
            return []
        filas = r.json()
        return filas if isinstance(filas, list) else []
    except Exception as e:
        print(f"[TCG WATCH] error listando pendientes: {e}", flush=True)
        return []

def sb_pend_cambiar(fila_id, de_estado, cambios):
    """PATCH condicional (atomico): solo cambia si sigue en de_estado. Devuelve True si esta llamada lo gano."""
    try:
        r = requests.patch(
            f"{URL_PEND}?id=eq.{fila_id}&estado=eq.{de_estado}",
            headers=dict(HEADERS_SB, Prefer="return=representation"),
            json=cambios, timeout=15)
        if r.status_code >= 300:
            return False
        filas = r.json()
        return isinstance(filas, list) and len(filas) > 0
    except Exception:
        return False

def sb_marcar_recarga(usuario, pedido_ref, cambios):
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/recargas?usuario=eq.{usuario}&pedido_id=eq.{pedido_ref}",
            headers=HEADERS_SB, json=cambios, timeout=15)
    except Exception as e:
        print(f"[TCG WATCH] no se pudo actualizar recargas: {e}", flush=True)

def _creado_dt(fila):
    from datetime import timezone
    try:
        v = str(fila.get("creado")).replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return ahora_utc()

def _avisar_admin(texto):
    destinos = [ADMIN_CHAT_ID] if ADMIN_CHAT_ID else [cid for cid, s in sesiones.items() if s.get("es_admin")]
    for cid in destinos:
        try:
            enviar(cid, texto)
        except Exception:
            pass

def _saldo_de(usuario):
    try:
        return sb_get_usuario(usuario)["saldo"]
    except Exception:
        return "?"

def vigilar_fila(fila):
    """Revisa un pendiente. Devuelve el estado final aplicado o None si sigue pendiente."""
    fid = fila["id"]
    # 1) Reclamar la fila (si otro worker la tomo, no hacemos nada)
    if not sb_pend_cambiar(fid, "pendiente", {"estado": "revisando", "revisado": ahora_utc().strftime("%Y-%m-%dT%H:%M:%SZ")}):
        return None
    internal = fila.get("internal_order_id")
    try:
        r = lio_consultar(order_id=internal) if internal else lio_consultar(client_ref=fila.get("client_ref"))
        estado, oid = lio_estado(r)
        panel = fila.get("panel_id") or lio_numero_panel(r)
        if not r.get("ok"):
            estado = ""
    except Exception:
        estado, oid, panel = "", None, fila.get("panel_id")
    internal = internal or oid
    if panel and internal:
        panel_a_interno[panel] = internal
    pedido = panel or internal or fila.get("pedido_ref")
    chat_id, usuario = fila["chat_id"], fila["usuario"]
    monto = float(fila.get("monto") or 0)
    roblox = (fila.get("tipo") == "roblox") or (not fila.get("tipo") and es_roblox(fila))
    linea = _linea_producto(fila["producto"], fila.get("id_jugador"), roblox)

    if estado in LIO_EXITO and roblox:
        if sb_pend_cambiar(fid, "revisando", {"estado": "completado", "internal_order_id": internal, "panel_id": panel}):
            sb_marcar_recarga(usuario, fila.get("pedido_ref"), {"producto": f"{TCG_PREFIJO}{fila['producto']}", "pedido_id": pedido})
            saldo = _saldo_de(usuario) if fila.get("cobrado") else "-"
            codigos = extraer_codigos(r, (fila.get("client_ref"), internal, panel))
            if codigos:
                print(f"[TCG DEBUG] codigo encontrado en: {', '.join(c[2] for c in codigos)}", flush=True)
                enviar(chat_id,
                    f"Compra TCG completada\n\n"
                    f"{fila['producto']}\n"
                    f"{_texto_codigos(codigos)}\n"
                    f"Pedido #{pedido}\n"
                    f"Tu saldo: ${saldo}")
            else:
                print(f"[TCG DEBUG] pedido {pedido} completado sin codigo en la respuesta", flush=True)
                enviar(chat_id,
                    f"Compra TCG completada, pero el codigo no llego por la API.\n\n"
                    f"{fila['producto']}\n"
                    f"Pedido #{pedido}\n"
                    f"Revisa el codigo en el panel de LioGames (pedido #{pedido}) o con /tcgestado {pedido}\n"
                    f"Tu saldo: ${saldo}")
                _sin_codigo(chat_id, usuario, fila["producto"], pedido)
        return "completado"

    if estado in LIO_EXITO:
        if sb_pend_cambiar(fid, "revisando", {"estado": "completado", "internal_order_id": internal, "panel_id": panel}):
            sb_marcar_recarga(usuario, fila.get("pedido_ref"), {"producto": f"{TCG_PREFIJO}{fila['producto']}", "pedido_id": pedido})
            saldo = _saldo_de(usuario) if fila.get("cobrado") else "-"
            enviar(chat_id,
                f"Recarga TCG completada\n\n"
                f"{fila['producto']}\n"
                f"ID: {fila.get('id_jugador')}\n"
                f"Pedido #{pedido}\n"
                f"Tu saldo: ${saldo}")
        return "completado"

    if estado in LIO_FALLO:
        # Marcar primero (atomico) y despues devolver: nunca se devuelve dos veces
        if sb_pend_cambiar(fid, "revisando", {"estado": "reembolsado", "internal_order_id": internal, "panel_id": panel}):
            sb_marcar_recarga(usuario, fila.get("pedido_ref"), {"producto": f"{TCG_PREFIJO}{fila['producto']} (REEMBOLSADO)", "monto": 0})
            if fila.get("cobrado"):
                try:
                    sb_recargar_saldo(usuario, monto)
                    enviar(chat_id,
                        f"Pedido TCG #{pedido} fallido ({estado}).\n\n"
                        f"{linea}\n"
                        f"Se te devolvieron ${monto:.2f}\n"
                        f"Tu saldo: ${_saldo_de(usuario)}")
                except Exception as e:
                    print(f"[TCG WATCH] FALLO el reembolso de {usuario} ${monto} pedido {pedido}: {e}", flush=True)
                    _avisar_admin(f"Revisar: no se pudo devolver ${monto:.2f} a {usuario} (pedido TCG #{pedido}).")
            else:
                enviar(chat_id, f"Pedido TCG #{pedido} fallido ({estado}).\n{linea}\nNo se cobro saldo.")
        return "reembolsado"

    # Sigue pendiente (o sin respuesta)
    vencido = (ahora_utc() - _creado_dt(fila)).total_seconds() > TCG_MAX_HORAS * 3600
    if vencido:
        if sb_pend_cambiar(fid, "revisando", {"estado": "revision_manual", "internal_order_id": internal, "panel_id": panel}):
            _avisar_admin(
                f"Revision manual TCG: pedido #{pedido} lleva mas de {TCG_MAX_HORAS}h sin terminar.\n"
                f"Usuario: {usuario} | {linea}\n"
                f"Monto: ${monto:.2f} ({'cobrado' if fila.get('cobrado') else 'no cobrado'}). El cobro se mantiene.")
        return "revision_manual"
    sb_pend_cambiar(fid, "revisando", {"estado": "pendiente", "intentos": int(fila.get("intentos") or 0) + 1,
                                        "internal_order_id": internal, "panel_id": panel})
    return None

_pasada_lock = threading.Lock()

def watcher_pasada():
    """Una vuelta del vigilante. Devuelve un resumen."""
    resumen = {"revisados": 0, "finalizados": 0}
    if not SUPABASE_URL or not LIO_MEMBER_CODE or not LIO_SECRET:
        return resumen
    if not _pasada_lock.acquire(blocking=False):
        resumen["ocupado"] = True
        return resumen
    try:
        for fila in sb_pend_listar():
            resumen["revisados"] += 1
            try:
                if vigilar_fila(fila):
                    resumen["finalizados"] += 1
            except Exception as e:
                print(f"[TCG WATCH] error en fila {fila.get('id')}: {e}", flush=True)
    finally:
        _pasada_lock.release()
    return resumen

def _hilo_vigilante():
    while True:
        try:
            watcher_pasada()
        except Exception as e:
            print(f"[TCG WATCH] error en la pasada: {e}", flush=True)
        time.sleep(TCG_WATCH_SEGUNDOS)

_vigilante_iniciado = False

def iniciar_vigilante():
    global _vigilante_iniciado
    if _vigilante_iniciado or not TCG_WATCHER:
        return False
    _vigilante_iniciado = True
    threading.Thread(target=_hilo_vigilante, name="tcg-vigilante", daemon=True).start()
    return True

@app.route("/check-pendientes")
def check_pendientes():
    if CHECK_TOKEN and not hmac.compare_digest(request.args.get("token", ""), CHECK_TOKEN):
        return {"ok": False, "error": "token invalido"}, 403
    return {"ok": True, **watcher_pasada()}, 200

@app.route("/")
def index():
    return "Bot activo v8", 200

iniciar_vigilante()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
