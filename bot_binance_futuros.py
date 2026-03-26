import websocket
import json
import requests
import time
import sys
import os
import threading
import socket
from flask import Flask

# =========================
# 🔥 SERVIDOR WEB (ANTI-SLEEP RENDER)
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Trading Activo 🚀"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def iniciar_web():
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

# =========================
# 🌐 CHECK INTERNET (CLAVE)
# =========================
def internet_disponible():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except:
        return False

# =========================
# ⚙️ CONFIG
# =========================
SYMBOL = "adausdt"
INTERVAL = "5m"

CAPITAL_INICIAL = 50.0
APALANCAMIENTO = 1
COMISION = 0.0004
STOP_LOSS = -1.35

# 🔐 ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("❌ Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")

# =========================
# 📲 TELEGRAM ROBUSTO
# =========================
def enviar_telegram(msg, preview=False):
    while not internet_disponible():
        print("❌ Sin internet...", flush=True)
        time.sleep(5)

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "disable_web_page_preview": not preview
        }, timeout=10)
    except Exception as e:
        print(f"⚠️ Error Telegram: {e}", flush=True)

# =========================
# 📊 ESTADO
# =========================
capital = CAPITAL_INICIAL
posicion = None
precio_entrada = 0

trades = 0
ganadas = 0
perdidas = 0

klines = []

# =========================
# 🧠 INDICADOR
# =========================
def ema(src, length):
    ema_vals = []
    k = 2/(length+1)
    for i,v in enumerate(src):
        if i == 0:
            ema_vals.append(v)
        else:
            ema_vals.append(v*k + ema_vals[i-1]*(1-k))
    return ema_vals

def calcular_senal():
    if len(klines) < 50:
        return None

    close = [k["close"] for k in klines]
    high = [k["high"] for k in klines]
    low = [k["low"] for k in klines]
    open_ = [k["open"] for k in klines]

    ohlc4 = [(o+h+l+c)/4 for o,h,l,c in zip(open_,high,low,close)]

    haOpen = [ohlc4[0]]
    for i in range(1,len(ohlc4)):
        haOpen.append((ohlc4[i] + haOpen[i-1]) / 2)

    haC = [(ohlc4[i] + haOpen[i] + max(high[i],haOpen[i]) + min(low[i],haOpen[i]))/4 for i in range(len(close))]

    L = 38

    EMA1 = ema(haC,L)
    EMA2 = ema(EMA1,L)
    EMA3 = ema(EMA2,L)
    TMA1 = [3*EMA1[i]-3*EMA2[i]+EMA3[i] for i in range(len(close))]

    EMA4 = ema(TMA1,L)
    EMA5 = ema(EMA4,L)
    EMA6 = ema(EMA5,L)
    TMA2 = [3*EMA4[i]-3*EMA5[i]+EMA6[i] for i in range(len(close))]

    mavi = TMA1
    kirmizi = TMA2

    i = -1

    cruce_up = mavi[i] > kirmizi[i] and mavi[i-1] <= kirmizi[i-1]
    cruce_down = mavi[i] < kirmizi[i] and mavi[i-1] >= kirmizi[i-1]

    confirm_up = mavi[i] > mavi[i-1]
    confirm_down = mavi[i] < mavi[i-1]

    dist = abs(mavi[i] - kirmizi[i])
    dist_media = sum([abs(mavi[j]-kirmizi[j]) for j in range(-30,0)]) / 30

    filtro = dist > dist_media * 0.3

    if cruce_up and confirm_up and filtro:
        return "BUY"
    elif cruce_down and confirm_down and filtro:
        return "SELL"
    return None

# =========================
# 💰 PNL
# =========================
def calcular_pnl(precio):
    if posicion == "LONG":
        return ((precio - precio_entrada) / precio_entrada) * 100
    elif posicion == "SHORT":
        return ((precio_entrada - precio) / precio_entrada) * 100
    return 0

# =========================
# 🔌 WS EVENTOS
# =========================
def on_message(ws, message):
    global klines, posicion, precio_entrada, capital
    global trades, ganadas, perdidas

    try:
        data = json.loads(message)
        k = data['k']
    except:
        return

    candle = {
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "closed": k["x"]
    }

    if len(klines) == 0 or candle["closed"]:
        klines.append(candle)
        if len(klines) > 100:
            klines.pop(0)
    else:
        klines[-1] = candle

    if candle["closed"]:
        precio = candle["close"]
        pnl = calcular_pnl(precio)
        señal = calcular_senal()

        # STOP LOSS
        if posicion and pnl <= STOP_LOSS:
            capital *= (1 + pnl/100)
            posicion = None
            perdidas += 1

            enviar_telegram(f"🛑 STOP LOSS {pnl:.2f}% | Capital: {capital:.2f}")

        # SEÑAL
        if señal:
            if posicion:
                capital *= (1 + pnl/100)

                if pnl > 0:
                    ganadas += 1
                else:
                    perdidas += 1

                trades += 1
                enviar_telegram(f"💰 Cierre {pnl:.2f}% | Capital: {capital:.2f}")

            posicion = "LONG" if señal == "BUY" else "SHORT"
            precio_entrada = precio

            enviar_telegram(f"🚀 {posicion} {precio}")

def on_open(ws):
    print("✅ WS conectado", flush=True)
    enviar_telegram("✅ Conexión a Binance Exitosa")

def on_close(ws, *args):
    print("❌ WS cerrado", flush=True)

def on_error(ws, error):
    print(f"⚠️ Error WS: {error}", flush=True)

# =========================
# 🔁 LOOP ROBUSTO (ANTI-CRASH)
# =========================
def iniciar_ws():
    socket_url = f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}"

    while True:
        if not internet_disponible():
            print("❌ Sin internet, reintentando...", flush=True)
            time.sleep(5)
            continue

        try:
            ws = websocket.WebSocketApp(
                socket_url,
                on_message=on_message,
                on_open=on_open,
                on_close=on_close,
                on_error=on_error
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)

        except Exception as e:
            print(f"🔥 Error crítico: {e}", flush=True)

        print("🔁 Reconectando en 5s...", flush=True)
        time.sleep(5)

# =========================
# 🚀 MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT BINANCE FUTUROS INICIADO", flush=True)

    enviar_telegram("🚀 BOT BINANCE FUTUROS INICIADO")

    iniciar_web()   # 🔥 clave para mantener vivo
    iniciar_ws()    # 🔥 loop infinito WS
