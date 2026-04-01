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
# TRADING ENGINE
# =========================
capital = 100
capital_inicial = 100

posicion = None
precio_entrada = 0.0
cantidad = 0.0

trades = 0
ganadas = 0
perdidas = 0
pnl_total = 0.0

comision = 0.0005

start_time = time.time()
ultimo_resumen = time.time()

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
# SEÑALES
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
# TRADING FUNCIONES
# =========================
def abrir_operacion(tipo, precio):
    global posicion, precio_entrada, cantidad, capital

    posicion = tipo
    precio_entrada = precio
    cantidad = capital / precio

    fee = capital * comision
    capital -= fee

    print(f"🟢 ABRE {tipo} | {precio} | Fee: {fee}", flush=True)


def cerrar_operacion(precio):
    global posicion, precio_entrada, capital
    global trades, ganadas, perdidas, pnl_total

    if posicion is None:
        return

    if posicion == "BUY":
        pnl = (precio - precio_entrada) * cantidad
    else:
        pnl = (precio_entrada - precio) * cantidad

    fee = capital * comision
    pnl -= fee

    capital += pnl
    pnl_total += pnl
    trades += 1

    if pnl > 0:
        ganadas += 1
    else:
        perdidas += 1

    print(f"🔴 CIERRA {posicion} | PnL: {pnl:.2f} | Capital: {capital:.2f}", flush=True)

    enviar_telegram(f"🔴 CIERRE {posicion}\n💰 {precio}\n📊 PnL: {pnl:.2f}\n💼 Capital: {capital:.2f}")

    posicion = None


def check_stop(precio):
    if posicion == "BUY" and precio <= precio_entrada * 0.99:
        cerrar_operacion(precio)
    elif posicion == "SELL" and precio >= precio_entrada * 1.01:
        cerrar_operacion(precio)


def resumen_diario():
    global ultimo_resumen

    if time.time() - ultimo_resumen >= 86400:
        dias = (time.time() - start_time) / 86400

        enviar_telegram(
            f"📊 RESUMEN\n"
            f"📅 Días: {dias:.2f}\n"
            f"💼 Capital: {capital:.2f}\n"
            f"📈 PnL: {pnl_total:.2f}\n"
            f"🔢 Trades: {trades}\n"
            f"✅ Ganadas: {ganadas}\n"
            f"❌ Perdidas: {perdidas}"
        )

        ultimo_resumen = time.time()

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
        print("🧠 Sincronizado", flush=True)
        return

    check_stop(precio)

    if señal:
        if posicion is not None:
            cerrar_operacion(precio)

        abrir_operacion(señal, precio)

    resumen_diario()

# =========================
# KEEP ALIVE
# =========================
def keep_alive():
    while True:
        try:
            requests.get("http://127.0.0.1:10000", timeout=2)
            print("💓 Alive", flush=True)
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
            print("🔄 Iniciando WebSocket...", flush=True)

            ws = websocket.WebSocketApp(socket_url, on_message=on_message)

            wst = threading.Thread(
                target=ws.run_forever,
                kwargs={"ping_interval": 20, "ping_timeout": 10}
            )
            wst.daemon = True
            wst.start()

            while True:
                print("💓 Bot vivo...", flush=True)
                time.sleep(10)

                if not wst.is_alive():
                    print("⚠️ WS muerto", flush=True)
                    break

        except Exception as e:
            print(f"❌ Error WS: {e}", flush=True)
            time.sleep(5)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT INICIADO", flush=True)

    iniciar_web()
    threading.Thread(target=keep_alive, daemon=True).start()

    enviar_telegram("🤖 BOT ACTIVO")

    cargar_historico()
    iniciar_ws()
