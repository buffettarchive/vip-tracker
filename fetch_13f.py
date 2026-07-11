"""
fetch_13f.py — 미국 가치투자 거장 13F 공시 수집 (네이버 API 실시간 연동 완벽 자동화)
"""

import os, sys, json, time, re, base64
import datetime as dt
import requests
import urllib.parse

GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_OWNER   = "buffettarchive"
GH_REPO    = "vip-tracker"
GH_PATH    = "docs/us_vips.json"
GH_BRANCH  = "main"
GH_API     = "https://api.github.com"

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Encoding": "gzip, deflate"
})

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ══════════════════════════════════════════════════════════════════
# CIK 최종 교정본 (13F 제출 투자자문사 기준 68명)
# ══════════════════════════════════════════════════════════════════
GURUS = {
    "마이클 버리 (사이언 에셋)": "0001649339",
    "워런 버핏 (버크셔 해서웨이)": "0001067983",
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
    "리차드 제나 (제나 인베스트먼트)": "0001390777",
    "모니시 파브라이 (파브라이 인베스트먼트)": "0001549575",
    "데이비드 테퍼 (아팔루사)": "0001656456",
    "스탠리 드러켄밀러 (듀케인)": "0001536411",
    "하워드 막스 (오크트리)": "0001535472",
    "데이비드 아인혼 (그린라이트)": "0001079114",
    "밸류액트 캐피탈": "0001397545",
    "빌 & 멀린다 게이츠 재단 (캐스케이드)": "0001166559",
    "체이스 콜먼 (타이거 글로벌)": "0001167483",
    "스티븐 맨델 (론 파인)": "0001061165",
    "리 애인슬리 (매버릭 캐피탈)": "0001010649",
    "브루스 버코위츠 (페어홈)": "0001056831",
    "빌 니그렌 (해리스 어소시에이츠)": "0000804550",
    "글렌 그린버그 (브레이브 워리어)": "0001576428",
    "메이슨 호킨스 (사우스이스턴)": "0000807985",
    "척 아크레 (아크레 캐피탈)": "0001112520",
    "도지 앤 콕스": "0000315066",
    "존 로저스 (아리엘 인베스트먼트)": "0001113148",
    "크리스 혼 (TCI 펀드)": "0001647251",
    "퍼스트 이글 인베스트먼트": "0000810958",
    "데이비드 에이브럼스 (아브람스 캐피탈)": "0001358706",
    "크리스토퍼 데이비스 (데이비스 어드바이저스)": "0000353184",
    "트위디 브라운": "0000732905",
    "토마스 루소 (가드너 루소)": "0000860643",
    "데이비드 롤프 (웨지우드)": "0000859804",
    "윌리엄 폰 뮈플링 (칸티용)": "0001279936",
    "퍼스트 퍼시픽 어드바이저스": "0001377581",
    "레온 쿠퍼만 (오메가)": "0000898202",
    "사라 케터러 (코즈웨이)": "0001211513",
    "헨리 엘렌보겐 (듀러블 캐피탈)": "0001798849",
    "데니스 홍 (쇼스프링)": "0001766908",
    "데이비드 카츠 (매트릭스)": "0001016287",
    "크리스토퍼 블룸스트란 (셈퍼 아우구스투스)": "0001115373",
    "루안 커니프 (세쿼이아)": "0001720792",
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
    "프란시스 추 (추 어소시에이츠)": "0001389403",
    "글렌 웰링 (인게이지드)": "0001559771",
    "밸리 포지 캐피탈": "0001697868",
    "린셀 트레인": "0001484150",
}

# ══════════════════════════════════════════════════════════════════
# 네이버 금융 자동완성 API를 활용한 실시간 번역 엔진 (메모리 캐시 적용)
# ══════════════════════════════════════════════════════════════════
TRANSLATION_CACHE = {}

def get_korean_name_from_naver(eng_name):
    if not eng_name:
        return ""
        
    # 이미 검색했던 종목이면 네이버에 묻지 않고 캐시에서 즉시 반환 (속도 극대화)
    if eng_name in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[eng_name]
        
    url = f"https://ac.finance.naver.com/ac?q={urllib.parse.quote(eng_name)}&q_enc=utf-8&st=111&r_format=json&t_koreng=1"
    
    try:
        r = s.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            if items and len(items[0]) > 0:
                match = items[0][0]
                if len(match) >= 2:
                    ticker = match[0]
                    kor_name = match[1]
                    # 결과값에 한글이 정상적으로 포함되어 있는지 검증
                    if re.search('[가-힣]', kor_name):
                        result = f"{kor_name} ({ticker})"
                        TRANSLATION_CACHE[eng_name] = result
                        time.sleep(0.1) # IP 차단 방지용 미세 딜레이
                        return result
    except:
        pass
        
    # 네이버에도 안 나오는 초소형 마이너 종목은 깔끔한 영문 대소문자로 변환하여 반환
    fallback_name = eng_name.title()
    TRANSLATION_CACHE[eng_name] = fallback_name
    time.sleep(0.1)
    return fallback_name

