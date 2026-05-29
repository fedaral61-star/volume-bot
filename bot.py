import asyncio
import aiohttp

# ------------------ TELEGRAM BİLGİLERİ ------------------
TELEGRAM_TOKEN = "8580210563:AAEu_vyoA_CiDtAxucXFG9GDy0Tu8kooQr8"
CHAT_ID = "1788929771"
# -------------------------------------------------------

INTERVAL = "1m"
MUM_SAYISI = 10
HACIM_FACTOR = 2
MIN_VOLUME_USDT = 100_000
SLEEP_TIME = 20  # 20 saniyede bir tarama

# Cloudflare engelini aşmak için gerçek bir tarayıcı kimliği (User-Agent) ekledik
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Railway IP engellerine karşı Binance'in yedek sunucu adresleri
BINANCE_URLS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com"
]

CURRENT_BASE_URL = BINANCE_URLS[0]

async def send_telegram(session, message):
    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    for _ in range(3):  # 3 deneme
        try:
            async with session.get(
                url,
                params={
                    "chat_id": CHAT_ID,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": "true"
                },
                timeout=10
            ) as r:
                if r.status == 200:
                    return
                else:
                    print("Telegram gönderim hatası:", await r.text())
        except Exception as e:
            print("Telegram exception:", e)
        await asyncio.sleep(2)

async def get_futures_symbols(session):
    global CURRENT_BASE_URL
    # Sırasıyla tüm yedek sunucuları dener
    for base_url in BINANCE_URLS:
        url = f"{base_url}/fapi/v1/exchangeInfo"
        try:
            async with session.get(url, headers=HEADERS, timeout=10) as res:
                if res.status != 200:
                    continue
                data = await res.json()
                if "symbols" in data:
                    CURRENT_BASE_URL = base_url  # Çalışan sunucuyu hafızaya al
                    return [
                        s["symbol"]
                        for s in data["symbols"]
                        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
                    ]
        except Exception:
            continue
    print("Mevcut tüm Binance yedek sunucuları engellendi veya yanıt vermiyor.")
    return []

async def get_klines(session, symbol, limit):
    url = f"{CURRENT_BASE_URL}/fapi/v1/klines?symbol={symbol}&interval={INTERVAL}&limit={limit}"
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as res:
            if res.status == 200:
                return await res.json()
            return []
    except Exception as e:
        print(f"{symbol} klines alınamadı:", e)
        return []

async def get_24h_volume(session, symbol):
    url = f"{CURRENT_BASE_URL}/fapi/v1/ticker/24hr?symbol={symbol}"
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as res:
            if res.status == 200:
                data = await res.json()
                return float(data.get("quoteVolume", 0.0))
            return 0.0
    except Exception as e:
        print(f"{symbol} 24h volume alınamadı:", e)
        return 0.0

async def check_volume_spike(session, symbol):
    klines = await get_klines(session, symbol, MUM_SAYISI)
    if not klines or len(klines) < MUM_SAYISI:
        return None

    try:
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        volumes_usdt = [volumes[i] * closes[i] for i in range(len(volumes))]

        avg_volume_usdt = sum(volumes_usdt[:-1]) / (len(volumes_usdt) - 1)
        last_volume_usdt = volumes_usdt[-1]

        prev_close = closes[-2]
        current_close = closes[-1]
        price_change_pct = ((current_close - prev_close) / prev_close) * 100
        price_trend = "🟢" if price_change_pct > 0 else "🔴"

        if (
            last_volume_usdt >= avg_volume_usdt * HACIM_FACTOR
            and last_volume_usdt >= MIN_VOLUME_USDT
            and abs(price_change_pct) >= 0.40
        ):
            return last_volume_usdt, avg_volume_usdt, price_change_pct, price_trend
    except Exception:
        pass

    return None

async def monitor_coin(session, symbol):
    try:
        result = await check_volume_spike(session, symbol)
        if not result:
            return

        last_vol, avg_vol, price_pct, trend = result
        vol_24h = await get_24h_volume(session, symbol)

        msg = (
            f"*📊 {symbol} Hacim Spike!*\n\n"
            f"📈 Son Mum Hacmi: {last_vol:,.2f} USDT\n"
            f"📉 Ortalama Hacim: {avg_vol:,.2f} USDT\n"
            f"🔥 Oran: {last_vol/avg_vol:.2f}x\n\n"
            f"💰 Son Mum Fiyat Değişimi: {price_pct:.2f}% {trend}\n\n"
            f"📦 24 Saatlik Hacim: {vol_24h:,.2f} USDT\n\n"
            f"[📈 Grafiğe Git](https://binance.com{symbol})"
        )

        await send_telegram(session, msg)
    except Exception as e:
        print(f"{symbol} hata:", e)

async def main():
    print("USDT Futures 1m HACİM SPIKE botu çalışıyor...")
    resolver = aiohttp.AsyncResolver(nameservers=['8.8.8.8', '8.8.4.4'])  # Google DNS
    conn = aiohttp.TCPConnector(resolver=resolver, ssl=False)

    async with aiohttp.ClientSession(connector=conn) as session:
        while True:
            symbols = await get_futures_symbols(session)
            if not symbols:
                print("Sembol yok, bekleniyor...")
                await asyncio.sleep(10)
                continue

            print(f"Toplam {len(symbols)} sembol başarıyla alındı. Tarama başlıyor...")
            tasks = [monitor_coin(session, s) for s in symbols]
            await asyncio.gather(*tasks, return_exceptions=True)

            await asyncio.sleep(SLEEP_TIME)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print("Bot hata verdi:", e)
