# import websocket
import json
import requests
import time
import os
import threading
from flask import Flask
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CallbackQueryHandler

# =========================
# FLASK
# =========================
app = Flask(__name__)

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "BOT ACTIVO 🚀", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def iniciar_web():
    t = threading.Thread(target=run_web)
    t.start()

# =========================
# CONFIG
# =========================
SYMBOL = "adausdt"
INTERVAL = "1m"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID"))

klines = []
trend = 0
last_candle_time = None

ultima_senal_historica = None
primera_senal_valida = False

# =========================
# 💰 TRADING SIMULADO
# =========================
capital = 100.0
capital_inicial = 100.0
posicion = None
entry_price = 0.0
trades = 0
FEE = 0.0005
ultimo_precio = 0

bot_activo = True
detener_bot_total = False

nivel_actual = 1
SL_PORCENTAJE = -1.7 
EMA_LENGTH = 2

# =========================
# TELEGRAM SIMPLE
# =========================
def enviar_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=3
        )
    except Exception as e:
        print("ERROR TELEGRAM:", e)

# =========================
# 🔥 STOP LOSS (FUNCION COPIADA EXACTA)
# =========================
def verificar_stop_loss():
    global capital, posicion, entry_price, trades, ultimo_precio

    if posicion is None:
        return False

    if posicion == "BUY":
        pnl = (ultimo_precio - entry_price) / entry_price * 100
    else:
        pnl = (entry_price - ultimo_precio) / entry_price * 100

    if pnl <= SL_PORCENTAJE:
        capital *= (1 + SL_PORCENTAJE / 100)
        capital *= (1 - FEE)

        trades += 1

        enviar_telegram(
            f"🔥 STOP LOSS ACTIVADO\n"
            f"📊 PnL: {SL_PORCENTAJE}%\n"
            f"💰 Capital: {capital:.2f} USDT\n"
            f"🤖 Trades: {trades}"
        )

        posicion = None
        return True

    return False

# =========================
# TELEGRAM BOT
# =========================
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, workers=1)

