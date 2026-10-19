"""TEFAS son yayımlanan fon fiyatlarını GitHub Pages için JSON'a yazar."""
import datetime as dt
import json
import math
import os
import time
from pathlib import Path
from curl_cffi import requests

CODES = {"GCN": "EMK", "GHA": "EMK", "GCT": "EMK", "YIT": "YAT", "KTJ": "YAT"}
OUT = Path("fon-fiyatlari.json")
API = "https://www.tefas.gov.tr/api/funds/fonFiyatBilgiGetir"

def parse_rows(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("resultList", "data", "result", "items"):
        part = data.get(key)
        if isinstance(part, list):
            return part
        if isinstance(part, dict):
            nested = parse_rows(part)
            if nested:
                return nested
    return []

def parse_price(value):
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        v = value.strip().replace(" ", "")
        if "," in v and "." in v:
            v = v.replace(".", "").replace(",", ".")
        elif "," in v:
            v = v.replace(",", ".")
        result = float(v)
    else:
        raise ValueError("Geçersiz fiyat")
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Fiyat sıfır/negatif")
    return result

def fetch_one(session, code):
    response = session.post(API, json={"fonKodu": code, "dil": "TR", "periyod": 1},
                            headers={"Origin": "https://www.tefas.gov.tr",
                                     "Referer": "https://www.tefas.gov.tr/"},
                            timeout=30)
    response.raise_for_status()
    if not response.content:
        raise ValueError("TEFAS boş yanıt verdi (bot koruması olabilir)")
    rows = parse_rows(response.json())
    usable = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = str(row.get("tarih") or row.get("date") or "")[:10]
        try:
            dt.date.fromisoformat(date)
            price = parse_price(row.get("fiyat", row.get("price")))
        except (ValueError, TypeError):
            continue
        usable.append((date, price))
    if not usable:
        raise ValueError("Geçerli tarihli fiyat kaydı yok")
    date, price = max(usable)
    return {"price": price, "date": date}

def fetch_gold_certificate(session):
    """Yahoo Finance BIST ALTINS1.IS son kapanış; geçersiz yanıtı kaydetme."""
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/ALTINS1.IS'
    response = session.get(url, params={'interval': '1d', 'range': '7d'},
                           headers={'Accept': 'application/json'}, timeout=30)
    response.raise_for_status()
    results = response.json().get('chart', {}).get('result') or []
    if not results:
        raise ValueError('Altın sertifikası için piyasa verisi bulunamadı')
    result = results[0]
    meta = result.get('meta') or {}
    symbol = str(meta.get('symbol', '')).upper()
    if symbol != 'ALTINS1.IS':
        raise ValueError('Beklenmeyen sembol: ' + symbol)
    currency = str(meta.get('currency', '')).upper()
    if currency != 'TRY':
        raise ValueError('Beklenmeyen para birimi: ' + currency)
    timestamps = result.get('timestamp') or []
    quotes = (result.get('indicators', {}).get('quote') or [{}])[0]
    closes = quotes.get('close') or []
    valid = [(stamp, parse_price(price)) for stamp, price in zip(timestamps, closes)
             if price is not None and isinstance(price, (int, float))
             and math.isfinite(price) and price > 0]
    if not valid:
        raise ValueError('Geçerli ALTIN.S1 kapanış fiyatı bulunamadı')
    timestamp, price = valid[-1]
    date = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date()
    if (dt.datetime.now(dt.timezone.utc).date() - date).days > 10:
        raise ValueError('ALTIN.S1 fiyatı 10 günden eski')
    return {'price': price, 'date': date.isoformat(), 'source': 'Yahoo Finance (ALTINS1.IS, kapanış)'}


def main():
    existing = {}
    if OUT.exists():
        try:
            raw = json.loads(OUT.read_text(encoding="utf-8"))
            existing = raw.get("funds", {})
        except (ValueError, OSError):
            pass
    certificates = {}
    if OUT.exists():
        try:
            certificates = raw.get('certificates', {}) if isinstance(raw, dict) else {}
        except NameError:
            pass
    session = requests.Session(impersonate="chrome")
    session.headers.update({"Accept": "application/json, text/plain, */*",
                            "User-Agent": "Mozilla/5.0"})
    try:
        session.get("https://www.tefas.gov.tr/", timeout=25)
    except Exception as exc:
        print("Ana sayfa uyarısı:", exc)
    successes = 0
    for code in CODES:
        try:
            record = fetch_one(session, code)
            existing[code] = record
            successes += 1
            print(f"{code}: {record['price']} TRY ({record['date']})")
        except Exception as exc:
            print(f"{code}: HATA: {exc}")
        time.sleep(1)
    try:
        record = fetch_gold_certificate(session)
        certificates['ALTIN.S1'] = record
        successes += 1
        print(f"ALTIN.S1: {record['price']} TRY ({record['date']})")
    except Exception as exc:
        print(f"ALTIN.S1: HATA: {exc} (eski fiyat varsa korundu)")
    if successes == 0:
        raise SystemExit("Hiçbir güncel fiyat alınamadı; eski veri üzerine yazılmadı.")
    output = {"updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
              "funds": existing, "certificates": certificates}
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Başarılı: {successes}/{len(CODES)+1}")
if __name__ == "__main__":
    main()
