import websocket
import json
import requests
import time
import os
import threading
from flask import Flask

# =========================
# FLASK
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    return "OK", 200

def iniciar_web():
    threading.Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 10000))
        ),
        daemon=True
    ).start()

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

# 🔥 CONTROL PROFESIONAL
velas_reales = 0
ultima_senal_enviada = None

# =========================
# TELEGRAM
# =========================
def enviar_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=3
        )
    except:
        pass

# =========================
# EMA / SMA
# =========================
def ema(src, length):
    ema_vals = []
    k = 2 / (length + 1)
    for i, v in enumerate(src):
        ema_vals.append(v if i == 0 else v * k + ema_vals[i - 1] * (1 - k))
    return ema_vals

def sma(src, length):
    return [
        None if i < length - 1
        else sum(src[i - length + 1:i + 1]) / length
        for i in range(len(src))
    ]

# =========================
# HISTÓRICO
# =========================
def cargar_historico():
    global klines, last_candle_time

    data = requests.get(
        f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL.upper()}&interval={INTERVAL}&limit=500"
    ).json()

    klines = [{
        "open": float(k[1]),
        "high": float(k[2]),
        "low": float(k[3]),
        "close": float(k[4]),
        "time": k[6]
    } for k in data]

    last_candle_time = klines[-1]["time"]

    print("📊 Histórico cargado", flush=True)

# =========================
# SINCRONIZAR TREND
# =========================
def sincronizar_trend():
    global trend, ultima_senal_enviada

    señal = calcular_senal()

    if señal == "BUY":
        trend = 1
        ultima_senal_enviada = "BUY"

    elif señal == "SELL":
        trend = -1
        ultima_senal_enviada = "SELL"

    print(f"🧠 Trend inicial: {trend}", flush=True)
    print(f"🚫 Bloqueando repetición inicial: {ultima_senal_enviada}", flush=True)

# =========================
# SEÑALES (NO TOCAR)
# =========================
def calcular_senal():
    global trend

    if len(klines) < 100:
        return None

    close = [k["close"] for k in klines]
    open_ = [k["open"] for k in klines]
    high = [k["high"] for k in klines]
    low = [k["low"] for k in klines]

    ohlc4 = [(o+h+l+c)/4 for o,h,l,c in zip(open_,high,low,close)]

    haOpen = [ohlc4[0]/2]
    for i in range(1,len(ohlc4)):
        haOpen.append((ohlc4[i]+haOpen[i-1])/2)

    haC = [
        (ohlc4[i]+haOpen[i]+max(high[i],haOpen[i])+min(low[i],haOpen[i]))/4
        for i in range(len(close))
    ]

    L=25

    EMA1=ema(haC,L)
    EMA2=ema(EMA1,L)
    EMA3=ema(EMA2,L)
    TMA1=[3*EMA1[i]-3*EMA2[i]+EMA3[i] for i in range(len(close))]

    EMA4=ema(TMA1,L)
    EMA5=ema(EMA4,L)
    EMA6=ema(EMA5,L)
    TMA2=[3*EMA4[i]-3*EMA5[i]+EMA6[i] for i in range(len(close))]

    mavi=TMA1
    kirmizi=TMA2

    i=-1

    cruce_up = mavi[i] > kirmizi[i] and mavi[i-1] <= kirmizi[i-1]
    cruce_down = mavi[i] < kirmizi[i] and mavi[i-1] >= kirmizi[i-1]

    confirm_up = mavi[i] > mavi[i-1]
    confirm_down = mavi[i] < mavi[i-1]

    dist=[abs(mavi[j]-kirmizi[j]) for j in range(len(mavi))]
    dist_media=sma(dist,30)

    if dist_media[i] is None:
        return None

    filtro = dist[i] > dist_media[i]*0.3

    if cruce_up and confirm_up and filtro and trend != 1:
        trend = 1
        return "BUY"

    if cruce_down and confirm_down and filtro and trend != -1:
        trend = -1
        return "SELL"

    return None

# =========================
# WEBSOCKET
# =========================
def on_message(ws, message):
    global klines, last_candle_time, velas_reales, ultima_senal_enviada

    data = json.loads(message)
    k = data['k']

    if not k["x"]:
        return

    candle_time = k["T"]

    # 🔥 BLOQUEAR HISTÓRICO
    if candle_time <= last_candle_time:
        return

    last_candle_time = candle_time
    velas_reales += 1

    candle = {
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "time": candle_time
    }

    klines.append(candle)
    if len(klines) > 500:
        klines.pop(0)

    señal = calcular_senal()

    if velas_reales >= 1 and señal:

        # 🔥 BLOQUEO ANTI-SEÑALES PASADAS / REPETIDAS
        if señal == ultima_senal_enviada:
            print("⛔ Señal repetida ignorada", flush=True)
            return

        ultima_senal_enviada = señal

        precio = candle["close"]

        print(f"🚀 {señal} | {precio}", flush=True)

        enviar_telegram(
            f"🚀 {señal}\n💰 Precio: {precio}"
        )

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
    url = f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}"

    while True:
        try:
            websocket.WebSocketApp(
                url,
                on_message=on_message
            ).run_forever()
        except:
            print("⚠️ Reconectando...", flush=True)
            time.sleep(5)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT FINAL ULTRA PRO INICIADO", flush=True)

    iniciar_web()
    threading.Thread(target=keep_alive, daemon=True).start()

    enviar_telegram("🤖 BOT ULTRA PRO ACTIVO")

    cargar_historico()
    sincronizar_trend()

    iniciar_ws()