def enviar_botones():
    keyboard = [
        [InlineKeyboardButton("⏸️ Pausar", callback_data="pause"),
         InlineKeyboardButton("▶️ Reanudar", callback_data="resume")],
        [InlineKeyboardButton("🔴 Cerrar operación", callback_data="close")],
        [InlineKeyboardButton("💰 Saldo", callback_data="saldo")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    bot.send_message(
        chat_id=TELEGRAM_ADMIN_ID,
        text="⚙️ CONTROL DEL BOT",
        reply_markup=reply_markup
    )

def enviar_control_ganancia():
    keyboard = [
        [InlineKeyboardButton("✅ Continuar", callback_data="continue_profit"),
         InlineKeyboardButton("🛑 Parar", callback_data="stop_profit")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    bot.send_message(
        chat_id=TELEGRAM_ADMIN_ID,
        text="📊 Se alcanzó el objetivo mensual.\n¿Desea continuar operando?",
        reply_markup=reply_markup
    )

# =========================
# CIERRE MANUAL
# =========================
def cerrar_manual():
    global capital, posicion, entry_price, trades

    if posicion is None:
        return

    if posicion == "BUY":
        pnl = (ultimo_precio - entry_price) / entry_price
    else:
        pnl = (entry_price - ultimo_precio) / entry_price

    capital *= (1 + pnl)
    capital *= (1 - FEE)

    trades += 1

    verificar_ganancia()

    enviar_telegram(
        f"🧑‍💻 CIERRE MANUAL {posicion}\n"
        f"💰 Capital: {capital:.2f} USDT\n"
        f"📊 PnL: {pnl*100:.2f}%\n"
        f"🤖 Trades: {trades}"
    )

    posicion = None

# =========================
# BOTONES
# =========================
def manejar_botones(update: Update, context):
    global bot_activo, nivel_actual, detener_bot_total

    query = update.callback_query
    query.answer()

    data = query.data

    if data == "pause":
        bot_activo = False
        bot.send_message(TELEGRAM_ADMIN_ID, "⏸ Bot pausado")
        enviar_botones()

    elif data == "resume":
        bot_activo = True
        bot.send_message(TELEGRAM_ADMIN_ID, "▶️ Bot reanudado")
        enviar_botones()

    elif data == "close":
        cerrar_manual()
        bot.send_message(TELEGRAM_ADMIN_ID, "🔴 Operación cerrada manualmente")
        enviar_botones()

    elif data == "saldo":
        bot.send_message(
            TELEGRAM_ADMIN_ID,
            f"💰 Capital: {capital:.2f} USDT\n📊 Posición: {posicion}"
        )
        enviar_botones()

    elif data == "continue_profit":
        bot.send_message(TELEGRAM_ADMIN_ID, "✅ Se continúa operando")

    elif data == "stop_profit":
        bot_activo = False
        detener_bot_total = True

        ganancia = ((capital - capital_inicial) / capital_inicial) * 100

        enviar_telegram(
            f"🏁 OPERACIONES FINALIZADAS DEL MES\n\n"
            f"📊 Ganancia total: {ganancia:.2f}%\n"
            f"💰 Capital final: {capital:.2f} USDT\n"
            f"🤖 Total trades: {trades}"
        )

dispatcher.add_handler(CallbackQueryHandler(manejar_botones))        

# =========================
# INICIAR TELEGRAM
# =========================
def iniciar_bot_telegram():
    def run():
        offset = None
        while True:
            try:
                updates = bot.get_updates(offset=offset, timeout=10)
                for update in updates:
                    dispatcher.process_update(update)
                    offset = update.update_id + 1
            except Exception as e:
                print("Error Telegram:", e)
                time.sleep(2)

    threading.Thread(target=run, daemon=True).start()

# =========================
# 🔥 CONTROL GANANCIA
# =========================
def verificar_ganancia():
    global nivel_actual

    ganancia = ((capital - capital_inicial) / capital_inicial) * 100

    print(f"[DEBUG] Ganancia actual: {ganancia:.2f}% | Nivel: {nivel_actual}")

    if ganancia >= nivel_actual:
        nivel_detectado = nivel_actual
        nivel_actual += 1

        enviar_telegram(
            f"🎯 ¡Objetivo alcanzado!\n\n"
            f"📈 Se llegó al +{nivel_detectado}% de ganancia mensual 🚀\n"
            f"💰 Ganancia actual: {ganancia:.2f}%\n"
            f"🔥 Seguimos creciendo día a día!"
        )

        enviar_control_ganancia()

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

    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL.upper()}&interval={INTERVAL}&limit=500"

    while True:  # 🔁 LOOP INFINITO (clave)
        try:
            print("🔄 Intentando cargar histórico...", flush=True)

            response = requests.get(url, timeout=10)
            print(f"[STATUS] {response.status_code}", flush=True)

            if response.status_code != 200:
                print(f"[ERROR HTTP] {response.status_code}", flush=True)
                time.sleep(3)
                continue

            data = response.json()

            # 👇 NUEVO: ver respuesta (recortada para no saturar logs)
            print(f"[BINANCE DATA] {str(data)[:200]}", flush=True)

            # ⚠️ Validar estructura
            if not isinstance(data, list):
                print(f"[ERROR BINANCE] {data}", flush=True)
                time.sleep(3)
                continue

            if len(data) == 0 or not isinstance(data[0], list):
                print(f"[ERROR FORMATO] {data}", flush=True)
                time.sleep(3)
                continue

            klines = [{
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "time": k[6]
            } for k in data]

            last_candle_time = klines[-2]["time"]

            print("✅ HISTÓRICO OK", flush=True)
            return  # ✔ sale SOLO cuando funciona

        except Exception as e:
            print(f"[EXCEPTION HISTÓRICO] {e}", flush=True)
            time.sleep(3)

# =========================
# 🔥 ÚLTIMA SEÑAL REAL
# =========================
def obtener_ultima_senal_real():
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

    haC = [(ohlc4[i]+haOpen[i]+max(high[i],haOpen[i])+min(low[i],haOpen[i]))/4 for i in range(len(close))]

    L = EMA_LENGTH

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

    dist=[abs(mavi[j]-kirmizi[j]) for j in range(len(mavi))]
    dist_media=sma(dist,30)

    temp_trend = 0
    ultima = None

    for i in range(1,len(close)):
        if dist_media[i] is None:
            continue

        cruce_up = mavi[i]>kirmizi[i] and mavi[i-1]<=kirmizi[i-1]
        cruce_down = mavi[i]<kirmizi[i] and mavi[i-1]>=kirmizi[i-1]

        confirm_up = mavi[i]>mavi[i-1]
        confirm_down = mavi[i]<mavi[i-1]

        filtro = dist[i]>dist_media[i]*0.3

        if cruce_up and confirm_up and filtro and temp_trend != 1:
            temp_trend = 1
            ultima = "BUY"

        elif cruce_down and confirm_down and filtro and temp_trend != -1:
            temp_trend = -1
            ultima = "SELL"

    trend = temp_trend
    return ultima

# =========================
# 🔥 MEMORIA IGUAL QUE PINE
# =========================
precio_memoria = None
tipo_memoria = 0  # 1 BUY, -1 SELL

# =========================
# 🔥 RECONSTRUCCIÓN HISTÓRICA (CLON REAL PINE)
# =========================
def reconstruir_estado_pine():
    global trend, precio_memoria, tipo_memoria

    if len(klines) < 100:
        return None

    close = [k["close"] for k in klines]
    open_ = [k["open"] for k in klines]
    high = [k["high"] for k in klines]
    low = [k["low"] for k in klines]

    # ===== BASE =====
    ohlc4 = [(o+h+l+c)/4 for o,h,l,c in zip(open_,high,low,close)]

    haOpen=[ohlc4[0]/2]
    for i in range(1,len(ohlc4)):
        haOpen.append((ohlc4[i]+haOpen[i-1])/2)

    haC=[(ohlc4[i]+haOpen[i]+max(high[i],haOpen[i])+min(low[i],haOpen[i]))/4 for i in range(len(close))]

    L= EMA_LENGTH

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

    dist=[abs(mavi[j]-kirmizi[j]) for j in range(len(mavi))]
    dist_media=sma(dist,30)

    # 🔥 RESET TOTAL (igual que Pine al iniciar)
    trend = 0
    precio_memoria = None
    tipo_memoria = 0

    ultima = None

    # 🔁 RECORRIDO HISTÓRICO REAL
    for i in range(1, len(close)):

        if dist_media[i] is None:
            continue

        # ===== BASE =====
        cruce_up = mavi[i]>kirmizi[i] and mavi[i-1]<=kirmizi[i-1]
        cruce_down = mavi[i]<kirmizi[i] and mavi[i-1]>=kirmizi[i-1]

        confirm_up = mavi[i]>mavi[i-1]
        confirm_down = mavi[i]<mavi[i-1]

        filtro = dist[i]>dist_media[i]*0.3

        long_base = False
        short_base = False

        if cruce_up and confirm_up and filtro and trend != 1:
            long_base = True
            trend = 1

        elif cruce_down and confirm_down and filtro and trend != -1:
            short_base = True
            trend = -1

        senal = 1 if long_base else -1 if short_base else 0

        if senal == 0:
            continue

        # ===== MEMORIA EXACTA =====
        if tipo_memoria == 0:
            precio_memoria = close[i]
            tipo_memoria = senal
            ultima = "BUY" if senal == 1 else "SELL"

        else:
            es_opuesta = senal != tipo_memoria

            if not es_opuesta:
                continue

            if tipo_memoria == 1:
                distancia = (close[i] - precio_memoria) / precio_memoria * 100
            else:
                distancia = (precio_memoria - close[i]) / precio_memoria * 100

            en_rango = (-0.49 <= distancia <= -0.01)

            if en_rango:
                continue

            precio_memoria = close[i]
            tipo_memoria = senal

            ultima = "BUY" if senal == 1 else "SELL"

    return ultima

# =========================
# 🔥 SEÑAL FINAL (CLON EXACTO PINE)
# =========================
def calcular_senal_final():
    global trend, precio_memoria, tipo_memoria

    if len(klines) < 100:
        return None

    close = [k["close"] for k in klines]
    open_ = [k["open"] for k in klines]
    high = [k["high"] for k in klines]
    low = [k["low"] for k in klines]

    # ===== BASE =====
    ohlc4 = [(o+h+l+c)/4 for o,h,l,c in zip(open_,high,low,close)]

    haOpen=[ohlc4[0]/2]
    for i in range(1,len(ohlc4)):
        haOpen.append((ohlc4[i]+haOpen[i-1])/2)

    haC=[(ohlc4[i]+haOpen[i]+max(high[i],haOpen[i])+min(low[i],haOpen[i]))/4 for i in range(len(close))]

    L= EMA_LENGTH

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

    # ===== FILTRO VOL =====
    dist=[abs(mavi[j]-kirmizi[j]) for j in range(len(mavi))]
    dist_media=sma(dist,30)

    if dist_media[i] is None:
        return None

    # ===== BASE SIGNAL =====
    cruce_up = mavi[i]>kirmizi[i] and mavi[i-1]<=kirmizi[i-1]
    cruce_down = mavi[i]<kirmizi[i] and mavi[i-1]>=kirmizi[i-1]

    confirm_up = mavi[i]>mavi[i-1]
    confirm_down = mavi[i]<mavi[i-1]

    filtro = dist[i]>dist_media[i]*0.3

    long_base = False
    short_base = False

    if cruce_up and confirm_up and filtro and trend != 1:
        long_base = True
        trend = 1

    elif cruce_down and confirm_down and filtro and trend != -1:
        short_base = True
        trend = -1

    # ===== SENAL =====
    senal = 1 if long_base else -1 if short_base else 0

    if senal == 0:
        return None

    # ===== MEMORIA (CLON EXACTO) =====
    if tipo_memoria == 0:
        precio_memoria = close[i]
        tipo_memoria = senal
        return "BUY" if senal == 1 else "SELL"

    else:
        es_opuesta = senal != tipo_memoria

        if not es_opuesta:
            return None

        if tipo_memoria == 1:
            distancia = (close[i] - precio_memoria) / precio_memoria * 100
        else:
            distancia = (precio_memoria - close[i]) / precio_memoria * 100

        en_rango = (-0.49 <= distancia <= -0.01)

        if en_rango:
            return None

        # ✔ PASA FILTRO
        precio_memoria = close[i]
        tipo_memoria = senal

        return "BUY" if senal == 1 else "SELL"

# =========================
# TRADING
# =========================
def ejecutar_trade(señal, precio):
    global capital, posicion, entry_price, trades

    if posicion is not None:
        if posicion == "BUY":
            pnl = (precio - entry_price) / entry_price
        else:
            pnl = (entry_price - precio) / entry_price

        capital *= (1 + pnl)
        capital *= (1 - FEE)

        trades += 1

        verificar_ganancia()

        enviar_telegram(
            f"❌ CIERRE {posicion}\n"
            f"💰 Capital: {capital:.2f} USDT\n"
            f"📊 PnL: {pnl*100:.2f}%\n"
            f"🤖 Trades: {trades}"
        )

    posicion = señal
    entry_price = precio
    capital *= (1 - FEE)

    enviar_telegram(
        f"🚀 APERTURA {señal}\n"
        f"💰 Precio: {precio}\n"
        f"💼 Capital: {capital:.2f} USDT"
    )

    verificar_ganancia()

# =========================
# WEBSOCKET
# =========================
def on_message(ws, message):
    global klines, last_candle_time, primera_senal_valida, ultimo_precio, detener_bot_total

    if detener_bot_total:
        return

    data=json.loads(message)
    k=data['k']

    if not k["x"]:
        return

    candle_time=k["T"]

    if candle_time <= last_candle_time:
        return

    last_candle_time=candle_time

    candle={
        "open":float(k["o"]),
        "high":float(k["h"]),
        "low":float(k["l"]),
        "close":float(k["c"]),
        "time":candle_time
    }

    ultimo_precio = candle["close"]

    # 🔥 STOP LOSS (INSERTADO EXACTO)
    if verificar_stop_loss():
        return

    klines.append(candle)
    if len(klines)>500:
        klines.pop(0)

    if not bot_activo:
        return

    señal = calcular_senal_final()

    if not señal:
        return

    if not primera_senal_valida:
        if señal != ultima_senal_historica:
            primera_senal_valida = True
        else:
            return

    ejecutar_trade(señal, ultimo_precio)

def polling_loop():
    global klines
    global last_candle_time
    global primera_senal_valida
    global ultimo_precio
    global detener_bot_total

    print("🟢 POLLING FUTURES INICIADO", flush=True)

    while True:
        try:
            if detener_bot_total:
                time.sleep(2)
                continue

            url = (
                f"https://fapi.binance.com/fapi/v1/klines"
                f"?symbol={SYMBOL.upper()}&interval={INTERVAL}&limit=2"
            )

            response = requests.get(url, timeout=15)

            if response.status_code != 200:
                print(f"❌ HTTP ERROR: {response.status_code}", flush=True)
                time.sleep(2)
                continue

            data = response.json()

            if not isinstance(data, list) or len(data) < 2:
                print(f"❌ DATA INVALIDA: {data}", flush=True)
                time.sleep(2)
                continue

            # 🔥 IMPORTANTE:
            # usamos la vela cerrada REAL
            k = data[-2]

            candle_time = k[6]

            # evitar duplicados
            if candle_time <= last_candle_time:
                time.sleep(2)
                continue

            last_candle_time = candle_time

            candle = {
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "time": candle_time
            }

            ultimo_precio = candle["close"]

        #   print(
        #       f"📩 Nueva vela: {ultimo_precio}",
        #       flush=True
        #   )

            # 🔥 STOP LOSS
            if verificar_stop_loss():
                continue

            klines.append(candle)

            if len(klines) > 500:
                klines.pop(0)

            if not bot_activo:
                time.sleep(2)
                continue

            señal = calcular_senal_final()

            print(f"🧠 Señal: {señal}", flush=True)

            if not señal:
                time.sleep(2)
                continue

            if not primera_senal_valida:
                if señal != ultima_senal_historica:
                    primera_senal_valida = True
                else:
                    time.sleep(2)
                    continue

            ejecutar_trade(señal, ultimo_precio)

        except Exception as e:
            print(f"❌ ERROR POLLING: {e}", flush=True)

        time.sleep(2)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("🚀 BOT PERFECTO + FILTRO ACTIVADO", flush=True)

    iniciar_web()

    def run_bot():
        global ultima_senal_historica

        enviar_telegram("🤖 BOT CON FILTRO INTELIGENTE ACTIVADO")

        cargar_historico()

        ultima_senal_historica = reconstruir_estado_pine()

        # 🔥 ESTO ES LO QUE TE FALTABA
        senal_actual = calcular_senal_final()

        if senal_actual:
            ultima_senal_historica = senal_actual

        if ultima_senal_historica == "BUY":
            ultima_txt = "BUY 🔼"
            esperar = "SELL 🔽"
        elif ultima_senal_historica == "SELL":
            ultima_txt = "SELL 🔽"
            esperar = "BUY 🔼"
        else:
            ultima_txt = "None"
            esperar = "BUY 🔼 / SELL 🔽"

        enviar_telegram(
            f"📌 Última señal detectada: {ultima_txt}\n"
            f"⏳ Esperando señal {esperar} para operar..."
        )

        enviar_botones()
        iniciar_bot_telegram()

        polling_loop()

      # websocket.WebSocketApp(
      #     f"wss://fstream.binance.com/ws/{SYMBOL}@kline_{INTERVAL}",
      #     on_message=on_message
      # ).run_forever()

    threading.Thread(target=run_bot).start()
