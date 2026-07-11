"""
fetch_13f.py — 미국 가치투자 거장 13F 공시 수집 
(84명 풀 리스트 한글 명칭 복구 + XML 파일 전수 검사 로직)
"""

import os, sys, json, time, re, base64
import datetime as dt
import requests

GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_OWNER   = "buffettarchive"
GH_REPO    = "vip-tracker"
GH_PATH    = "docs/us_vips.json"
GH_BRANCH  = "main"
GH_API     = "https://api.github.com"

s = requests.Session()
s.headers.update({
    "User-Agent": "BuffettArchive buffettarchive1@gmail.com",
    "Accept-Encoding": "gzip, deflate"
})

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ══════════════════════════════════════════════════════════════════
# 84명 구루 한글 명칭 원상 복구 (게이츠 재단 캐스케이드 CIK 교정 포함)
# ══════════════════════════════════════════════════════════════════
GURUS = {
    "워런 버핏 (버크셔 해서웨이)": "0001067983",
    "마이클 버리 (사이언 에셋)": "0001649339",
    "빌 애크먼 (퍼싱 스퀘어)": "0001336528",
    "세스 클라만 (바우포스트 그룹)": "0001061768",
    "리 루 (히말라야 캐피탈)": "0001569205",
    "넬슨 펠츠 (트리안 펀드)": "0001345471",
    "바이킹 글로벌 (안드레아스 할보센)": "0001103804",
    "칼 아이칸 (아이칸 캐피탈)": "0000921669",
    "단 롭 (서드 포인트)": "0001040273",
    "빌 밀러 (밀러 밸류 파트너스)": "0000820124",
    "프렘 왓사 (페어팩스)": "0000915191",
    "토마스 게이너 (마켈 그룹)": "0001096343",
    "리차드 프제나 (프제나 인베스트먼트)": "0001027796",
    "모니시 파브라이 (파브라이 인베스트먼트)": "0001549575",
    "데이비드 테퍼 (아팔루사)": "0001656456",
    "스티븐 맨델 (론 파인)": "0001061165",
    "하워드 막스 (오크트리)": "0001535472",
    "데이비드 아인혼 (그린라이트)": "0001079114",
    "밸류액트 캐피탈": "0001397545",
    "빌 & 멀린다 게이츠 재단 (캐스케이드)": "0001166559",
    "체이스 콜먼 (타이거 글로벌)": "0001167483",
    "리 애인슬리 (매버릭 캐피탈)": "0000934639",
    "브루스 버코위츠 (페어홈)": "0001056831",
    "빌 니그렌 (해리스 어소시에이츠)": "0000813917",
    "글렌 그린버그 (브레이브 워리어)": "0001553733",
    "메이슨 호킨스 (사우스이스턴)": "0000807985",
    "척 아크레 (아크레 캐피탈)": "0001112520",
    "도지 앤 콕스": "0000315066",
    "존 로저스 (아리엘 인베스트먼트)": "0000936753",
    "크리스 혼 (TCI 펀드)": "0001647251",
    "퍼스트 이글 인베스트먼트": "0000810958",
    "데이비드 에이브럼스 (아브람스 캐피탈)": "0001358706",
    "크리스토퍼 데이비스 (데이비스 어드바이저스)": "0001036325",
    "트위디 브라운": "0000732905",
    "토마스 루소 (가드너 루소)": "0000860643",
    "데이비드 롤프 (웨지우드)": "0000859804",
    "윌리엄 폰 뮈플링 (칸티용)": "0001279936",
    "퍼스트 퍼시픽 어드바이저스": "0001377581",
    "레온 쿠퍼만 (오메가)": "0000898202",
    "사라 케터러 (코즈웨이)": "0001406439",
    "헨리 엘렌보겐 (듀러블 캐피탈)": "0001798849",
    "데니스 홍 (쇼스프링)": "0001766908",
    "데이비드 카츠 (매트릭스)": "0001016287",
    "크리스토퍼 블룸스트란 (셈퍼 아우구스투스)": "0001115373",
    "루안 커니프 (세쿼이아)": "0000851730",
    "알타록 파트너스": "0001631014",
    "폴렌 캐피탈": "0001034524",
    "써드 애비뉴 매니지먼트": "0001099281",
    "스티븐 체크 (체크 캐피탈)": "0001032814",
    "토레이 펀드": "0000098758",
    "얙트먼 에셋 매니지먼트": "0000905567",
    "로버트 올스타인 (올스타인)": "0000947996",
    "그린헤이븐 어소시에이츠": "0000846222",
    "뮬렌캠프": "0001133219",
    "브라이언 로렌스 (오크클리프)": "0001657335",
    "팻 도시 (도시 애셋)": "0001671657",
    "힐만 캐피탈": "0001314620",
    "톰 밴크로프트 (마카이라)": "0001540866",
    "사만다 맥레모어 (페이션트)": "0001854794",
    "클리포드 소신 (CAS)": "0001697591",
    "글렌 웰링 (인게이지드)": "0001559771",
    "밸리 포지 캐피탈": "0001697868",
    "린셀 트레인": "0001484150",
    "프란시스 추 (추 어소시에이츠)": "0001389403",
    "가이 스피어 (아쿠아마린 캐피탈)": "0001404599",
    "테리 스미스 (펀드스미스)": "0001567330",
    "AKO 캐피탈": "0001613915",
    "존 아미티지 (에저턴 캐피탈)": "0001581811",
    "로버트 비날 (RV 캐피탈)": "0001607519",
    "단 용핑 (H&H 인베스트먼트)": "0001759760",
    "노버트 루 (펀치 카드)": "0001419050",
    "그레그 알렉산더 (코니퍼)": "0001510444",
    "조쉬 타라소프 (그린리아 레인)": "0001567332",
    "아브람스 바이슨 인베스트먼트": "0001317588",
    "칸 브라더스 그룹": "0000044923",
    "트리플 프론드 파트너스": "0001454502",
    "알렉스 뢰퍼스 (아틀란틱)": "0001015338",
    "아놀드 반 덴 버그 (센추리)": "0000795245",
    "젠슨 인베스트먼트": "0000946647",
    "해리 번 (사운드 쇼어)": "0000885978",
    "월러스 웨이츠 (웨이츠)": "0000783412",
    "메이어스 & 파워": "0000062820",
    "벌칸 밸류 파트너스": "0001585201",
    "프랑수아 로숑 (지베르니)": "0001641864"
}

