import requests
import json
import time
import hashlib
import os
import re
from datetime import datetime

# =============================================
# 설정 (여기만 수정)
# =============================================
TELEGRAM_TOKEN = "8607870648:AAFSkkTcEv_1Iip9NULXOmOw45rEXb9dLM0"
TELEGRAM_CHAT_ID = "7786983359"

CHECK_INTERVAL = 1800  # 30분
SEEN_FILE = "seen_listings.json"

# =============================================
# API 설정
# =============================================
SEARCH_URL = "https://jeonse.lh.or.kr/jw/rs/search/reSearchRthousList.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept": "application/json, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://jeonse.lh.or.kr/jw/rs/search/selectRthousList.do?mi=2871",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

# 수도권 전체 좌표 (최대한 넓게)
PARAMS = {
    "mi": "2872",
    "recentChk": "N",
    "addrGroupChk": "Y",
    "rthousBdtyp": "9",
    "rthousRentStle": "9",
    "rthousDelngSttus": "9",
    "rthousRoomCo": "-1",
    "rthousToiletCo": "-1",
    "rthousGtnFrom": "1",
    "rthousGtnTo": "16000",
    "rthousMthtFrom": "0",
    "rthousMthtTo": "35",
    "confmdeFrom": "1900",
    "confmdeTo": "2029",
    # 수도권 전체 커버
    "northEast": "(38.3, 127.9)",
    "southWest": "(36.9, 126.1)",
}

# 필터
FILTER = {
    "priority_regions": ["서초", "강남"],
    "min_deposit": 10000,
    "max_area": 84,
    "min_area": 33,
    "exclude_basement": True,
}

# =============================================
# Telegram
# =============================================
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

# =============================================
# 크롤링
# =============================================
def fetch_listings():
    try:
        r = requests.post(SEARCH_URL, data=PARAMS, headers=HEADERS, timeout=15)
        print(f"  HTTP: {r.status_code}")

        if r.status_code != 200:
            return []

        data = r.json()

        # 실제 키: rthousList
        listings = data.get("rthousList", [])
        print(f"  rthousList: {len(listings)}건")

        # 혹시 페이징 안에 있으면
        if not listings:
            paging = data.get("rthousListPaging", {})
            listings = paging.get("list", [])
            print(f"  paging.list: {len(listings)}건")

        return listings

    except Exception as e:
        print(f"  오류: {e}")
        return []

# =============================================
# 파싱 & 필터
# =============================================
def extract_number(val):
    nums = re.findall(r'[\d,]+', str(val))
    return float(nums[0].replace(",", "")) if nums else 0

def parse_item(item):
    deposit = extract_number(item.get("rthousGtn", item.get("deposit", 0)))
    monthly = extract_number(item.get("rthousMtht", item.get("monthlyRent", 0)))
    area = extract_number(item.get("rthousSplsArea", item.get("area", 0)))
    floor = item.get("rthousFlrInfo", item.get("flrNo", "-"))
    addr = item.get("rthousAddr", item.get("rnaAddr", item.get("address", "")))

    return {
        "id": hashlib.md5((addr + str(deposit) + str(area)).encode()).hexdigest(),
        "address": addr,
        "area": area,
        "floor": str(floor),
        "deposit": deposit,
        "monthly_rent": monthly * 10000 if monthly < 1000 else monthly,
        "type": "전세" if monthly == 0 else "월세",
    }

def matches_filter(listing):
    floor = listing.get("floor", "")
    area = listing.get("area", 0)

    if FILTER["exclude_basement"]:
        if any(k in str(floor) for k in ["지하", "반지하", "B"]):
            return False

    if area and not (FILTER["min_area"] <= area <= FILTER["max_area"]):
        return False

    return True

def get_priority(listing):
    score = 0
    if any(r in listing.get("address", "") for r in FILTER["priority_regions"]):
        score += 100
    if listing.get("type") == "전세":
        score += 50
    return score

# =============================================
# 메시지
# =============================================
def format_message(listing, score):
    deposit = listing.get("deposit", 0)
    monthly = listing.get("monthly_rent", 0)
    area = listing.get("area", 0)
    pyeong = round(area / 3.3, 1) if area else "-"

    if listing.get("type") == "전세":
        price_str = f"전세 {int(deposit):,}만원"
    else:
        price_str = f"보증금 {int(deposit):,}만원 / 월 {int(monthly/10000):,}만원"

    tag = "⭐ 서초·강남" if score >= 100 else "📋 수도권"

    return f"""{tag} <b>LH 전세임대 새 매물</b>

📍 {listing.get('address', '주소 확인필요')}
📐 {area}㎡ ({pyeong}평)
🏢 {listing.get('floor', '-')}층
💰 {price_str}
🕐 {datetime.now().strftime('%m/%d %H:%M')}

🔗 <a href="https://jeonse.lh.or.kr/jw/rs/search/selectRthousList.do?mi=2871">전세임대뱅크</a>"""

# =============================================
# 상태 관리
# =============================================
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

# =============================================
# 메인
# =============================================
def main():
    print("=" * 40)
    print("LH 전세임대뱅크 알림봇")
    print("보증금 ~1.6억 / 월35만이하 / 33~84㎡")
    print(f"체크: {CHECK_INTERVAL//60}분마다")
    print("=" * 40)

    send_telegram("✅ LH 전세임대뱅크 알림봇 시작\n보증금 ~1.6억 / 월35만이하\n면적 33~84㎡ / 서초·강남 우선")

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
