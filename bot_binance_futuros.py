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
# 🔥 ARCHIVO DE MEMORIA
# =========================
STATE_FILE = "estado_bot.json"

def guardar_estado():
    estado = {
        "capital": capital,
        "posicion": posicion,
        "precio_entrada": precio_entrada,
        "trades": trades,
        "ganadas": ganadas,
        "perdidas": perdidas,
        "trend": trend,
        "last_signal_bar": last_signal_bar
    }
    with open(STATE_FILE, "w") as f:
        json.dump(estado, f)

def cargar_estado():
    global capital, posicion, precio_entrada
    global trades, ganadas, perdidas, trend, last_signal_bar

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            estado = json.load(f)

        capital = estado.get("capital", CAPITAL_INICIAL)
        posicion = estado.get("posicion", None)
        precio_entrada = estado.get("precio_entrada", 0)
        trades = estado.get("trades", 0)
        ganadas = estado.get("ganadas", 0)
        perdidas = estado.get("perdidas", 0)
        trend = estado.get("trend", 0)
        last_signal_bar = estado.get("last_signal_bar", -1)

        print("✅ Estado restaurado", flush=True)
    else:
        last_signal_bar = -1
        print("⚠️ No hay estado previo, iniciando limpio", flush=True)

# =========================
# 🌐 WEB (ANTI-SLEEP)
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
# 🌐 INTERNET
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
INTERVAL = "1m"

CAPITAL_INICIAL = 50.0
STOP_LOSS = -1.35

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("❌ Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")

# =========================
# 📲 TELEGRAM
# =========================
def enviar_telegram(msg):
    while not internet_disponible():
        time.sleep(5)

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg
        }, timeout=10)
    except:
        pass

# =========================
# 📊 ESTADO GLOBAL
# =========================
capital = CAPITAL_INICIAL
posicion = None
precio_entrada = 0

trades = 0
ganadas = 0
perdidas = 0

trend = 0
last_signal_bar = -1

klines = []

# =========================
# 📈 EMA EXACTA
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

# =========================
# 🧠 INDICADOR IGUAL A TV
# =========================
def calcular_senal():
    global trend, last_signal_bar

    if len(klines) < 50:
        return None

    close = [k["close"] for k in klines]
    high = [k["high"] for k in klines]
    low = [k["low"] for k in klines]
    open_ = [k["open"] for k in klines]

    # 🔥 OHLC4
    ohlc4 = [(o+h+l+c)/4 for o,h,l,c in zip(open_,high,low,close)]

    # 🔥 haOpen EXACTO (igual que Pine)
    haOpen = [0.0] * len(ohlc4)
    for i in range(len(ohlc4)):
        if i == 0:
            haOpen[i] = (ohlc4[i] + 0) / 2
        else:
            haOpen[i] = (ohlc4[i] + haOpen[i-1]) / 2

    # 🔥 haClose
    haC = [(ohlc4[i] + haOpen[i] + max(high[i],haOpen[i]) + min(low[i],haOpen[i]))/4 for i in range(len(close))]

    L = 2

    # 🔥 TMA1
    EMA1 = ema(haC,L)
    EMA2 = ema(EMA1,L)
    EMA3 = ema(EMA2,L)
    TMA1 = [3*EMA1[i]-3*EMA2[i]+EMA3[i] for i in range(len(close))]

    # 🔥 TMA2
    EMA4 = ema(TMA1,L)
    EMA5 = ema(EMA4,L)
    EMA6 = ema(EMA5,L)
    TMA2 = [3*EMA4[i]-3*EMA5[i]+EMA6[i] for i in range(len(close))]

    mavi = TMA1
    kirmizi = TMA2

    i = len(mavi) - 2

    # 🔥 CRUCE REAL
    cruce_up = mavi[i] > kirmizi[i] and mavi[i-1] <= kirmizi[i-1]
    cruce_down = mavi[i] < kirmizi[i] and mavi[i-1] >= kirmizi[i-1]

    # 🔥 CONFIRMACIÓN
    confirm_up = mavi[i] > mavi[i-1]
    confirm_down = mavi[i] < mavi[i-1]

    # 🔥 FILTRO VOLATILIDAD
    dist_series = [abs(mavi[j]-kirmizi[j]) for j in range(len(mavi))]
    dist_media = sum(dist_series[-30:]) / 30
    dist = abs(mavi[i] - kirmizi[i])
    filtro = dist > dist_media * 0.3

    señal = None

    # 🔥 EVITAR DUPLICADOS POR VELA
    current_bar = len(klines)

    if current_bar == last_signal_bar:
        return None

    if cruce_up and confirm_up and filtro and trend != 1:
        trend = 1
        señal = "BUY"
        last_signal_bar = current_bar

    elif cruce_down and confirm_down and filtro and trend != -1:
        trend = -1
        señal = "SELL"
        last_signal_bar = current_bar

    return señal

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

    # 🔥 ACTUALIZACIÓN CORRECTA DE VELAS
    if len(klines) == 0:
        klines.append(candle)
    else:
        if candle["closed"]:
            klines.append(candle)
            if len(klines) > 100:
                klines.pop(0)
        else:
            klines[-1] = candle

    # 🔥 SOLO VELA CERRADA (IGUAL TV)
    if candle["closed"]:
        precio = candle["close"]
        pnl = calcular_pnl(precio)
        señal = calcular_senal()

        # STOP LOSS
        if posicion and pnl <= STOP_LOSS:
            capital *= (1 + pnl/100)
            posicion = None
            perdidas += 1

            guardar_estado()

            enviar_telegram(f"🛑 STOP LOSS {pnl:.2f}%\n💰 Capital: {capital:.2f}")

        # NUEVA SEÑAL
        if señal:
            if posicion:
                capital *= (1 + pnl/100)

                if pnl > 0:
                    ganadas += 1
                else:
                    perdidas += 1

                trades += 1

                enviar_telegram(
                    f"💰 Cierre operación\n"
                    f"Resultado: {pnl:.2f}%\n"
                    f"Capital: {capital:.2f}\n"
                    f"Trades: {trades}"
                )

            posicion = "LONG" if señal == "BUY" else "SHORT"
            precio_entrada = precio

            guardar_estado()

            enviar_telegram(
                f"🚀 NUEVA SEÑAL\n"
                f"Tipo: {posicion}\n"
                f"Precio: {precio}"
            )

# =========================
# 🔌 EVENTOS WS
# =========================
def on_open(ws):
    print("✅ WS conectado", flush=True)
    enviar_telegram("✅ Conexión a Binance Exitosa")

def on_close(ws, *args):
    print("❌ WS cerrado", flush=True)
    enviar_telegram("❌ WS cerrado, reconectando...")

def on_error(ws, error):
    print(f"⚠️ Error WS: {error}", flush=True)

# =========================
# 🔁 LOOP
# =========================
def iniciar_ws():
    socket_url = f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}"

    while True:
        try:
            ws = websocket.WebSocketApp(
                socket_url,
                on_message=on_message,
                on_open=on_open,
                on_close=on_close,
                on_error=on_error
            )
            ws.run_forever()
        except:
            print("⚠️ Error conexión, reconectando...", flush=True)
            time.sleep(5)

# =========================
# 🚀 MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT BINANCE FUTUROS INICIADO", flush=True)

    cargar_estado()

    enviar_telegram("🚀 BOT BINANCE FUTUROS INICIADO")

    iniciar_web()
    iniciar_ws()