# ══════════════════════════════════════════════════════════════════
# 종목 영문명 변환 사전 (외부 API 통신 완전 배제)
# ══════════════════════════════════════════════════════════════════
TRANSLATE = {
    "APPLE": "애플 (AAPL)", "BANK AMERICA": "뱅크오브아메리카 (BAC)", "BANK OF AMERICA": "뱅크오브아메리카 (BAC)",
    "AMERICAN EXPRESS": "아메리칸 익스프레스 (AXP)", "COCA COLA": "코카콜라 (KO)", "COCACOLA": "코카콜라 (KO)",
    "CHEVRON": "쉐브론 (CVX)", "OCCIDENTAL PETE": "옥시덴탈 석유 (OXY)", "OCCIDENTAL PETROLEUM": "옥시덴탈 석유 (OXY)",
    "KRAFT HEINZ": "크래프트 하인즈 (KHC)", "MOODYS": "무디스 (MCO)",
    "ALPHABET": "알파벳 (GOOGL)", "AMAZON COM": "아마존 (AMZN)", "AMAZONCOM": "아마존 (AMZN)",
    "MICRON TECHNOLOGY": "마이크론 (MU)", "ALIBABA": "알리바바 (BABA)",
    "BAIDU": "바이두 (BIDU)", "MASTERCARD": "마스터카드 (MA)",
    "VISA": "비자 (V)", "KKR & CO": "KKR (KKR)",
    "CONSTELLATION SOFTWARE": "컨스텔레이션 (CSU)", "O REILLY AUTOMOTIVE": "오라일리 (ORLY)", "OREILLY AUTOMOTIVE": "오라일리 (ORLY)",
    "CHIPOTLE MEXICAN GRILL": "치폴레 (CMG)", "MICROSOFT": "마이크로소프트 (MSFT)",
    "NVIDIA": "엔비디아 (NVDA)", "META PLATFORMS": "메타 (META)"
}

def clean_issuer_name(name):
    clean = name.upper().replace(".", "").replace(",", "").replace("&AMP;", "&").replace("'", "").strip()
    clean = re.sub(r'\b(INC|CORP|LTD|PLC|LLC|CO|COMPANY|NEW|DEL|COM|CLASS A|CLASS B|CLASS C|CAP|HLDG|HLDGS|HOLDINGS|HOLDING|GROUP)\b', '', clean).strip()
    
    for key in TRANSLATE:
        if clean.startswith(key):
            return TRANSLATE[key]
    return clean.title()

# ══════════════════════════════════════════════════════════════════
# SEC API 통신 로직 (디도스 차단 방어: 0.35초 강제 딜레이)
# ══════════════════════════════════════════════════════════════════
_last_request_time = 0

def safe_get(url):
    global _last_request_time
    for attempt in range(5):
        elapsed = time.time() - _last_request_time
        if elapsed < 0.35:
            time.sleep(0.35 - elapsed)
        try:
            _last_request_time = time.time()
            r = s.get(url, timeout=15)
            if r.status_code == 200:
                return r
            elif r.status_code in (403, 429):
                wait = min(5 * (2 ** attempt), 60)
                time.sleep(wait)
            else:
                return r
        except Exception as e:
            wait = min(5 * (2 ** attempt), 60)
            time.sleep(wait)
    return None

