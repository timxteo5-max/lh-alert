import requests
import json
import time
import hashlib
import os
import re
import math
from datetime import datetime
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = "8607870648:AAFSkkTcEv_1Iip9NULXOmOw45rEXb9dLM0"
TELEGRAM_CHAT_ID = "7786983359"
SHEETS_URL = "https://script.google.com/macros/s/AKfycbyAARmIZWNQ54WSRNWGe8rlR-45h1dd9wapo1NpyHHTc4vML_EcJTXmq40PIT4Rtygh/exec"

CHECK_INTERVAL = 1800
SEEN_FILE = "seen_listings.json"

NAEBANG_LAT = 37.4969
NAEBANG_LNG = 126.9810

SUBWAY_LINES = {
    "7호선": ["내방", "이수", "사당", "남성", "숭실대입구", "상도", "장승배기",
              "신대방삼거리", "보라매", "신풍", "대림", "구로디지털단지", "철산",
              "광명사거리", "온수", "군자", "어린이대공원", "건대입구", "뚝섬유원지",
              "청담", "강남구청", "학동", "논현", "반포", "고속터미널"],
    "2호선": ["사당", "방배", "서초", "교대", "강남", "역삼", "선릉", "삼성",
              "종합운동장", "잠실새내", "잠실", "건대입구", "뚝섬", "성수", "왕십리"],
    "5호선": ["군자", "아차산", "광나루", "천호", "강동", "마천", "방화"],
}

SEARCH_URL = "https://jeonse.lh.or.kr/jw/rs/search/reSearchRthousList.do"
DETAIL_URL = "https://jeonse.lh.or.kr/jw/rs/search/selectRthousInfo.do"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
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
    "rthousGtnFrom": "10000",
    "rthousGtnTo": "16000",
    "rthousMthtFrom": "0",
    "rthousMthtTo": "35",
    "rthousHpprFrom": "33",
    "rthousHpprTo": "84",
    "confmdeFrom": "1900",
    "confmdeTo": "2029",
    "northEast": "(38.3, 127.9)",
    "southWest": "(36.9, 126.1)",
}

def safe_float(val):
    try:
        m = re.search(r'\d+\.?\d*', str(val))
        return float(m.group()) if m else 0.0
    except:
        return 0.0

