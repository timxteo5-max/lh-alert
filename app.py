from flask import Flask, jsonify, request
import requests
import re
import math
import threading
import json
import os
import time
import hashlib
from datetime import datetime
from bs4 import BeautifulSoup

app = Flask(__name__)

TELEGRAM_TOKEN = "여기에_새_토큰_입력"
TELEGRAM_CHAT_ID = "여기에_채팅ID_입력"
SHEETS_URL = "https://script.google.com/macros/s/AKfycbyAARmIZWNQ54WSRNWGe8rlR-45h1dd9wapo1NpyHHTc4vML_EcJTXmq40PIT4Rtygh/exec"
CHECK_INTERVAL = 1800
SEEN_FILE = "seen_listings.json"
NAEBANG_LAT = 37.4969
NAEBANG_LNG = 126.9810

SUBWAY_LINES = {
    "7호선": ["내방","이수","사당","남성","숭실대입구","상도","장승배기","신대방삼거리","보라매","신풍","대림","구로디지털단지","철산","광명사거리","온수","군자","어린이대공원","건대입구"],
    "2호선": ["사당","방배","서초","교대","강남","역삼","선릉","삼성","종합운동장","잠실새내","잠실","건대입구","뚝섬","성수","왕십리"],
    "5호선": ["군자","아차산","광나루","천호","강동"],
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
    "mi": "2872", "recentChk": "N", "addrGroupChk": "Y",
    "rthousBdtyp": "9", "rthousRentStle": "9", "rthousDelngSttus": "9",
    "rthousRoomCo": "-1", "rthousToiletCo": "-1",
    "rthousGtnFrom": "10000", "rthousGtnTo": "16000",
    "rthousMthtFrom": "0", "rthousMthtTo": "35",
    "rthousHpprFrom": "33", "rthousHpprTo": "84",
    "confmdeFrom": "1900", "confmdeTo": "2029",
    "northEast": "(38.3, 127.9)", "southWest": "(36.9, 126.1)",
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
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lng2-lng1)/2)**2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def detect_subway(text):
    found = []
    for line, stations in SUBWAY_LINES.items():
        for st in stations:
            if st in text:
                found.append(f"{line} {st}역")
                break
    return ", ".join(found) if found else ""