def clean_and_translate_issuer(raw_name):
    # 1. 쓸데없는 13F 꼬리표 싹둑 자르기 (가장 지저분한 것들 모두 포함)
    clean = raw_name.upper().replace(".", "").replace(",", "").replace("&AMP;", "&").replace("'", "").strip()
    clean = re.sub(r'\b(INC|CORP|LTD|PLC|LLC|CO|COMPANY|NEW|DEL|COM|CLASS A|CLASS B|CLASS C|CAP|HLDG|HLDGS|HOLDINGS|HOLDING|GROUP|STK|CL A|CL B|CL C|SER A|SER B|SPONSORED|ADR|ADS|SHS)\b', '', clean).strip()
    
    # 2. 1차 네이버 API 검색
    translated = get_korean_name_from_naver(clean)
    
    # 3. 만약 네이버 검색에 실패했다면 (이름이 너무 길어서 안 나오는 경우 대비) -> 첫 단어만 떼서 2차 검색
    if translated == clean.title() and " " in clean:
        first_word = clean.split(" ")[0]
        if len(first_word) > 2:
            translated_fallback = get_korean_name_from_naver(first_word)
            if translated_fallback != first_word.title():
                return translated_fallback
                
    return translated

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
                print(f"    [경고] SEC 차단 감지 ({r.status_code}). {wait}초 대기 후 재시도... ({attempt+1}/5)")
                time.sleep(wait)
            else:
                return r
        except Exception as e:
            wait = min(5 * (2 ** attempt), 60)
            print(f"    [에러] 네트워크 오류. {wait}초 대기... ({attempt+1}/5)")
            time.sleep(wait)
    return None

def parse_13f_xml(xml_content):
    text = xml_content.decode('utf-8', errors='ignore')
    text = re.sub(r'\sxmlns[^>]*', '', text)
    text = re.sub(r'<[a-zA-Z0-9\-]+:', '<', text)
    text = re.sub(r'</[a-zA-Z0-9\-]+:', '</', text)
    info_blocks = re.findall(r'<[a-zA-Z0-9_:-]*infoTable\b[^>]*>(.*?)</[a-zA-Z0-9_:-]*infoTable>', text, re.DOTALL | re.IGNORECASE)
    
    holdings = {}
    total_val = 0
    
    for block in info_blocks:
        issuer_m = re.search(r'<[a-zA-Z0-9_:-]*nameOfIssuer[^>]*>(.*?)</[a-zA-Z0-9_:-]*nameOfIssuer>', block, re.IGNORECASE)
        if not issuer_m: continue
        issuer = issuer_m.group(1).strip()
        
        val_m = re.search(r'<[a-zA-Z0-9_:-]*value[^>]*>(.*?)</[a-zA-Z0-9_:-]*value>', block, re.IGNORECASE)
        val_str = val_m.group(1).strip() if val_m else "0"
        try: val = int(float(val_str.replace(',', ''))) * 1000
        except: val = 0
        
        shares_m = re.search(r'<[a-zA-Z0-9_:-]*sshPrnamt[^>]*>(.*?)</[a-zA-Z0-9_:-]*sshPrnamt>', block, re.IGNORECASE)
        shares_str = shares_m.group(1).strip() if shares_m else "0"
        try: shares = int(float(shares_str.replace(',', '')))
        except: shares = 0
        
        # 완전 자동화된 네이버 API 번역 엔진 통과
        name = clean_and_translate_issuer(issuer)
        
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

def get_valid_13f_holdings(cik):
    sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = safe_get(sub_url)
    if not r or r.status_code != 200:
        return [], 0, None
        
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    hr_indices = [i for i, f in enumerate(forms) if f.startswith("13F-HR")]
    
    if not hr_indices:
        return [], 0, None
        
    for i in hr_indices[:3]:
        accession = recent["accessionNumber"][i]
        report_date = recent["reportDate"][i]
        accession_no_dash = accession.replace("-", "")
        cik_int = int(cik)
        idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dash}/index.json"
        idx_r = safe_get(idx_url)
        
        if not idx_r or idx_r.status_code != 200:
            continue
            
        files = idx_r.json().get("directory", {}).get("item", [])
        xml_file = None
        for file in files:
            fname = file["name"].lower()
            if fname.endswith(".xml") and ("infotable" in fname or "info_table" in fname):
                xml_file = file["name"]
                break
                
        if not xml_file:
            for file in files:
                fname = file["name"].lower()
                if fname.endswith(".xml") and "primary_doc" not in fname:
                    xml_file = file["name"]
                    break
                    
        if not xml_file:
            continue
            
        xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dash}/{xml_file}"
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
    
    print(f"[시작] 총 {total}명의 거장 포트폴리오 조회를 시작합니다. (네이버 API 연동 모드)")
    for idx, (guru_name, cik) in enumerate(GURUS.items(), 1):
        print(f"\n[scan {idx}/{total}] {guru_name} (CIK: {cik})")
        try:
            holdings, total_val, report_date = get_valid_13f_holdings(cik)
            if holdings:
                portfolios[guru_name] = {
                    "report_date": report_date,
                    "total_value_usd": total_val,
                    "holdings": holdings
                }
                print(f"  → 성공: {len(holdings)}개 종목 (보고일: {report_date})")
            else:
                failed.append(guru_name)
                print(f"  → [실패] 유효한 포트폴리오 없음")
        except Exception as e:
            failed.append(guru_name)
            print(f"  → [치명적 오류] {str(e)}")
            
        time.sleep(1.5)
        
        if idx % 10 == 0 and idx < total:
            print(f"\n  ⏳ [{idx}/{total}] SEC 디도스 오해 방지 쿨다운 30초...\n")
            time.sleep(30)
            
    payload = {
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "portfolios": portfolios
    }
    
    if portfolios:
        gh_put_file(payload, sha)
        
    print(f"\n{'='*60}")
    print(f"[완료] 성공: {len(portfolios)}명 / 실패: {len(failed)}명 / 총: {total}명")
    if failed:
        print(f"\n[실패 목록]")
        for name in failed:
            print(f"  - {name}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
