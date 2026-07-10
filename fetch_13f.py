"""
fetch_13f.py — 미국 가치투자 거장 13F 공시 수집 (84명 풀버전 & SEC 차단 완벽 우회)
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
# SEC는 User-Agent가 없거나 불량하면 403 에러를 냅니다.
s.headers.update({
    "User-Agent": "BuffettArchive buffettarchive1@gmail.com",
    "Accept-Encoding": "gzip, deflate"
})

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# 데이터로마 슈퍼 인베스터 84명 풀 리스트
GURUS = {
    "마이클 버리 (사이언 에셋)": "0001649339",
    "워런 버핏 (버크셔 해서웨이)": "0001067983",
    "빌 애크먼 (퍼싱 스퀘어)": "0001336528",
    "세스 클라만 (바우포스트 그룹)": "0001061768",
    "리 루 (히말라야 캐피탈)": "0001569205",
    "모니시 파브라이 (달랄 스트리트)": "0001548760",
    "데이비드 테퍼 (아팔루사)": "0001006438",
    "스탠리 드러켄밀러 (듀케인)": "0001525287",
    "가이 스피어 (아쿠아마린)": "0001569420",
    "하워드 막스 (오크트리)": "0000940517",
    "단 용핑 (H&H 인베스트먼트)": "0001763131",
    "아브람스 바이슨 인베스트먼트": "0001438363",
    "넬슨 펠츠 (트리안 펀드)": "0001345471",
    "리 애인슬리 (매버릭 캐피탈)": "0000939016",
    "바이킹 글로벌 (안드레아스 할보센)": "0001103804",
    "밸류액트 캐피탈": "0001130626",
    "데이비드 아인혼 (그린라이트)": "0001072971",
    "칼 아이칸 (아이칸 캐피탈)": "0000921669",
    "브루스 버코위츠 (페어홈)": "0001083622",
    "빌 니그렌 (오크마크 펀드)": "0000870233",
    "빌 & 멀린다 게이츠 재단": "0001320414",
    "노버트 루 (펀치 카드)": "0001509993",
    "헨리 엘렌보겐 (듀러블 캐피탈)": "0001788775",
    "크리스토퍼 블룸스트란 (셈퍼 아우구스투스)": "0001452932",
    "메이슨 호킨스 (사우스이스턴)": "0000868148",
    "글렌 그린버그 (브레이브 워리어)": "0001549429",
    "단 롭 (서드 포인트)": "0001040273",
    "스티븐 맨델 (론 파인)": "0001041693",
    "알렉스 뢰퍼스 (아틀란틱)": "0001010300",
    "밸리 포지 캐피탈": "0001614748",
    "데이비드 롤프 (웨지우드)": "0001053648",
    "체이스 콜먼 (타이거 글로벌)": "0001136363",
    "글렌 웰링 (인게이지드 캐피탈)": "0001560383",
    "클리포드 소신 (CAS 인베스트먼트)": "0001560943",
    "알타록 파트너스": "0001600742",
    "프랑수아 로숑 (지베르니 캐피탈)": "0001518428",
    "레온 쿠퍼만 (오메가 어드바이저스)": "0001010574",
    "아놀드 반 덴 버그 (센추리 매니지먼트)": "0001053150",
    "브라이언 로렌스 (오크클리프)": "0001331006",
    "빌 밀러 (밀러 밸류 파트너스)": "0000820124",
    "팻 도시 (도시 애셋)": "0001605634",
    "크리스 혼 (TCI 펀드)": "0001603508",
    "AKO 캐피탈": "0001613915",
    "테리 스미스 (펀드스미스)": "0001567330",
    "프렘 왓사 (페어팩스)": "0000915191",
    "힐만 캐피탈 매니지먼트": "0001099684",
    "트리플 프론드 파트너스": "0001770630",
    "톰 밴크로프트 (마카이라)": "0001423851",
    "루안 커니프 (세쿼이아 펀드)": "0000311471",
    "그레그 알렉산더 (코니퍼 매니지먼트)": "0001510444",
    "존 로저스 (아리엘 인베스트먼트)": "0000881855",
    "데이비드 에이브럼스 (아브람스 캐피탈)": "0001386403",
    "척 아크레 (아크레 캐피탈)": "0001158172",
    "퍼스트 이글 인베스트먼트": "0001318060",
    "데니스 홍 (쇼스프링 파트너스)": "0001640102",
    "사라 케터러 (코즈웨이 캐피탈)": "0001158227",
    "월러스 웨이츠 (웨이츠 인베스트먼트)": "0000806689",
    "도지 앤 콕스": "0000029669",
    "프란시스 추 (추 어소시에이츠)": "0001222472",
    "사만다 맥레모어 (페이션트 캐피탈)": "0001815198",
    "폴렌 캐피탈": "0001026006",
    "퍼스트 퍼시픽 어드바이저스": "0000812011",
    "메이어스 & 파워 펀드": "0000062820",
    "써드 애비뉴 매니지먼트": "0000898567",
    "존 아미티지 (에저턴 캐피탈)": "0001158652",
    "토마스 루소 (가드너 루소)": "0000862022",
    "벌칸 밸류 파트너스": "0001487602",
    "로버트 비날 (RV 캐피탈)": "0001607519",
    "조쉬 타라소프 (그린리아 레인)": "0001567332",
    "칸 브라더스 그룹": "0001026003",
    "해리 번 (사운드 쇼어)": "0000940381",
    "윌리엄 폰 뮈플링 (칸티용)": "0001306354",
    "크리스토퍼 데이비스 (데이비스 어드바이저스)": "0001037750",
    "트위디 브라운": "0001009309",
    "뮬렌캠프": "0000201886",
    "젠슨 인베스트먼트": "0001000650",
    "스티븐 체크 (체크 캐피탈)": "0000908816",
    "토마스 게이너 (마켈 그룹)": "0001096343",
    "토레이 펀드": "0000890250",
    "얙트먼 에셋 매니지먼트": "0000906473",
    "린셀 트레인": "0001340122",
    "리차드 제나 (제나 인베스트먼트)": "0001390777",
    "데이비드 카츠 (매트릭스 애셋)": "0001020416",
    "로버트 올스타인 (올스타인 캐피탈)": "0001004128",
    "그린헤이븐 어소시에이츠": "0001062660"
}

TRANSLATE = {
    "APPLE INC": "애플 (AAPL)",
    "BANK AMERICA CORP": "뱅크오브아메리카 (BAC)",
    "AMERICAN EXPRESS CO": "아메리칸 익스프레스 (AXP)",
    "COCA COLA CO": "코카콜라 (KO)",
    "CHEVRON CORP NEW": "쉐브론 (CVX)",
    "OCCIDENTAL PETE CORP": "옥시덴탈 석유 (OXY)",
    "KRAFT HEINZ CO": "크래프트 하인즈 (KHC)",
    "MOODYS CORP": "무디스 (MCO)",
    "ALPHABET INC": "알파벳 (GOOGL)",
    "AMAZON COM INC": "아마존 (AMZN)",
    "MICRON TECHNOLOGY INC": "마이크론 (MU)",
    "ALIBABA GROUP HOLDING LTD": "알리바바 (BABA)",
    "BAIDU INC": "바이두 (BIDU)",
    "MASTERCARD INC": "마스터카드 (MA)",
    "VISA INC": "비자 (V)",
    "KKR & CO INC": "KKR (KKR)",
    "CONSTELLATION SOFTWARE INC": "컨스텔레이션 (CSU)",
    "O REILLY AUTOMOTIVE INC": "오라일리 오토모티브 (ORLY)",
    "CHIPOTLE MEAT COM": "치폴레 (CMG)",
    "MICROSOFT CORP": "마이크로소프트 (MSFT)",
    "NVIDIA CORP": "엔비디아 (NVDA)",
    "META PLATFORMS INC": "메타 (META)"
}

def clean_issuer_name(name):
    clean = name.upper().replace(".", "").replace(",", "").replace("&AMP;", "&").strip()
    for key in TRANSLATE:
        if clean.startswith(key):
            return TRANSLATE[key]
    return clean

# SEC 서버 차단을 우회하기 위한 무적의 HTTP 요청 함수
def safe_get(url):
    for attempt in range(5):
        try:
            r = s.get(url, timeout=15)
            if r.status_code == 200:
                return r
            elif r.status_code in (403, 429):
                print(f"    [경고] SEC 서버 차단 감지 (코드 {r.status_code}). 5초 대기 후 재시도... ({attempt+1}/5)")
                time.sleep(5)
            else:
                return r
        except Exception as e:
            print(f"    [네트워크 에러] {e}. 5초 후 재시도... ({attempt+1}/5)")
            time.sleep(5)
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
        try:
            val = int(float(val_str.replace(',', ''))) * 1000
        except:
            val = 0
            
        shares_m = re.search(r'<[a-zA-Z0-9_:-]*sshPrnamt[^>]*>(.*?)</[a-zA-Z0-9_:-]*sshPrnamt>', block, re.IGNORECASE)
        shares_str = shares_m.group(1).strip() if shares_m else "0"
        try:
            shares = int(float(shares_str.replace(',', '')))
        except:
            shares = 0
            
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

def get_valid_13f_holdings(cik):
    sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = safe_get(sub_url)
    
    if not r or r.status_code != 200:
        return [], 0, None
    
    recent = r.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    
    for i, form in enumerate(forms):
        if form.startswith("13F-HR"):
            accession = recent["accessionNumber"][i]
            report_date = recent["reportDate"][i]
            accession_no_dash = accession.replace("-", "")
            
            idx_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dash}/index.json"
            idx_r = safe_get(idx_url)
            
            if idx_r and idx_r.status_code == 200:
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
                            
                if xml_file:
                    xml_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dash}/{xml_file}"
                    xml_r = safe_get(xml_url)
                    
                    if xml_r and xml_r.status_code == 200:
                        holdings, total_val = parse_13f_xml(xml_r.content)
                        if holdings: 
                            return holdings, total_val, report_date
                        else:
                            print(f"    [건너뜀] {report_date} 공시 내용이 없어 이전 분기를 탐색합니다.")
                            
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
    
    print(f"[시작] 총 {len(GURUS)}명의 거장 포트폴리오 조회를 시작합니다.")
    
    for guru_name, cik in GURUS.items():
        print(f"[scan] {guru_name} 조회 중...")
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
                print(f"  → [실패] 유효한 포트폴리오를 찾을 수 없습니다.")
                
        except Exception as e:
            print(f"  → [치명적 오류] {str(e)} - 건너뜁니다.")
            
        # 디도스로 오해받지 않기 위한 필수 안전 대기 시간
        time.sleep(1.5)
            
    payload = {
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "portfolios": portfolios
    }
    
    if portfolios:
        gh_put_file(payload, sha)
        print(f"\n[완료] 총 {len(portfolios)}명의 거장 데이터가 성공적으로 업로드되었습니다!")

if __name__ == "__main__":
    main()