def fetch_detail(rtid):
    try:
        r = requests.post(DETAIL_URL, data={"rthousId": rtid, "mi": "2873"}, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        result = {}
        for row in soup.select("table tr"):
            cells = row.find_all(["th","td"])
            for i, cell in enumerate(cells):
                label = cell.get_text(strip=True)
                if i+1 < len(cells):
                    val = cells[i+1].get_text(strip=True)
                    if "매물주소" in label: result["addr"] = val
                    elif "관리비" in label: result["manage"] = val
                    elif "방향" in label: result["direction"] = val
                    elif "입주" in label: result["move_in"] = val
                    elif "주차" in label: result["parking"] = val
                    elif "방/화장실" in label: result["rooms"] = val
                    elif "이름" in label: result["contact_name"] = val
                    elif "휴대폰" in label: result["mobile"] = val
                    elif "전화번호" in label: result["phone"] = val
                    elif "사용승인" in label: result["approved"] = val
                    elif "건축물" in label and "용도" in label: result["building_use"] = val
        # LH 가능 여부
        lh_ok = "LH가능" in r.text or "LH 가능" in r.text or "lh가능" in r.text.lower()
        result["lh_ok"] = "가능" if lh_ok else "확인필요"
        # 협의 가능 여부
        nego = "협의" in r.text
        result["nego"] = "협의가능" if nego else "-"
        # 옵션
        opts = []
        for o in soup.select(".opt_list span, .option span, td.opt"):
            t = o.get_text(strip=True)
            if t: opts.append(t)
        result["options"] = ", ".join(opts) if opts else ""
        # 상세설명
        desc_el = soup.select_one(".detail_cont, .desc_cont, #descCont")
        result["desc"] = desc_el.get_text(strip=True) if desc_el else ""
        # 전화번호 fallback
        if not result.get("mobile"):
            phones = re.findall(r'0\d{1,2}-?\d{3,4}-?\d{4}', r.text)
            if phones: result["mobile"] = phones[0]
            if len(phones) > 1: result["phone"] = phones[1]
        if not result.get("addr"):
            m = re.search(r'서울[^\s<]{5,30}|경기[^\s<]{5,30}|인천[^\s<]{5,30}', r.text)
            if m: result["addr"] = m.group()
        return result
    except Exception as e:
        return {}

def fetch_all_listings():
    all_listings = []
    page = 1
    while True:
        try:
            params = PARAMS.copy()
            params["currPage"] = str(page)
            r = requests.post(SEARCH_URL, data=params, headers=HEADERS, timeout=15)
            data = r.json()
            listings = data.get("rthousList", [])
            all_listings.extend(listings)
            paging = data.get("rthousListPaging", {})
            total_page = paging.get("totalPage", 1)
            if page >= total_page: break
            page += 1
            time.sleep(0.3)
        except:
            break
    return all_listings

def parse_listing(item):
    area = safe_float(item.get("rthousExclAr", 0))
    supply = safe_float(item.get("rthousHppr", 0))
    floor = item.get("rthousFloor", "-")
    all_floor = item.get("rthousAllFloor", "-")
    deposit = safe_float(item.get("rthousGtn", 0))
    monthly = safe_float(item.get("rthousMtht", 0))
    rent_type = item.get("rthousRentStle", "")
    name = item.get("rthousNm", "")
    rtid = item.get("rthousId", "")
    reg_date = item.get("rthousRgsde", "")
    broker = item.get("brkrNm", "")
    manage = safe_float(item.get("rthousManagect", 0))
    desc = item.get("rthousSumryDc","") + " " + item.get("rthousSumryKwrd","")
    lat = safe_float(item.get("rthousYdnts", 0))
    lng = safe_float(item.get("rthousXcnts", 0))
    type_str = {"1":"전세","3":"반전세"}.get(rent_type, "월세")
    dist = calc_distance(NAEBANG_LAT, NAEBANG_LNG, lat, lng) if lat and lng else 0
    subway = detect_subway(name + " " + desc)
    try:
        floor_int = int(floor)
    except:
        floor_int = 0
    return {
        "id": rtid or hashlib.md5((name+str(deposit)).encode()).hexdigest(),
        "rtid": rtid,
        "name": name,
        "area": area,
        "supply_area": supply,
        "floor": str(floor),
        "floor_int": floor_int,
        "all_floor": str(all_floor),
        "deposit": deposit,
        "monthly_rent": monthly,
        "manage_fee": manage,
        "type": type_str,
        "reg_date": reg_date,
        "broker": broker,
        "desc": desc.strip(),
        "subway": subway,
        "dist_naebang": dist,
        "detail_link": f"https://jeonse.lh.or.kr/jw/rs/search/selectRthousInfo.do?rthousId={rtid}&mi=2873",
        "found_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

# 캐시
_cache = {"listings": [], "updated": ""}

def refresh_cache():
    raw = fetch_all_listings()
    parsed = []
    for item in raw:
        try:
            p = parse_listing(item)
            if p["floor_int"] >= 1 and (33 <= p["area"] <= 84 or p["area"] == 0):
                parsed.append(p)
        except:
            continue
    _cache["listings"] = parsed
    _cache["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =============================================
# 웹 대시보드
# =============================================
@app.route("/")
def dashboard():
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LH 전세임대 대시보드</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Noto Sans KR',sans-serif;background:#0f1117;color:#e2e8f0;min-height:100vh}
.header{background:#1a1f2e;border-bottom:1px solid #2d3748;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.logo{font-size:18px;font-weight:700;color:#63b3ed}
.updated{font-size:12px;color:#718096}
.filters{background:#1a1f2e;border-bottom:1px solid #2d3748;padding:16px 24px;display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end}
.filter-group{display:flex;flex-direction:column;gap:4px}
.filter-group label{font-size:11px;color:#718096;font-weight:500}
select,input{background:#2d3748;border:1px solid #4a5568;color:#e2e8f0;padding:6px 10px;border-radius:6px;font-size:13px;font-family:inherit}
.btn{background:#3182ce;color:white;border:none;padding:7px 16px;border-radius:6px;cursor:pointer;font-size:13px;font-family:inherit;font-weight:500}
.btn:hover{background:#2b6cb0}
.btn-reset{background:#4a5568}
.btn-reset:hover{background:#2d3748}
.stats{padding:12px 24px;display:flex;gap:16px;font-size:13px;color:#718096}
.stat-num{color:#63b3ed;font-weight:700}
.grid{padding:16px 24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.card{background:#1a1f2e;border:1px solid #2d3748;border-radius:12px;padding:16px;cursor:pointer;transition:all .2s}
.card:hover{border-color:#3182ce;transform:translateY(-2px)}
.card.priority{border-color:#d69e2e}
.card-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px}
.card-name{font-weight:600;font-size:14px;line-height:1.4;flex:1;margin-right:8px}
.tag{font-size:11px;padding:2px 8px;border-radius:20px;white-space:nowrap}
.tag-jeonse{background:#1a365d;color:#63b3ed}
.tag-wolse{background:#1a202c;color:#fc8181}
.tag-ban{background:#1c2a1a;color:#68d391}
.tag-priority{background:#744210;color:#f6e05e}
.price{font-size:16px;font-weight:700;color:#f6e05e;margin-bottom:8px}
.info-row{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:6px}
.info-item{font-size:12px;color:#a0aec0;display:flex;align-items:center;gap:4px}
.info-item strong{color:#e2e8f0}
.subway{font-size:12px;color:#68d391;margin-top:4px}
.dist{font-size:12px;color:#fc8181}
.broker{font-size:12px;color:#718096;margin-top:8px;border-top:1px solid #2d3748;padding-top:8px}
.lh-ok{color:#68d391;font-weight:600}
.nego{color:#f6ad55}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;justify-content:center;align-items:flex-start;overflow-y:auto;padding:20px}
.modal.open{display:flex}
.modal-content{background:#1a1f2e;border:1px solid #2d3748;border-radius:16px;padding:24px;max-width:600px;width:100%;margin:auto;position:relative}
.modal-close{position:absolute;top:16px;right:16px;background:none;border:none;color:#718096;font-size:20px;cursor:pointer}
.modal-title{font-size:18px;font-weight:700;margin-bottom:16px;color:#63b3ed}
.modal-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px}
.modal-item{background:#2d3748;border-radius:8px;padding:10px}
.modal-item label{font-size:11px;color:#718096;display:block;margin-bottom:2px}
.modal-item span{font-size:13px;color:#e2e8f0;font-weight:500}
.modal-links{display:flex;gap:8px;margin-top:12px}
.modal-links a{background:#2d3748;color:#63b3ed;padding:8px 16px;border-radius:8px;text-decoration:none;font-size:13px;flex:1;text-align:center}
.modal-links a:hover{background:#3182ce;color:white}
.loading{text-align:center;padding:60px;color:#718096}
.empty{text-align:center;padding:60px;color:#718096}
</style>
</head>
<body>
<div class="header">
  <div class="logo">🏠 LH 전세임대 대시보드</div>
  <div class="updated" id="updated">로딩 중...</div>
</div>

<div class="filters">
  <div class="filter-group">
    <label>거래유형</label>
    <select id="f-type">
      <option value="">전체</option>
      <option value="전세">전세</option>
      <option value="반전세">반전세</option>
      <option value="월세">월세</option>
    </select>
  </div>
  <div class="filter-group">
    <label>오늘 매물만</label>
    <select id="f-today">
      <option value="">전체</option>
      <option value="today">오늘만</option>
    </select>
  </div>
  <div class="filter-group">
    <label>LH 가능</label>
    <select id="f-lh">
      <option value="">전체</option>
      <option value="가능">가능만</option>
    </select>
  </div>
  <div class="filter-group">
    <label>협의 가능</label>
    <select id="f-nego">
      <option value="">전체</option>
      <option value="협의가능">협의가능만</option>
    </select>
  </div>
  <div class="filter-group">
    <label>층수</label>
    <select id="f-floor">
      <option value="">전체</option>
      <option value="1">1층</option>
      <option value="2">2층</option>
      <option value="3">3층 이상</option>
    </select>
  </div>
  <div class="filter-group">
    <label>지역</label>
    <select id="f-area">
      <option value="">전체</option>
      <option value="서초">서초구</option>
      <option value="강남">강남구</option>
      <option value="방배">방배동</option>
      <option value="군자">군자</option>
      <option value="광진">광진구</option>
    </select>
  </div>
  <div class="filter-group">
    <label>보증금 최대(만원)</label>
    <input type="number" id="f-deposit" placeholder="예: 13000" style="width:120px">
  </div>
  <div class="filter-group">
    <label>지하철노선</label>
    <select id="f-subway">
      <option value="">전체</option>
      <option value="7호선">7호선</option>
      <option value="2호선">2호선</option>
      <option value="5호선">5호선</option>
    </select>
  </div>
  <button class="btn" onclick="applyFilter()">검색</button>
  <button class="btn btn-reset" onclick="resetFilter()">초기화</button>
  <button class="btn" onclick="loadListings()" style="background:#2f855a">🔄 새로고침</button>
</div>

<div class="stats" id="stats">매물 로딩 중...</div>

<div class="grid" id="grid">
  <div class="loading">매물을 불러오는 중...</div>
</div>

<div class="modal" id="modal" onclick="closeModal(event)">
  <div class="modal-content">
    <button class="modal-close" onclick="document.getElementById('modal').classList.remove('open')">✕</button>
    <div id="modal-body"></div>
  </div>
</div>

<script>
let allData = [];
let detailCache = {};
const today = new Date().toISOString().slice(0,10).replace(/-/g,".");

async function loadListings() {
  document.getElementById("grid").innerHTML = '<div class="loading">매물 불러오는 중...</div>';
  try {
    const res = await fetch("/api/listings");
    const data = await res.json();
    allData = data.listings;
    document.getElementById("updated").textContent = "업데이트: " + data.updated;
    applyFilter();
  } catch(e) {
    document.getElementById("grid").innerHTML = '<div class="empty">불러오기 실패. 새로고침 해주세요.</div>';
  }
}

function applyFilter() {
  const type = document.getElementById("f-type").value;
  const todayOnly = document.getElementById("f-today").value;
  const lh = document.getElementById("f-lh").value;
  const nego = document.getElementById("f-nego").value;
  const floor = document.getElementById("f-floor").value;
  const area = document.getElementById("f-area").value;
  const deposit = parseFloat(document.getElementById("f-deposit").value) || 0;
  const subway = document.getElementById("f-subway").value;

  let filtered = allData.filter(d => {
    if (type && d.type !== type) return false;
    if (todayOnly && !d.reg_date.startsWith(today.slice(0,7).replace(".","-").replace(".","-"))) {
      if (d.reg_date !== today) return false;
    }
    if (lh && d.lh_ok !== lh) return false;
    if (nego && d.nego !== nego) return false;
    if (floor === "1" && d.floor_int !== 1) return false;
    if (floor === "2" && d.floor_int !== 2) return false;
    if (floor === "3" && d.floor_int < 3) return false;
    if (area && !d.name.includes(area) && !(d.addr||"").includes(area)) return false;
    if (deposit && d.deposit > deposit) return false;
    if (subway && !(d.subway||"").includes(subway)) return false;
    return true;
  });

  document.getElementById("stats").innerHTML =
    `전체 <span class="stat-num">${allData.length}</span>건 중 조건 맞는 매물 <span class="stat-num">${filtered.length}</span>건`;

  if (!filtered.length) {
    document.getElementById("grid").innerHTML = '<div class="empty">조건에 맞는 매물이 없습니다.</div>';
    return;
  }

  document.getElementById("grid").innerHTML = filtered.map(d => renderCard(d)).join("");
}

function renderCard(d) {
  const isPriority = ["서초","강남","방배","내방","이수"].some(k => d.name.includes(k) || (d.addr||"").includes(k));
  const tagClass = d.type === "전세" ? "tag-jeonse" : d.type === "반전세" ? "tag-ban" : "tag-wolse";
  const price = d.type === "전세"
    ? `전세 ${d.deposit.toLocaleString()}만원`
    : d.type === "반전세"
    ? `반전세 ${d.deposit.toLocaleString()}만 / 월 ${d.monthly_rent}만`
    : `보증금 ${d.deposit.toLocaleString()}만 / 월 ${d.monthly_rent}만`;
  const manage = d.manage_fee ? ` | 관리비 ${d.manage_fee}만` : "";
  const dist = d.dist_naebang ? `📏 내방역 ${d.dist_naebang < 1000 ? d.dist_naebang+"m" : (d.dist_naebang/1000).toFixed(1)+"km"}` : "";
  const lhBadge = d.lh_ok === "가능" ? '<span style="color:#68d391;font-size:11px">✅LH가능</span>' : "";
  const negoBadge = d.nego === "협의가능" ? '<span style="color:#f6ad55;font-size:11px"> 협의가능</span>' : "";

  return `<div class="card ${isPriority?'priority':''}" onclick="showDetail('${d.rtid}', this)" data-id="${d.id}">
    <div class="card-top">
      <div class="card-name">${d.name}</div>
      <span class="tag ${tagClass}">${d.type}</span>
    </div>
    <div class="price">${price}${manage}</div>
    <div class="info-row">
      <div class="info-item">📐 <strong>${d.area}㎡(${Math.round(d.area/3.3*10)/10}평)</strong></div>
      <div class="info-item">🏢 <strong>${d.all_floor}층/${d.floor}층</strong></div>
      <div class="info-item">📅 <strong>${d.reg_date}</strong></div>
    </div>
    ${d.subway ? `<div class="subway">🚇 ${d.subway}</div>` : ""}
    ${dist ? `<div class="dist">${dist}</div>` : ""}
    <div class="broker">${d.broker} ${lhBadge}${negoBadge}</div>
  </div>`;
}

async function showDetail(rtid, el) {
  document.getElementById("modal").classList.add("open");
  document.getElementById("modal-body").innerHTML = "<div class='loading'>상세 정보 불러오는 중...</div>";

  let d = allData.find(x => x.rtid === rtid) || {};
  let detail = detailCache[rtid];

  if (!detail) {
    try {
      const res = await fetch(`/api/detail?rtid=${rtid}`);
      detail = await res.json();
      detailCache[rtid] = detail;
    } catch(e) {
      detail = {};
    }
  }

  const merged = {...d, ...detail};
  const price = d.type === "전세"
    ? `전세 ${d.deposit.toLocaleString()}만원`
    : `보증금 ${d.deposit.toLocaleString()}만 / 월 ${d.monthly_rent}만`;
  const naver = merged.addr ? `https://map.naver.com/v5/search/${encodeURIComponent(merged.addr)}` : "";

  document.getElementById("modal-body").innerHTML = `
    <div class="modal-title">${d.name}</div>
    <div class="modal-grid">
      <div class="modal-item"><label>💰 가격</label><span>${price}</span></div>
      <div class="modal-item"><label>🧾 관리비</label><span>${merged.manage || (d.manage_fee ? d.manage_fee+"만원" : "없음")}</span></div>
      <div class="modal-item"><label>📍 주소</label><span>${merged.addr || "-"}</span></div>
      <div class="modal-item"><label>📐 면적</label><span>전용 ${d.area}㎡ / 공급 ${d.supply_area}㎡</span></div>
      <div class="modal-item"><label>🏢 층수</label><span>${d.all_floor}층 건물 / ${d.floor}층 매물</span></div>
      <div class="modal-item"><label>🧭 방향</label><span>${merged.direction || "-"}</span></div>
      <div class="modal-item"><label>🛏 방/화장실</label><span>${merged.rooms || "-"}</span></div>
      <div class="modal-item"><label>🚗 주차</label><span>${merged.parking || "-"}</span></div>
      <div class="modal-item"><label>📆 입주가능</label><span>${merged.move_in || "-"}</span></div>
      <div class="modal-item"><label>🏛 사용승인</label><span>${merged.approved || "-"}</span></div>
      <div class="modal-item"><label>✅ LH가능</label><span class="lh-ok">${merged.lh_ok || "확인필요"}</span></div>
      <div class="modal-item"><label>🤝 협의</label><span class="nego">${merged.nego || "-"}</span></div>
      <div class="modal-item"><label>🚇 지하철</label><span>${d.subway || "-"}</span></div>
      <div class="modal-item"><label>📏 내방역</label><span>${d.dist_naebang ? (d.dist_naebang<1000 ? d.dist_naebang+"m" : (d.dist_naebang/1000).toFixed(1)+"km") : "-"}</span></div>
      <div class="modal-item"><label>📅 등록일</label><span>${d.reg_date}</span></div>
      <div class="modal-item"><label>🏪 중개사</label><span>${d.broker}</span></div>
      <div class="modal-item"><label>👤 담당자</label><span>${merged.contact_name || "-"}</span></div>
      <div class="modal-item"><label>📱 휴대폰</label><span>${merged.mobile || "-"}</span></div>
      <div class="modal-item"><label>☎️ 전화</label><span>${merged.phone || "-"}</span></div>
      ${merged.options ? `<div class="modal-item" style="grid-column:1/-1"><label>🔧 옵션</label><span>${merged.options}</span></div>` : ""}
    </div>
    <div class="modal-links">
      <a href="${d.detail_link}" target="_blank">🔗 LH 상세보기</a>
      ${naver ? `<a href="${naver}" target="_blank">🗺 네이버지도</a>` : ""}
    </div>
  `;
}

function closeModal(e) {
  if (e.target === document.getElementById("modal")) {
    document.getElementById("modal").classList.remove("open");
  }
}

function resetFilter() {
  ["f-type","f-today","f-lh","f-nego","f-floor","f-area","f-subway"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("f-deposit").value = "";
  applyFilter();
}

loadListings();
</script>
</body>
</html>'''

@app.route("/api/listings")
def api_listings():
    if not _cache["listings"]:
        refresh_cache()
    return jsonify({"listings": _cache["listings"], "updated": _cache["updated"]})

@app.route("/api/detail")
def api_detail():
    rtid = request.args.get("rtid", "")
    if not rtid:
        return jsonify({})
    detail = fetch_detail(rtid)
    return jsonify(detail)

@app.route("/api/refresh")
def api_refresh():
    refresh_cache()
    return jsonify({"ok": True, "count": len(_cache["listings"])})

def bot_loop():
    seen = set()
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE,"r") as f:
            seen = set(json.load(f))
    while True:
        try:
            refresh_cache()
            for listing in _cache["listings"]:
                lid = listing["id"]
                if lid not in seen:
                    seen.add(lid)
                    detail = fetch_detail(listing.get("rtid",""))
                    msg = f"🏠 새 매물: {listing['name']}\n💰 {listing['deposit']:,.0f}만원\n📍 {detail.get('addr','')}\n📱 {detail.get('mobile','')}\n🔗 {listing['detail_link']}"
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                  json={"chat_id":TELEGRAM_CHAT_ID,"text":msg}, timeout=10)
                    try:
                        requests.post(SHEETS_URL, json={**listing,**detail}, timeout=10)
                    except: pass
            with open(SEEN_FILE,"w") as f:
                json.dump(list(seen), f)
        except Exception as e:
            print(f"봇 오류: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