def calc_distance(lat1, lng1, lat2, lng2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def distance_label(meters):
    mins = round(meters / 67)
    if meters < 1000:
        return f"{int(meters)}m (도보 {mins}분)"
    return f"{meters/1000:.1f}km (도보 {mins}분)"

def detect_subway(text):
    found = []
    for line, stations in SUBWAY_LINES.items():
        for st in stations:
            if st in text:
                found.append(f"{line} {st}역")
                break
    return ", ".join(found) if found else ""

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

def send_to_sheets(data):
    try:
        r = requests.post(SHEETS_URL, json=data, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"시트 오류: {e}")
        return False

def fetch_detail(rtid):
    try:
        params = {"rthousId": rtid, "mi": "2873"}
        r = requests.post(DETAIL_URL, data=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, "html.parser")
        result = {}
        rows = soup.select("table tr")
        for row in rows:
            cells = row.find_all(["th", "td"])
            for i, cell in enumerate(cells):
                label = cell.get_text(strip=True)
                if i + 1 < len(cells):
                    val = cells[i+1].get_text(strip=True)
                    if "매물주소" in label:
                        result["addr"] = val
                    elif "관리비" in label:
                        result["manage"] = val
                    elif "방향" in label:
                        result["direction"] = val
                    elif "입주" in label:
                        result["move_in"] = val
                    elif "사용승인" in label:
                        result["approved"] = val
                    elif "주차" in label:
                        result["parking"] = val
                    elif "방/화장실" in label:
                        result["rooms"] = val
                    elif "건물" in label and "동" in label:
                        result["building_dong"] = val
                    elif "건축물" in label and "용도" in label:
                        result["building_use"] = val
        options = []
        for opt in soup.select(".option-item, .opt-item, li.opt, .opt_list li"):
            txt = opt.get_text(strip=True)
            if txt:
                options.append(txt)
        if options:
            result["options"] = ", ".join(options)
        contact_rows = soup.select("table tr")
        for row in contact_rows:
            cells = row.find_all(["th", "td"])
            for i, cell in enumerate(cells):
                label = cell.get_text(strip=True)
                if i + 1 < len(cells):
                    val = cells[i+1].get_text(strip=True)
                    if "이름" in label:
                        result["contact_name"] = val
                    elif "휴대폰" in label:
                        result["mobile"] = val
                    elif "전화번호" in label:
                        result["phone"] = val
        if not result.get("mobile"):
            phones = re.findall(r'0\d{1,2}-?\d{3,4}-?\d{4}', r.text)
            if phones:
                result["mobile"] = phones[0]
                if len(phones) > 1:
                    result["phone"] = phones[1]
        if not result.get("addr"):
            addr_match = re.search(r'서울[^\s<]{5,30}|경기[^\s<]{5,30}|인천[^\s<]{5,30}', r.text)
            if addr_match:
                result["addr"] = addr_match.group()
        return result
    except Exception as e:
        print(f"  상세 오류: {e}")
        return {}

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
    area = safe_float(item.get("rthousExclAr", 0))
    supply_area = safe_float(item.get("rthousHppr", 0))
    floor = item.get("rthousFloor", "-")
    all_floor = item.get("rthousAllFloor", "-")
    deposit = safe_float(item.get("rthousGtn", 0))
    monthly = safe_float(item.get("rthousMtht", 0))
    rent_type = item.get("rthousRentStle", "")
    name = item.get("rthousNm", "")
    rtid = item.get("rthousId", "")
    reg_date = item.get("rthousRgsde", "")
    broker = item.get("brkrNm", "")
    manage_fee = safe_float(item.get("rthousManagect", 0))
    desc = item.get("rthousSumryDc", "") + " " + item.get("rthousSumryKwrd", "")
    lat = safe_float(item.get("rthousYdnts", 0))
    lng = safe_float(item.get("rthousXcnts", 0))

    if rent_type == "1":
        type_str = "전세"
    elif rent_type == "3":
        type_str = "반전세"
    else:
        type_str = "월세"

    dist = calc_distance(NAEBANG_LAT, NAEBANG_LNG, lat, lng) if lat and lng else 0
    subway = detect_subway(name + " " + desc)

    return {
        "id": rtid or hashlib.md5((name + str(deposit)).encode()).hexdigest(),
        "rtid": rtid,
        "name": name,
        "area": area,
        "supply_area": supply_area,
        "floor": str(floor),
        "all_floor": str(all_floor),
        "deposit": deposit,
        "monthly_rent": monthly,
        "manage_fee": manage_fee,
        "type": type_str,
        "reg_date": reg_date,
        "broker": broker,
        "desc": desc.strip(),
        "subway": subway,
        "dist_naebang": dist,
        "detail_link": f"https://jeonse.lh.or.kr/jw/rs/search/selectRthousInfo.do?rthousId={rtid}&mi=2873" if rtid else "",
        "found_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

def matches_filter(listing):
    floor_val = listing.get("floor", "0")
    area = listing.get("area", 0)
    try:
        if int(floor_val) < 1:
            return False
    except:
        if any(k in str(floor_val) for k in ["지하", "B"]):
            return False
    if area and not (33 <= area <= 84):
        return False
    return True

def get_priority(listing):
    score = 0
    name = listing.get("name", "")
    if any(k in name for k in ["서초", "강남", "방배", "양재", "내방", "이수", "사당", "군자"]):
        score += 100
    if listing.get("type") == "전세":
        score += 50
    elif listing.get("type") == "반전세":
        score += 25
    if listing.get("subway"):
        score += 30
    dist = listing.get("dist_naebang", 99999)
    if dist < 1000:
        score += 50
    elif dist < 3000:
        score += 20
    return score

def format_message(listing, score, detail):
    deposit = listing.get("deposit", 0)
    monthly = listing.get("monthly_rent", 0)
    area = listing.get("area", 0)
    supply = listing.get("supply_area", 0)
    floor = listing.get("floor", "-")
    all_floor = listing.get("all_floor", "-")
    ltype = listing.get("type", "")
    manage = listing.get("manage_fee", 0)
    reg_date = listing.get("reg_date", "")
    broker = listing.get("broker", "")
    subway = listing.get("subway", "")
    dist = listing.get("dist_naebang", 0)
    link = listing.get("detail_link", "")

    addr = detail.get("addr", "")
    mobile = detail.get("mobile", "")
    phone = detail.get("phone", "")
    contact_name = detail.get("contact_name", "")
    direction = detail.get("direction", "")
    move_in = detail.get("move_in", "")
    rooms = detail.get("rooms", "")
    parking = detail.get("parking", "")
    options = detail.get("options", "")
    manage_detail = detail.get("manage", "")

    pyeong = round(area / 3.3, 1) if area else "-"
    supply_py = round(supply / 3.3, 1) if supply else "-"
    dist_str = distance_label(dist) if dist else "-"

    if ltype == "전세":
        price_str = f"전세 {int(deposit):,}만원"
    elif ltype == "반전세":
        price_str = f"반전세 {int(deposit):,}만원 / 월 {int(monthly):,}만원"
    else:
        price_str = f"보증금 {int(deposit):,}만원 / 월 {int(monthly):,}만원"

    manage_str = manage_detail or (f"{int(manage)}만원" if manage else "없음")
    tag = "⭐ 우선매물" if score >= 100 else "📋 수도권"
    subway_str = f"\n🚇 {subway}" if subway else ""
    phone_str = ""
    if contact_name:
        phone_str += f"\n👤 담당: {contact_name}"
    if mobile:
        phone_str += f"\n📱 {mobile}"
    if phone:
        phone_str += f"\n☎️ {phone}"
    if not phone_str:
        phone_str = "\n📞 연락처: 상세페이지 확인"
    options_str = f"\n🔧 {options}" if options else ""
    direction_str = f" {direction}" if direction else ""
    move_in_str = f"\n📆 입주: {move_in}" if move_in else ""
    rooms_str = f" | 방/화장실 {rooms}" if rooms else ""
    parking_str = f"\n🚗 주차: {parking}" if parking else ""
    naver = f"https://map.naver.com/v5/search/{addr.replace(' ', '+')}" if addr else ""

    return f"""{tag} <b>LH 전세임대 새 매물</b>

🏠 {listing.get('name', '')}
📍 {addr}
💰 {price_str}
🧾 관리비: {manage_str}
📐 전용 {area}㎡({pyeong}평) / 공급 {supply}㎡({supply_py}평){rooms_str}
🏢 {all_floor}층 건물 / {floor}층{direction_str}{subway_str}
📏 내방역 {dist_str}{move_in_str}{parking_str}{options_str}
📅 등록: {reg_date}
🏪 {broker}{phone_str}
🕐 {datetime.now().strftime('%m/%d %H:%M')}

🔗 <a href="{link}">LH 상세보기</a>{"  🗺 <a href='" + naver + "'>네이버지도</a>" if naver else ""}"""

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)

def main():
    print("=" * 40)
    print("LH 전세임대뱅크 알림봇 완성판")
    print("텔레그램 + 구글시트 자동기록")
    print(f"체크: {CHECK_INTERVAL//60}분마다")
    print("=" * 40)

    send_telegram("✅ LH 전세임대뱅크 알림봇 시작\n상세정보+연락처+네이버지도+구글시트 자동기록")

    seen = load_seen()

    while True:
        print(f"\n[{datetime.now().strftime('%H:%M')}] 매물 확인 중...")
        raw_listings = fetch_listings()
        matched = []

        for raw in raw_listings:
            try:
                listing = parse_item(raw)
                lid = listing["id"]
                if lid not in seen and matches_filter(listing):
                    score = get_priority(listing)
                    matched.append((score, lid, listing))
                    seen.add(lid)
            except Exception as e:
                print(f"  파싱 오류: {e}")
                continue

        matched.sort(key=lambda x: x[0], reverse=True)

        for score, lid, listing in matched:
            print(f"  → {listing.get('name', '')}")
            detail = fetch_detail(listing.get("rtid", ""))
            time.sleep(0.5)

            # 텔레그램 발송
            send_telegram(format_message(listing, score, detail))

            # 구글 시트 기록
            sheet_data = {**listing, **detail}
            send_to_sheets(sheet_data)

            time.sleep(1)

        save_seen(seen)
        print(f"  신규: {len(matched)}건 / 전체: {len(raw_listings)}건")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
