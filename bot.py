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
    data = r.j
