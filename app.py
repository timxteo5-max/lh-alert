from flask import Flask, jsonify, request
import requests, re, math, threading, json, os, time, hashlib
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup

app = Flask(__name__)

TELEGRAM_TOKEN = "여기에_새_토큰_입력"
TELEGRAM_CHAT_ID = "여기에_채팅ID_입력"
SHEETS_URL = "https://script.google.com/macros/s/AKfycbx-KIPy5qrS8pFBgZ1tOq23R439ahs-D9eOfYFDqRtgKGm8KxmBiyGssnTMUH4G0wdi/exec"
CHECK_INTERVAL = 1800
SEEN_FILE = "seen_listings.json"
NAEBANG_LAT = 37.4969
NAEBANG_LNG = 126.9810

SUBWAY_LINES = {
    "1호선":["종각","시청","서울역","용산","노량진","구로","영등포","수원","인천"],
    "2호선":["시청","을지로입구","강남","역삼","선릉","삼성","잠실","건대입구","홍대입구","신촌","이대","방배","서초","교대","사당","낙성대","봉천","신림"],
    "3호선":["종로3가","충무로","약수","금호","옥수","압구정","신사","잠원","고속터미널","교대","남부터미널","양재","매봉","도곡","대치","학여울"],
    "4호선":["동대문","혜화","한성대입구","성신여대입구","길음","미아사거리","수유","창동","노원","당고개","사당","이수","동작","총신대입구"],
    "5호선":["광화문","종로3가","을지로4가","동대문역사문화공원","청구","신금호","행당","왕십리","마장","답십리","장한평","군자","아차산","광나루","천호","강동","마천","방화"],
    "6호선":["이태원","녹사평","삼각지","효창공원앞","공덕","디지털미디어시티","응암","불광","독바위","연신내","구산"],
    "7호선":["장암","도봉산","수락산","마들","노원","중계","하계","공릉","태릉입구","먹골","중화","상봉","면목","사가정","용마산","중곡","군자","어린이대공원","건대입구","뚝섬유원지","청담","강남구청","학동","논현","반포","고속터미널","내방","이수","남성","숭실대입구","상도","장승배기","신대방삼거리","보라매","신풍","대림","구로디지털단지","천왕","광명사거리","철산","가산디지털단지","남구로","온수"],
    "8호선":["암사","천호","강동구청","몽촌토성","잠실","석촌","송파","가락시장","문정","장지","복정","산성","남한산성입구","단대오거리","신흥","수진","모란"],
    "9호선":["개화","김포공항","공항시장","신방화","마곡나루","양천향교","가양","증미","등촌","염창","신목동","선유도","당산","국회의사당","여의도","샛강","노량진","노들","흑석","동작","구반포","신반포","고속터미널","사평","신논현","언주","선정릉","봉은사","종합운동장","삼전","석촌고분","석촌","송파나루","한성백제","올림픽공원","둔촌오륜","중앙보훈병원"],
    "수인분당선":["왕십리","서울숲","압구정로데오","강남구청","선정릉","선릉","한티","도곡","구룡","개포동","대모산입구","수서","복정","태평","가천대","이매","야탑","모란","수원"],
    "신분당선":["강남","양재","양재시민의숲","청계산입구","판교","정자","미금","동천","수지구청","성복","상현","광교중앙","광교"],
    "경의중앙선":["서울역","효창공원앞","공덕","홍대입구","가좌","디지털미디어시티","수색","능곡","행신","화전","강매","김포공항","마곡","양천향교","용산","이촌","서빙고","한남","옥수","응봉","왕십리","청량리"],
    "GTX-A":["수서","성남","용인","동탄"],
}

SEOUL_GU = ["강남구","강동구","강북구","강서구","관악구","광진구","구로구","금천구","노원구","도봉구","동대문구","동작구","마포구","서대문구","서초구","성동구","성북구","송파구","양천구","영등포구","용산구","은평구","종로구","중구","중랑구"]

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
    "mi":"2872","recentChk":"N","addrGroupChk":"Y",
    "rthousBdtyp":"9","rthousRentStle":"9","rthousDelngSttus":"9",
    "rthousRoomCo":"-1","rthousToiletCo":"-1",
    "rthousGtnFrom":"10000","rthousGtnTo":"16000",
    "rthousMthtFrom":"0","rthousMthtTo":"35",
    "rthousHpprFrom":"33","rthousHpprTo":"84",
    "confmdeFrom":"1900","confmdeTo":"2029",
    "northEast":"(38.3, 127.9)","southWest":"(36.9, 126.1)",
}

