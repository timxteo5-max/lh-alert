import requests
import json
import time
import hashlib
import os
import re
from datetime import datetime

TELEGRAM_TOKEN = "8607870648:AAFSkkTcEv_1Iip9NULXOmOw45rEXb9dLM0"
TELEGRAM_CHAT_ID = "7786983359"

CHECK_INTERVAL = 1800
SEEN_FILE = "seen_listings.json"

SEARCH_URL = "https://jeonse.lh.or.kr/jw/rs/search/reSearchRthousList.do"
DETAIL_URL = "https://jeonse.lh.or.kr/jw/rs/search/selectRthousDetail.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept": "application/json, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://jeonse.lh.or.kr/jw/rs/search/selectRthousList.do?mi=2871",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

PARAMS = {
    "mi": "2872",
    "recentChk": "N",
    "addrGroupChk": "Y",
    "rthousBdtyp": "9",
    "rthousRentStle": "9",
    "rthousDelngSttus": "9",
    "rthousRoomCo": "-1",
    "rthousToiletCo": "-1",
    "rthousGtnFrom": "10000",   # 보증금 1억 이상
    "rthousGtnTo": "16000",     # 보증금 1.6억 이하
    "rthousMthtFrom": "0",
    "rthousMthtTo": "35",       # 월세 35만 이하
    "rthousHpprFrom": "33",     # 공급면적 최소 33㎡
    "rthousHpprTo": "84",       # 공급면적 최대 84㎡
    "confmdeFrom": "1900",
    "confmdeTo": "2029",
    "northEast": "(38.3, 127.9)",
    "southWest": "(36.9, 126.1)",
}

FILTER = {
    "priority_regions": ["서초", "강남"],
    "min_area": 33,
    "max_area": 84,
    "exclude_basement": True,
}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"텔레그램 오류: {e}")
        return False

def fetch_listings():
    all_listings = []
    page = 1
    while True:
        try:
            params = PARAMS.copy()
            params["currPage"] = str(page)
            r = requests.post(SEARCH_URL, data=params, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()
            listings = data.get("rthousList", [])
            all_listings.extend(listings)
            paging = data.get("rthousListPaging", {})
            total_page = paging.get("totalPage", 1)
            print(f"  페이지 {page}/{total_page}: {len(listings)}건")
            if page >= total_page:
                break
            page += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"  오류: {e}")
            break
    return all_listings

def parse_item(item):
    # 실제 필드명 기반
    area = float(item.get("rthousExclAr", 0) or 0)       # 전용면적
    supply_area = float(item.get("rthousHppr", 0) or 0)   # 공급면적
    floor = item.get("rthousFloor", "-")                    # 층수 (-1=지하)
    deposit = float(item.get("rthousGtn", 0) or 0)         # 보증금(만원)
    monthly = float(item.get("rthousMtht", 0) or 0)        # 월세(만원)
    rent_type = item.get("rthousRentStle", "")              # 1=전세 2=월세 3=반전세
    name = item.get("rthousNm", "")
    rtid = item.get("rthousId", "")
    reg_date = item.get("rthousRgsde", "")
    broker = item.get("brkrNm", "")
    manage_fee = item.get("rthousManagect", 0)

    if rent_type == "1":
        type_str = "전세"
    elif rent_type == "3":
        type_str = "반전세"
    else:
        type_str = "월세"

    # 상세 링크
    detail_link = f"https://jeonse.lh.or.kr/jw/rs/search/selectRthousDetail.do?rthousId={rtid}&mi=2873" if rtid else ""

    return {
        "id": rtid or hashlib.md5((name + str(deposit)).encode()).hexdigest(),
        "name": name,
        "area": area,
        "supply_area": supply_area,
        "floor": str(floor),
        "deposit": deposit,
        "monthly_rent": monthly,
        "type": type_str,
        "reg_date": reg_date,
        "broker": broker,
        "manage_fee": manage_fee,
        "detail_link": detail_link,
    }

def matches_filter(listing):
    floor_val = listing.get("floor", "0")
    area = listing.get("area", 0)

    # 지하 제외
    if FILTER["exclude_basement"]:
        try:
            if int(floor_val) < 1:
                return False
        except:
            if any(k in str(floor_val) for k in ["지하", "B", "-"]):
                return False

    # 면적
    if area and not (FILTER["min_area"] <= area <= FILTER["max_area"]):
        return False

    return True

def get_priority(listing):
    score = 0
    name = listing.get("name", "")
    if any(r in name for r in FILTER["priority_regions"]):
        score += 100
    if listing.get("type") == "전세":
        score += 50
    elif listing.get("type") == "반전세":
        score += 25
    area = listing.get("area", 0)
    if 40 <= area <= 70:
        score += 20
    return score

def format_message(listing, score):
    deposit = listing.get("deposit", 0)
    monthly = listing.get("monthly_rent", 0)
    area = listing.get("area", 0)
    supply = listing.get("supply_area", 0)
    floor = listing.get("floor", "-")
    ltype = listing.get("type", "")
    manage = listing.get("manage_fee", 0)
    reg_date = listing.get("reg_date", "")
    broker = listing.get("broker", "")
    link = listing.get("detail_link", "https://jeonse.lh.or.kr/jw/rs/search/selectRthousList.do?mi=2871")

    pyeong = round(area / 3.3, 1) if area else "-"
    supply_py = round(supply / 3.3, 1) if supply else "-"

    if ltype == "전세":
        price_str = f"전세 {int(deposit):,}만원"
    elif ltype == "반전세":
        price_str = f"반전세 {int(deposit):,}만원 / 월 {int(monthly):,}만원"
    else:
        price_str = f"보증금 {int(deposit):,}만원 / 월 {int(monthly):,}만원"

    manage_str = f" (관리비 {manage}만)" if manage else ""
    tag = "⭐ 서초·강남" if score >= 100 else "📋 수도권"

    return f"""{tag} <b>LH 전세임대 새 매물</b>

🏠 {listing.get('name', '')}
💰 {price_str}{manage_str}
📐 전용 {area}㎡({pyeong}평) / 공급 {supply}㎡({supply_py}평)
🏢 {floor}층
📅 등록: {reg_date}
🏪 {broker}
🕐 발견: {datetime.now().strftime('%m/%d %H:%M')}

🔗 <a href="{link}">상세보기</a>"""

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def main():
    print("=" * 40)
    print("LH 전세임대뱅크 알림봇")
    print("보증금 1억~1.6억 / 월35만이하 / 33~84㎡")
    print(f"체크: {CHECK_INTERVAL//60}분마다")
    print("=" * 40)

    send_telegram("✅ LH 전세임대뱅크 알림봇 시작\n보증금 1억~1.6억 / 월35만이하\n면적 33~84㎡ / 서초·강남 우선\n상세보기 링크 포함")

    seen = load_seen()

    while True:
        print(f"\n[{datetime.now().strftime('%H:%M')}] 매물 확인 중...")
        raw_listings = fetch_listings()
        matched = []

        for raw in raw_listings:
            listing = parse_item(raw)
            lid = listing["id"]
            if lid not in seen and matches_filter(listing):
                score = get_priority(listing)
                matched.append((score, lid, listing))
                seen.add(lid)

        matched.sort(key=lambda x: x[0], reverse=True)
        for score, lid, listing in matched:
            send_telegram(format_message(listing, score))
            time.sleep(1)

        save_seen(seen)
        print(f"  신규: {len(matched)}건 / 전체: {len(raw_listings)}건")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
