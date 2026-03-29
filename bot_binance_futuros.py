import websocket
import json
import requests
import time
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
        "perdidas": perdidas
    }
    with open(STATE_FILE, "w") as f:
        json.dump(estado, f)

def cargar_estado():
    global capital, posicion, precio_entrada
    global trades, ganadas, perdidas

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            estado = json.load(f)

        capital = estado.get("capital", CAPITAL_INICIAL)
        posicion = estado.get("posicion", None)
        precio_entrada = estado.get("precio_entrada", 0)
        trades = estado.get("trades", 0)
        ganadas = estado.get("ganadas", 0)
        perdidas = estado.get("perdidas", 0)

        print("✅ Estado restaurado", flush=True)
    else:
        print("⚠️ No hay estado previo", flush=True)

# =========================
# 🔥 HISTORIAL (CLAVE)
# =========================
def cargar_historial():
    global klines

    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL.upper()}&interval={INTERVAL}&limit=150"
    data = requests.get(url).json()

    klines.clear()

    for k in data:
        klines.append({
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "closed": True
        })

    print("✅ Historial cargado", flush=True)

# =========================
# 🌐 WEB
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot activo"

def iniciar_web():
    t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000))))
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

# =========================
# 📲 TELEGRAM
# =========================
def enviar_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10
        )
    except:
        pass

# =========================
# 📊 ESTADO
# =========================
capital = CAPITAL_INICIAL
posicion = None
precio_entrada = 0

trades = 0
ganadas = 0
perdidas = 0

trend = 0
klines = []

# =========================
# 📈 EMA
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
# 🧠 INDICADOR (CLON TV)
# =========================
def calcular_senal():
    global trend

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

    L = 2

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

    dist_series = [abs(mavi[j]-kirmizi[j]) for j in range(len(mavi))]
    dist_media = sum(dist_series[-30:]) / 30

    dist = abs(mavi[i] - kirmizi[i])
    filtro = dist > dist_media * 0.3

    señal = None

    if cruce_up and confirm_up and filtro and trend != 1:
        señal = "BUY"
        trend = 1

    elif cruce_down and confirm_down and filtro and trend != -1:
        señal = "SELL"
        trend = -1

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
# 🔌 WS
# =========================
def on_message(ws, message):
    global klines, posicion, precio_entrada, capital
    global trades, ganadas, perdidas

    data = json.loads(message)
    k = data['k']

    candle = {
        "open": float(k["o"]),
        "high": float(k["h"]),
        "low": float(k["l"]),
        "close": float(k["c"]),
        "closed": k["x"]
    }

    if len(klines) == 0 or candle["closed"]:
        klines.append(candle)
        if len(klines) > 150:
            klines.pop(0)
    else:
        klines[-1] = candle

    if candle["closed"]:
        precio = candle["close"]
        pnl = calcular_pnl(precio)
        señal = calcular_senal()

        if posicion and pnl <= STOP_LOSS:
            capital *= (1 + pnl/100)
            posicion = None
            perdidas += 1
            guardar_estado()
            enviar_telegram(f"STOP LOSS {pnl:.2f}%")

        if señal:
            if posicion:
                capital *= (1 + pnl/100)

                if pnl > 0:
                    ganadas += 1
                else:
                    perdidas += 1

                trades += 1

            posicion = "LONG" if señal == "BUY" else "SHORT"
            precio_entrada = precio

            guardar_estado()

            enviar_telegram(f"{señal} {precio}")

def on_open(ws):
    print("WS conectado")
    enviar_telegram("✅ Conexión a Binance Exitosa")

def on_close(ws, *args):
    print("WS cerrado")

def on_error(ws, error):
    print("Error:", error)

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
            time.sleep(5)

# =========================
# 🚀 MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT BINANCE FUTUROS INICIADO")

    cargar_estado()
    trend = 0  # 🔥 importante

    cargar_historial()

    enviar_telegram("🚀 BOT BINANCE FUTUROS INICIADO")

    iniciar_web()
    iniciar_ws()