def safe_float(val):
    try:
        m = re.search(r'\d+\.?\d*', str(val))
        return float(m.group()) if m else 0.0
    except: return 0.0

def calc_distance(lat1,lng1,lat2,lng2):
    R=6371000
    p1,p2=math.radians(lat1),math.radians(lat2)
    a=math.sin(math.radians(lat2-lat1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(lng2-lng1)/2)**2
    return round(R*2*math.atan2(math.sqrt(a),math.sqrt(1-a)))

def detect_subway(text):
    found=[]
    for line,stations in SUBWAY_LINES.items():
        for st in stations:
            if st in text:
                found.append(f"{line} {st}역")
                break
    return ", ".join(found) if found else ""

def fetch_detail(rtid):
    try:
        r=requests.post(DETAIL_URL,data={"rthousId":rtid,"mi":"2873"},headers=HEADERS,timeout=10)
        soup=BeautifulSoup(r.text,"html.parser")
        result={}
        for row in soup.select("table tr"):
            cells=row.find_all(["th","td"])
            for i,cell in enumerate(cells):
                label=cell.get_text(strip=True)
                if i+1<len(cells):
                    val=cells[i+1].get_text(strip=True)
                    if "매물주소" in label: result["addr"]=val
                    elif "관리비" in label: result["manage"]=val
                    elif "방향" in label: result["direction"]=val
                    elif "입주" in label: result["move_in"]=val
                    elif "주차" in label: result["parking"]=val
                    elif "방/화장실" in label: result["rooms"]=val
                    elif "이름" in label: result["contact_name"]=val
                    elif "휴대폰" in label: result["mobile"]=val
                    elif "전화번호" in label: result["phone"]=val
                    elif "사용승인" in label: result["approved"]=val
                    elif "건축물" in label and "용도" in label: result["building_use"]=val
        # LH/협의/엘베 감지
        text_all = r.text
        result["lh_ok"] = "가능" if ("LH가능" in text_all or "LH 가능" in text_all or "lh가능" in text_all.lower()) else "확인필요"
        result["nego"] = "협의가능" if "협의" in text_all else "불가"
        result["elevator"] = "있음" if ("엘리베이터" in text_all or "엘베" in text_all or "승강기" in text_all) else "없음/미확인"
        result["dabang"] = "있음" if "다방" in text_all else ""
        opts=[]
        for o in soup.select(".opt_list span,.option span,td.opt,.option_list li"):
            t=o.get_text(strip=True)
            if t: opts.append(t)
        result["options"]=", ".join(opts) if opts else ""
        desc_el=soup.select_one(".detail_cont,.desc_cont,#descCont")
        result["desc"]=desc_el.get_text(strip=True) if desc_el else ""
        if not result.get("mobile"):
            phones=re.findall(r'0\d{1,2}-?\d{3,4}-?\d{4}',r.text)
            if phones: result["mobile"]=phones[0]
            if len(phones)>1: result["phone"]=phones[1]
        if not result.get("addr"):
            m=re.search(r'서울[^\s<]{5,30}|경기[^\s<]{5,30}|인천[^\s<]{5,30}',r.text)
            if m: result["addr"]=m.group()
        return result
    except: return {}

def fetch_all_listings():
    all_listings=[]
    page=1
    while True:
        try:
            params=PARAMS.copy()
            params["currPage"]=str(page)
            r=requests.post(SEARCH_URL,data=params,headers=HEADERS,timeout=15)
            data=r.json()
            listings=data.get("rthousList",[])
            all_listings.extend(listings)
            total_page=data.get("rthousListPaging",{}).get("totalPage",1)
            if page>=total_page: break
            page+=1
            time.sleep(0.3)
        except: break
    return all_listings

def parse_listing(item):
    area=safe_float(item.get("rthousExclAr",0))
    supply=safe_float(item.get("rthousHppr",0))
    floor=item.get("rthousFloor","-")
    all_floor=item.get("rthousAllFloor","-")
    deposit=safe_float(item.get("rthousGtn",0))
    monthly=safe_float(item.get("rthousMtht",0))
    rent_type=item.get("rthousRentStle","")
    name=item.get("rthousNm","")
    rtid=item.get("rthousId","")
    reg_date=item.get("rthousRgsde","")
    broker=item.get("brkrNm","")
    manage=safe_float(item.get("rthousManagect",0))
    desc=item.get("rthousSumryDc","")+item.get("rthousSumryKwrd","")
    lat=safe_float(item.get("rthousYdnts",0))
    lng=safe_float(item.get("rthousXcnts",0))
    type_str={"1":"전세","3":"반전세"}.get(rent_type,"월세")
    dist=calc_distance(NAEBANG_LAT,NAEBANG_LNG,lat,lng) if lat and lng else 0
    subway=detect_subway(name+" "+desc)
    try: floor_int=int(floor)
    except: floor_int=0
    # 지역 감지
    region=""
    for gu in SEOUL_GU:
        if gu in name or gu in desc:
            region=f"서울 {gu}"
            break
    if not region:
        for r in ["경기","인천"]:
            if r in name or r in desc:
                region=r
                break
    return {
        "id":rtid or hashlib.md5((name+str(deposit)).encode()).hexdigest(),
        "rtid":rtid,"name":name,"area":area,"supply_area":supply,
        "floor":str(floor),"floor_int":floor_int,"all_floor":str(all_floor),
        "deposit":deposit,"monthly_rent":monthly,"manage_fee":manage,
        "type":type_str,"reg_date":reg_date,"broker":broker,
        "desc":desc.strip(),"subway":subway,"dist_naebang":dist,
        "region":region,
        "detail_link":f"https://jeonse.lh.or.kr/jw/rs/search/selectRthousInfo.do?rthousId={rtid}&mi=2873",
        "found_at":datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

_cache={"listings":[],"updated":""}

def refresh_cache():
    raw=fetch_all_listings()
    parsed=[]
    for item in raw:
        try:
            p=parse_listing(item)
            parsed.append(p)
        except: continue
    _cache["listings"]=parsed
    _cache["updated"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@app.route("/")
def dashboard():
    today=date.today().strftime("%Y.%m.%d")
    yesterday=(date.today()-timedelta(1)).strftime("%Y.%m.%d")
    subway_options="\n".join([f'<option value="{k}">{k}</option>' for k in SUBWAY_LINES.keys()])
    gu_options="\n".join([f'<option value="{g}">{g}</option>' for g in SEOUL_GU])
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LH 전세임대 대시보드</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap');
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Noto Sans KR',sans-serif;background:#0d1117;color:#e2e8f0;min-height:100vh}}
.header{{background:#161b22;border-bottom:2px solid #21262d;padding:14px 20px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}}
.logo{{font-size:16px;font-weight:700;color:#58a6ff}}
.updated{{font-size:11px;color:#6e7681}}
.filters{{background:#161b22;border-bottom:1px solid #21262d;padding:12px 20px;display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end}}
.fg{{display:flex;flex-direction:column;gap:3px}}
.fg label{{font-size:10px;color:#6e7681;font-weight:500;text-transform:uppercase}}
select,input{{background:#21262d;border:1px solid #30363d;color:#e2e8f0;padding:5px 8px;border-radius:6px;font-size:12px;font-family:inherit;min-width:90px}}
select:focus,input:focus{{outline:none;border-color:#58a6ff}}
.btn{{background:#238636;color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-family:inherit;font-weight:600;height:28px}}
.btn:hover{{background:#2ea043}}
.btn-reset{{background:#21262d;border:1px solid #30363d}}
.btn-reset:hover{{background:#30363d}}
.btn-refresh{{background:#1f6feb}}
.btn-refresh:hover{{background:#388bfd}}
.stats{{padding:8px 20px;display:flex;gap:12px;font-size:12px;color:#6e7681;border-bottom:1px solid #21262d}}
.stat-num{{color:#58a6ff;font-weight:700}}
.grid{{padding:14px 20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}}
.card{{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:14px;cursor:pointer;transition:all .15s}}
.card:hover{{border-color:#58a6ff;background:#1c2128}}
.card.gold{{border-color:#d29922}}
.card-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}}
.card-name{{font-weight:600;font-size:13px;line-height:1.4;flex:1;margin-right:6px}}
.tags{{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}}
.tag{{font-size:10px;padding:2px 6px;border-radius:4px;white-space:nowrap;font-weight:600}}
.t-jeonse{{background:#0d2137;color:#58a6ff;border:1px solid #1f6feb}}
.t-wolse{{background:#2d1515;color:#f85149;border:1px solid #da3633}}
.t-ban{{background:#132d15;color:#3fb950;border:1px solid #238636}}
.t-lh{{background:#1a3a1a;color:#56d364}}
.t-nego{{background:#3d2a00;color:#d29922}}
.t-elev{{background:#1a1a3d;color:#79c0ff}}
.t-basement{{background:#3d1515;color:#f85149}}
.price{{font-size:15px;font-weight:700;color:#f0b429;margin-bottom:6px}}
.info-grid{{display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-bottom:6px}}
.info-item{{font-size:11px;color:#6e7681}}
.info-item strong{{color:#c9d1d9}}
.subway-tag{{font-size:11px;color:#3fb950;margin-top:4px}}
.dist-tag{{font-size:11px;color:#f85149}}
.date-tag{{font-size:10px;color:#6e7681}}
.broker-row{{font-size:11px;color:#6e7681;margin-top:8px;padding-top:6px;border-top:1px solid #21262d;display:flex;justify-content:space-between}}
.modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:200;justify-content:center;align-items:flex-start;overflow-y:auto;padding:16px}}
.modal.open{{display:flex}}
.mc{{background:#161b22;border:1px solid #30363d;border-radius:14px;padding:20px;max-width:620px;width:100%;margin:auto;position:relative}}
.mc-close{{position:absolute;top:14px;right:14px;background:#21262d;border:none;color:#8b949e;font-size:16px;cursor:pointer;width:28px;height:28px;border-radius:6px}}
.mc-title{{font-size:16px;font-weight:700;margin-bottom:14px;color:#58a6ff;padding-right:30px}}
.mc-grid{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:14px}}
.mc-item{{background:#21262d;border-radius:6px;padding:8px 10px}}
.mc-item label{{font-size:10px;color:#6e7681;display:block;margin-bottom:2px;text-transform:uppercase}}
.mc-item span{{font-size:12px;color:#e2e8f0;font-weight:500}}
.mc-full{{grid-column:1/-1}}
.mc-links{{display:flex;gap:6px}}
.mc-links a{{background:#21262d;color:#58a6ff;padding:8px 14px;border-radius:6px;text-decoration:none;font-size:12px;flex:1;text-align:center;border:1px solid #30363d}}
.mc-links a:hover{{background:#1f6feb;color:white;border-color:#1f6feb}}
.loading{{text-align:center;padding:60px;color:#6e7681}}
.empty{{text-align:center;padding:60px;color:#6e7681}}
.sep{{width:1px;background:#21262d;margin:0 4px}}
</style>
</head>
<body>
<div class="header">
  <div class="logo">🏠 LH 전세임대 대시보드</div>
  <div class="updated" id="updated">로딩 중...</div>
</div>

<div class="filters">
  <div class="fg">
    <label>날짜</label>
    <select id="f-date">
      <option value="">전체</option>
      <option value="today">오늘({today})</option>
      <option value="yesterday">어제({yesterday})</option>
      <option value="3days">3일 이내</option>
      <option value="week">1주일 이내</option>
    </select>
  </div>
  <div class="fg">
    <label>거래유형</label>
    <select id="f-type">
      <option value="">전체</option>
      <option value="전세">전세</option>
      <option value="반전세">반전세</option>
      <option value="월세">월세</option>
    </select>
  </div>
  <div class="fg">
    <label>LH가능</label>
    <select id="f-lh">
      <option value="">전체</option>
      <option value="가능">가능</option>
      <option value="확인필요">확인필요</option>
    </select>
  </div>
  <div class="fg">
    <label>협의여부</label>
    <select id="f-nego">
      <option value="">전체</option>
      <option value="협의가능">협의가능</option>
      <option value="불가">불가</option>
    </select>
  </div>
  <div class="fg">
    <label>층수</label>
    <select id="f-floor">
      <option value="">전체</option>
      <option value="basement">지하/반지하</option>
      <option value="1">1층</option>
      <option value="2">2층</option>
      <option value="3">3층 이상</option>
      <option value="rooftop">옥탑</option>
    </select>
  </div>
  <div class="fg">
    <label>엘리베이터</label>
    <select id="f-elev">
      <option value="">전체</option>
      <option value="있음">있음</option>
      <option value="없음/미확인">없음/미확인</option>
    </select>
  </div>
  <div class="sep"></div>
  <div class="fg">
    <label>지역구분</label>
    <select id="f-region-type">
      <option value="">전체</option>
      <option value="서울">서울 전체</option>
      <option value="경기">경기</option>
      <option value="인천">인천</option>
    </select>
  </div>
  <div class="fg">
    <label>서울 구</label>
    <select id="f-gu">
      <option value="">전체</option>
      {gu_options}
    </select>
  </div>
  <div class="sep"></div>
  <div class="fg">
    <label>보증금 최소(만)</label>
    <input type="number" id="f-dep-min" placeholder="예:10000" style="width:90px">
  </div>
  <div class="fg">
    <label>보증금 최대(만)</label>
    <input type="number" id="f-dep-max" placeholder="예:16000" style="width:90px">
  </div>
  <div class="fg">
    <label>월세 최대(만)</label>
    <input type="number" id="f-monthly" placeholder="예:35" style="width:70px">
  </div>
  <div class="fg">
    <label>관리비</label>
    <select id="f-manage">
      <option value="">전체</option>
      <option value="0">없음</option>
      <option value="5">5만 미만</option>
      <option value="10">5~10만</option>
      <option value="15">10~15만</option>
      <option value="20">15~20만</option>
      <option value="99">20만 이상</option>
    </select>
  </div>
  <div class="sep"></div>
  <div class="fg">
    <label>지하철 노선</label>
    <select id="f-subway">
      <option value="">전체</option>
      {subway_options}
    </select>
  </div>
  <div class="fg">
    <label>다방 등록</label>
    <select id="f-dabang">
      <option value="">전체</option>
      <option value="있음">있음</option>
    </select>
  </div>
  <div style="display:flex;gap:4px;align-items:flex-end">
    <button class="btn" onclick="applyFilter()">🔍 검색</button>
    <button class="btn btn-reset" onclick="resetFilter()">초기화</button>
    <button class="btn btn-refresh" onclick="loadListings()">🔄 새로고침</button>
  </div>
</div>

<div class="stats" id="stats">매물 로딩 중...</div>
<div class="grid" id="grid"><div class="loading">매물을 불러오는 중...</div></div>

<div class="modal" id="modal" onclick="closeModalBg(event)">
  <div class="mc">
    <button class="mc-close" onclick="closeModal()">✕</button>
    <div id="modal-body"></div>
  </div>
</div>

<script>
let allData=[];
let detailCache={{}};
const todayStr="{today}";
const dates={{
  today:"{today}",
  yesterday:"{yesterday}",
  "3days":new Date(Date.now()-3*864e5).toISOString().slice(0,10).split("-").join("."),
  week:new Date(Date.now()-7*864e5).toISOString().slice(0,10).split("-").join(".")
}};

async function loadListings(){{
  document.getElementById("grid").innerHTML='<div class="loading">매물 불러오는 중...</div>';
  try{{
    const res=await fetch("/api/listings");
    const data=await res.json();
    allData=data.listings;
    document.getElementById("updated").textContent="업데이트: "+data.updated+" (총 "+allData.length+"건)";
    applyFilter();
  }}catch(e){{
    document.getElementById("grid").innerHTML='<div class="empty">불러오기 실패. 새로고침 해주세요.</div>';
  }}
}}

function applyFilter(){{
  const dateVal=document.getElementById("f-date").value;
  const type=document.getElementById("f-type").value;
  const lh=document.getElementById("f-lh").value;
  const nego=document.getElementById("f-nego").value;
  const floor=document.getElementById("f-floor").value;
  const elev=document.getElementById("f-elev").value;
  const regionType=document.getElementById("f-region-type").value;
  const gu=document.getElementById("f-gu").value;
  const depMin=parseFloat(document.getElementById("f-dep-min").value)||0;
  const depMax=parseFloat(document.getElementById("f-dep-max").value)||0;
  const monthly=parseFloat(document.getElementById("f-monthly").value)||0;
  const manage=document.getElementById("f-manage").value;
  const subway=document.getElementById("f-subway").value;
  const dabang=document.getElementById("f-dabang").value;

  let filtered=allData.filter(d=>{{
    if(dateVal){{
      const cutoff=dates[dateVal]||"";
      if(dateVal==="today"&&d.reg_date!==todayStr) return false;
      if(dateVal==="yesterday"&&d.reg_date!==dates.yesterday) return false;
      if((dateVal==="3days"||dateVal==="week")&&d.reg_date<cutoff) return false;
    }}
    if(type&&d.type!==type) return false;
    if(lh&&(d.lh_ok||"")!==lh) return false;
    if(nego&&(d.nego||"")!==nego) return false;
    if(floor==="basement"&&d.floor_int>=1) return false;
    if(floor==="basement"&&d.floor_int>=1) return false;
    if(floor==="1"&&d.floor_int!==1) return false;
    if(floor==="2"&&d.floor_int!==2) return false;
    if(floor==="3"&&d.floor_int<3) return false;
    if(floor==="rooftop"&&!(d.name||"").includes("옥")) return false;
    if(elev&&(d.elevator||"")!==elev) return false;
    if(regionType&&!(d.region||"").includes(regionType)) return false;
    if(gu&&!(d.region||"").includes(gu)) return false;
    if(depMin&&d.deposit<depMin) return false;
    if(depMax&&d.deposit>depMax) return false;
    if(monthly&&d.monthly_rent>monthly) return false;
    if(manage){{
      const m=d.manage_fee||0;
      if(manage==="0"&&m!==0) return false;
      if(manage==="5"&&(m<=0||m>=5)) return false;
      if(manage==="10"&&(m<5||m>=10)) return false;
      if(manage==="15"&&(m<10||m>=15)) return false;
      if(manage==="20"&&(m<15||m>=20)) return false;
      if(manage==="99"&&m<20) return false;
    }}
    if(subway&&!(d.subway||"").includes(subway)) return false;
    if(dabang&&!(d.dabang||"").includes(dabang)) return false;
    return true;
  }});

  document.getElementById("stats").innerHTML=
    `전체 <span class="stat-num">${{allData.length}}</span>건 중 조건 매물 <span class="stat-num">${{filtered.length}}</span>건`;

  if(!filtered.length){{
    document.getElementById("grid").innerHTML='<div class="empty">조건에 맞는 매물이 없습니다.</div>';
    return;
  }}
  document.getElementById("grid").innerHTML=filtered.map(renderCard).join("");
}}

function renderCard(d){{
  const isPriority=["서초","강남","방배","내방","이수","사당","군자"].some(k=>(d.name||"").includes(k)||(d.region||"").includes(k));
  const tagClass=d.type==="전세"?"t-jeonse":d.type==="반전세"?"t-ban":"t-wolse";
  const price=d.type==="전세"?`전세 ${{d.deposit.toLocaleString()}}만원`:
    d.type==="반전세"?`반전세 ${{d.deposit.toLocaleString()}}만 / 월 ${{d.monthly_rent}}만`:
    `보증금 ${{d.deposit.toLocaleString()}}만 / 월 ${{d.monthly_rent}}만`;
  const manage=d.manage_fee?` | 관리비 ${{d.manage_fee}}만`:"";
  const dist=d.dist_naebang?(d.dist_naebang<1000?`${{d.dist_naebang}}m`:`${{(d.dist_naebang/1000).toFixed(1)}}km`):"";
  const isBasement=d.floor_int<1;
  return `<div class="card ${{isPriority?'gold':''}}" onclick="showDetail('${{d.rtid}}')" data-id="${{d.id}}">
    <div class="card-header">
      <div class="card-name">${{d.name}}</div>
      <div class="tags">
        <span class="tag ${{tagClass}}">${{d.type}}</span>
        ${{isBasement?'<span class="tag t-basement">지하</span>':''}}
        ${{d.lh_ok==="가능"?'<span class="tag t-lh">LH✓</span>':''}}
        ${{d.nego==="협의가능"?'<span class="tag t-nego">협의</span>':''}}
        ${{d.elevator==="있음"?'<span class="tag t-elev">엘베</span>':''}}
      </div>
    </div>
    <div class="price">${{price}}${{manage}}</div>
    <div class="info-grid">
      <div class="info-item">📐 <strong>${{d.area}}㎡(${{Math.round(d.area/3.3*10)/10}}평)</strong></div>
      <div class="info-item">🏢 <strong>${{d.all_floor}}층/${{d.floor}}층</strong></div>
      <div class="info-item">📍 <strong>${{d.region||'-'}}</strong></div>
      <div class="info-item">📅 <strong>${{d.reg_date}}</strong></div>
    </div>
    ${{d.subway?`<div class="subway-tag">🚇 ${{d.subway}}</div>`:''}}
    ${{dist?`<div class="dist-tag">📏 내방역 ${{dist}}</div>`:''}}
    <div class="broker-row"><span>${{d.broker}}</span><span class="date-tag">${{d.found_at}}</span></div>
  </div>`;
}}

async function showDetail(rtid){{
  document.getElementById("modal").classList.add("open");
  document.getElementById("modal-body").innerHTML='<div class="loading">상세 정보 불러오는 중...</div>';
  let d=allData.find(x=>x.rtid===rtid)||{{}};
  let detail=detailCache[rtid];
  if(!detail){{
    try{{
      const res=await fetch(`/api/detail?rtid=${{rtid}}`);
      detail=await res.json();
      detailCache[rtid]=detail;
    }}catch(e){{detail={{}};}}
  }}
  const merged={{...d,...detail}};
  const price=d.type==="전세"?`전세 ${{d.deposit?.toLocaleString()}}만원`:
    `보증금 ${{d.deposit?.toLocaleString()}}만 / 월 ${{d.monthly_rent}}만`;
  const naver=merged.addr?`https://map.naver.com/v5/search/${{encodeURIComponent(merged.addr)}}`:"";
  document.getElementById("modal-body").innerHTML=`
    <div class="mc-title">${{d.name}}</div>
    <div class="mc-grid">
      <div class="mc-item"><label>💰 가격</label><span>${{price}}</span></div>
      <div class="mc-item"><label>🧾 관리비</label><span>${{merged.manage||(d.manage_fee?d.manage_fee+"만원":"없음")}}</span></div>
      <div class="mc-item mc-full"><label>📍 주소</label><span>${{merged.addr||"-"}}</span></div>
      <div class="mc-item"><label>📐 면적</label><span>전용 ${{d.area}}㎡(${{Math.round((d.area||0)/3.3*10)/10}}평)</span></div>
      <div class="mc-item"><label>🏠 공급면적</label><span>${{d.supply_area}}㎡(${{Math.round((d.supply_area||0)/3.3*10)/10}}평)</span></div>
      <div class="mc-item"><label>🏢 층수</label><span>${{d.all_floor}}층 건물 / ${{d.floor}}층</span></div>
      <div class="mc-item"><label>🧭 방향</label><span>${{merged.direction||"-"}}</span></div>
      <div class="mc-item"><label>🛏 방/화장실</label><span>${{merged.rooms||"-"}}</span></div>
      <div class="mc-item"><label>🚗 주차</label><span>${{merged.parking||"-"}}</span></div>
      <div class="mc-item"><label>🛗 엘리베이터</label><span>${{merged.elevator||"-"}}</span></div>
      <div class="mc-item"><label>📆 입주가능</label><span>${{merged.move_in||"-"}}</span></div>
      <div class="mc-item"><label>🏛 사용승인</label><span>${{merged.approved||"-"}}</span></div>
      <div class="mc-item"><label>✅ LH가능</label><span style="color:#3fb950;font-weight:600">${{merged.lh_ok||"확인필요"}}</span></div>
      <div class="mc-item"><label>🤝 협의</label><span style="color:#d29922">${{merged.nego||"-"}}</span></div>
      <div class="mc-item"><label>🚇 지하철</label><span>${{d.subway||"-"}}</span></div>
      <div class="mc-item"><label>📏 내방역</label><span>${{d.dist_naebang?(d.dist_naebang<1000?d.dist_naebang+"m":(d.dist_naebang/1000).toFixed(1)+"km"):"-"}}</span></div>
      <div class="mc-item"><label>📅 등록일</label><span>${{d.reg_date}}</span></div>
      <div class="mc-item"><label>🏪 중개사</label><span>${{d.broker}}</span></div>
      <div class="mc-item"><label>👤 담당자</label><span>${{merged.contact_name||"-"}}</span></div>
      <div class="mc-item"><label>📱 휴대폰</label><span>${{merged.mobile||"-"}}</span></div>
      <div class="mc-item"><label>☎️ 전화</label><span>${{merged.phone||"-"}}</span></div>
      ${{merged.options?`<div class="mc-item mc-full"><label>🔧 옵션</label><span>${{merged.options}}</span></div>`:''}}
      ${{merged.desc?`<div class="mc-item mc-full"><label>📝 상세설명</label><span style="font-size:11px;line-height:1.5">${{merged.desc.slice(0,300)}}</span></div>`:''}}
    </div>
    <div class="mc-links">
      <a href="${{d.detail_link}}" target="_blank">🔗 LH 상세보기</a>
      ${{naver?`<a href="${{naver}}" target="_blank">🗺 네이버지도</a>`:''}}
    </div>`;
}}

function closeModal(){{document.getElementById("modal").classList.remove("open");}}
function closeModalBg(e){{if(e.target===document.getElementById("modal"))closeModal();}}
function resetFilter(){{
  ["f-date","f-type","f-lh","f-nego","f-floor","f-elev","f-region-type","f-gu","f-manage","f-subway","f-dabang"].forEach(id=>document.getElementById(id).value="");
  ["f-dep-min","f-dep-max","f-monthly"].forEach(id=>document.getElementById(id).value="");
  applyFilter();
}}
loadListings();
</script>
</body>
</html>'''

@app.route("/api/listings")
def api_listings():
    if not _cache["listings"]: refresh_cache()
    return jsonify({"listings":_cache["listings"],"updated":_cache["updated"]})

@app.route("/api/detail")
def api_detail():
    rtid=request.args.get("rtid","")
    if not rtid: return jsonify({})
    return jsonify(fetch_detail(rtid))

@app.route("/api/refresh")
def api_refresh():
    refresh_cache()
    return jsonify({"ok":True,"count":len(_cache["listings"])})

def bot_loop():
    seen=set()
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE,"r") as f: seen=set(json.load(f))
    while True:
        try:
            refresh_cache()
            for listing in _cache["listings"]:
                lid=listing["id"]
                if lid not in seen:
                    seen.add(lid)
                    detail=fetch_detail(listing.get("rtid",""))
                    msg=f"🏠 새 매물: {listing['name']}\n💰 {listing['deposit']:,.0f}만원\n📍 {detail.get('addr','')}\n📱 {detail.get('mobile','')}\n🔗 {listing['detail_link']}"
                    try:
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                            json={"chat_id":TELEGRAM_CHAT_ID,"text":msg},timeout=10)
                    except: pass
                    try:
                        session=requests.Session()
                        session.post(SHEETS_URL,data=json.dumps({**listing,**detail}),
                            headers={"Content-Type":"application/json"},allow_redirects=True,timeout=15)
                    except: pass
            with open(SEEN_FILE,"w") as f: json.dump(list(seen),f)
        except Exception as e: print(f"봇 오류: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__=="__main__":
    t=threading.Thread(target=bot_loop,daemon=True)
    t.start()
    port=int(os.environ.get("PORT",8080))
    app.run(host="0.0.0.0",port=port)