# ══════════════════════════════════════════════════════════════════
# 13F XML 파싱 (정규식 방탄 파서)
# ══════════════════════════════════════════════════════════════════
def parse_13f_xml(xml_content):
    text = xml_content.decode('utf-8', errors='ignore')
    text = re.sub(r'\sxmlns[^>]*', '', text)
    text = re.sub(r'<[a-zA-Z0-9\-]+:', '<', text)
    text = re.sub(r'</[a-zA-Z0-9\-]+:', '</', text)
    
    info_blocks = re.findall(r'<infoTable\b[^>]*>(.*?)</infoTable>', text, re.DOTALL | re.IGNORECASE)
    
    holdings = {}
    total_val = 0
    
    for block in info_blocks:
        issuer_m = re.search(r'<nameOfIssuer[^>]*>(.*?)</nameOfIssuer>', block, re.IGNORECASE)
        if not issuer_m: continue
        issuer = issuer_m.group(1).strip()
        
        val_m = re.search(r'<value[^>]*>(.*?)</value>', block, re.IGNORECASE)
        val_str = val_m.group(1).strip() if val_m else "0"
        try: val = int(float(val_str.replace(',', ''))) * 1000
        except: val = 0
        
        shares_m = re.search(r'<sshPrnamt[^>]*>(.*?)</sshPrnamt>', block, re.IGNORECASE)
        shares_str = shares_m.group(1).strip() if shares_m else "0"
        try: shares = int(float(shares_str.replace(',', '')))
        except: shares = 0
        
        name = clean_issuer_name(issuer)
        
        if name in holdings:
            holdings[name]['value'] += val
            holdings[name]['shares'] += shares
        else:
            holdings[name] = {'name': name, 'value': val, 'shares': shares}
        total_val += val
        
    result_list = []
    for h in holdings.values():
        weight = round((h['value'] / total_val * 100), 2) if total_val > 0 else 0
        h['weight'] = weight
        result_list.append(h)
    result_list.sort(key=lambda x: x['value'], reverse=True)
    return result_list, total_val

# ══════════════════════════════════════════════════════════════════
# XML 파일 전수 검사 로직 (실패 근본 원인 해결)
# ══════════════════════════════════════════════════════════════════
def get_valid_13f_holdings(cik):
    sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = safe_get(sub_url)
    
    if not r or r.status_code != 200:
        return [], 0, None
        
    recent = r.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    
    hr_indices = [i for i, f in enumerate(forms) if f.startswith("13F-HR")]
    
    if not hr_indices:
        return [], 0, None
        
    for i in hr_indices[:5]:
        accession = recent["accessionNumber"][i]
        report_date = recent["reportDate"][i]
        accession_no_dash = accession.replace("-", "")
        
        idx_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dash}/index.json"
        idx_r = safe_get(idx_url)
        
        if not idx_r or idx_r.status_code != 200:
            continue
            
        files = idx_r.json().get("directory", {}).get("item", [])
        
        xml_files = [f["name"] for f in files if f["name"].lower().endswith(".xml")]
        
        for xml_file in xml_files:
            xml_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dash}/{xml_file}"
            xml_r = safe_get(xml_url)
            
            if xml_r and xml_r.status_code == 200:
                holdings, total_val = parse_13f_xml(xml_r.content)
                if holdings: 
                    return holdings, total_val, report_date
                            
    return [], 0, None

def gh_get_file():
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}?ref={GH_BRANCH}"
    r = safe_get(url)
    if r and r.status_code == 200:
        return r.json()["sha"]
    return None

def gh_put_file(data, sha):
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}"
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    body = {
        "message": f"us_vips: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "content": base64.b64encode(blob.encode("utf-8")).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha: body["sha"] = sha
    requests.put(url, headers=GH_HEADERS, json=body, timeout=15)

def main():
    sha = gh_get_file()
    portfolios = {}
    failed = []
    total = len(GURUS)
    
    print(f"[시작] 총 {total}명의 거장 포트폴리오 조회를 시작합니다.")
    
    for idx, (guru_name, cik) in enumerate(GURUS.items(), 1):
        print(f"[{idx}/{total}] {guru_name} (CIK: {cik}) 조회 중...")
        try:
            holdings, total_val, report_date = get_valid_13f_holdings(cik)
            
            if holdings:
                portfolios[guru_name] = {
                    "report_date": report_date,
                    "total_value_usd": total_val,
                    "holdings": holdings
                }
                print(f"  → 성공: {len(holdings)}개 종목 확인 (보고일: {report_date})")
            else:
                failed.append(guru_name)
                print(f"  → [실패] 유효한 13F 포트폴리오 문서가 없습니다.")
                
        except Exception as e:
            failed.append(guru_name)
            print(f"  → [오류 발생 건너뜀] {str(e)}")
            
        time.sleep(1.5)
        
        if idx % 10 == 0 and idx < total:
            time.sleep(15)
            
    payload = {
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "portfolios": portfolios
    }
    
    if portfolios:
        gh_put_file(payload, sha)
        print(f"\n[완료] 총 {len(portfolios)}명의 거장 포트폴리오 갱신 및 업로드 성공!")
    else:
        print("\n[실패] 수집된 데이터가 하나도 없습니다.")
        
    if failed:
        print(f"\n[실패 목록]")
        for name in failed:
            print(f"  - {name}")

if __name__ == "__main__":
    main()
