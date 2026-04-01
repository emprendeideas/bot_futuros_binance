import websocket
import json
import requests
import time
import os
import threading
from flask import Flask

# =========================
# FLASK (RENDER)
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def iniciar_web():
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

# =========================
# CONFIG
# =========================
SYMBOL = "adausdt"
INTERVAL = "1m"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("❌ Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")

klines = []
trend = 0
last_candle_time = None
iniciado = False

# =========================
# CONTROL DE OPERACIONES
# =========================
posicion = None  # "BUY" o "SELL"
precio_entrada = 0.0

capital = 100.0
comision = 0.0005

operacion_activa = False

# =========================
# TELEGRAM
# =========================
def enviar_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg
        }, timeout=3)
    except:
        pass

# =========================
# EMA / SMA
# =========================
def ema(src, length):
    ema_vals = []
    k = 2 / (length + 1)
    for i, v in enumerate(src):
        if i == 0:
            ema_vals.append(v)
        else:
            ema_vals.append(v * k + ema_vals[i - 1] * (1 - k))
    return ema_vals

def sma(src, length):
    out = []
    for i in range(len(src)):
        if i < length - 1:
            out.append(None)
        else:
            out.append(sum(src[i - length + 1:i + 1]) / length)
    return out

# =========================
# HISTÓRICO
# =========================
def cargar_historico():
    global klines, last_candle_time

    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL.upper()}&interval={INTERVAL}&limit=500"
    data = requests.get(url).json()

    klines = []
    for k in data:
        klines.append({
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "time": k[6]
        })

    last_candle_time = klines[-1]["time"]

    print("📊 Histórico cargado", flush=True)

# =========================
# SEÑALES (NO TOCAR)
# =========================
def calcular_senal():
    global trend

    if len(klines) < 100:
        return None

    open_ = [k["open"] for k in klines]
    high = [k["high"] for k in klines]
    low = [k["low"] for k in klines]
    close = [k["close"] for k in klines]

    ohlc4 = [(o + h + l + c) / 4 for o, h, l, c in zip(open_, high, low, close)]

    haOpen = [0.0] * len(ohlc4)
    for i in range(len(ohlc4)):
        if i == 0:
            haOpen[i] = ohlc4[i] / 2
        else:
            haOpen[i] = (ohlc4[i] + haOpen[i - 1]) / 2

    haC = [
        (ohlc4[i] + haOpen[i] + max(high[i], haOpen[i]) + min(low[i], haOpen[i])) / 4
        for i in range(len(close))
    ]

    L = 2

    EMA1 = ema(haC, L)
    EMA2 = ema(EMA1, L)
    EMA3 = ema(EMA2, L)
    TMA1 = [3 * EMA1[i] - 3 * EMA2[i] + EMA3[i] for i in range(len(close))]

    EMA4 = ema(TMA1, L)
    EMA5 = ema(EMA4, L)
    EMA6 = ema(EMA5, L)
    TMA2 = [3 * EMA4[i] - 3 * EMA5[i] + EMA6[i] for i in range(len(close))]

    mavi = TMA1
    kirmizi = TMA2

    i = -1

    cruce_up = mavi[i] > kirmizi[i] and mavi[i - 1] <= kirmizi[i - 1]
    cruce_down = mavi[i] < kirmizi[i] and mavi[i - 1] >= kirmizi[i - 1]

    confirm_up = mavi[i] > mavi[i - 1]
    confirm_down = mavi[i] < mavi[i - 1]

    dist = [abs(mavi[j] - kirmizi[j]) for j in range(len(mavi))]
    dist_media = sma(dist, 30)

    if dist_media[i] is None:
        return None

    filtro_vol = dist[i] > dist_media[i] * 0.3

    if cruce_up and confirm_up and filtro_vol and trend != 1:
        trend = 1
        return "BUY"

    elif cruce_down and confirm_down and filtro_vol and trend != -1:
        trend = -1
        return "SELL"

    return None

# =========================
# TRADING CONTROL
# =========================
def abrir_operacion(tipo, precio):
    global posicion, precio_entrada, capital, operacion_activa

    if operacion_activa:
        return

    posicion = tipo
    precio_entrada = precio
    operacion_activa = True

    fee = capital * comision
    capital -= fee

    print(f"🟢 ABRE {tipo} @ {precio}", flush=True)

    enviar_telegram(f"🟢 ABRE {tipo}\n💰 {precio}")


def cerrar_operacion(precio):
    global posicion, precio_entrada, capital, operacion_activa

    if not operacion_activa:
        return

    if posicion == "BUY":
        pnl = (precio - precio_entrada) / precio_entrada * capital
    else:
        pnl = (precio_entrada - precio) / precio_entrada * capital

    fee = capital * comision
    pnl -= fee

    capital += pnl

    print(f"🔴 CIERRA {posicion} | PnL: {pnl:.2f}", flush=True)

    enviar_telegram(
        f"🔴 CIERRE {posicion}\n"
        f"💰 {precio}\n"
        f"📊 PnL: {pnl:.2f}\n"
        f"💼 Capital: {capital:.2f}"
    )

    posicion = None
    operacion_activa = False


def check_stop(precio):
    if not operacion_activa:
        return

    if posicion == "BUY" and precio <= precio_entrada * 0.99:
        print("⛔ STOP BUY", flush=True)
        cerrar_operacion(precio)

    elif posicion == "SELL" and precio >= precio_entrada * 1.01:
        print("⛔ STOP SELL", flush=True)
        cerrar_operacion(precio)

# =========================
# WEBSOCKET
# =========================
def on_message(ws, message):
    global klines, last_candle_time, iniciado

    data = json.loads(message)
    k = data['k']

    if not k["x"]:
        return

    candle_time = k["T"]

    if candle_time <= last_candle_time:
        return

    candle = {
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "time": candle_time
    }

    last_candle_time = candle_time
    klines.append(candle)

    if len(klines) > 500:
        klines.pop(0)

    señal = calcular_senal()
    precio = candle["close"]

    if not iniciado:
        iniciado = True
        print("🧠 Bot sincronizado", flush=True)
        return

    # 🔥 STOP siempre activo
    check_stop(precio)

    if señal:
        print(f"🚀 {señal} | {precio}", flush=True)

        if operacion_activa:
            cerrar_operacion(precio)

        abrir_operacion(señal, precio)

# =========================
# KEEP ALIVE
# =========================
def keep_alive():
    while True:
        try:
            requests.get("http://127.0.0.1:10000", timeout=2)
        except:
            pass
        time.sleep(60)

# =========================
# WS START
# =========================
def iniciar_ws():
    socket_url = f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}"

    while True:
        try:
            ws = websocket.WebSocketApp(
                socket_url,
                on_message=on_message
            )
            ws.run_forever()
        except:
            print("⚠️ Reconectando...", flush=True)
            time.sleep(5)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT FINAL DEFINITIVO INICIADO", flush=True)

    iniciar_web()
    threading.Thread(target=keep_alive, daemon=True).start()

    enviar_telegram("🤖 BOT ACTIVO (TIEMPO REAL REAL)")

    cargar_historico()
    iniciar_ws()
