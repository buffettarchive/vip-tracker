"""
fetch_13f.py — 미국 가치투자 거장 13F 공시 수집 (한국판 데이터로마 - 풀버전)
"""

import os, sys, json, time, re, base64
import xml.etree.ElementTree as ET
import datetime as dt
import requests

GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_OWNER   = "buffettarchive"
GH_REPO    = "vip-tracker"
GH_PATH    = "docs/us_vips.json"
GH_BRANCH  = "main"
GH_API     = "https://api.github.com"

# SEC API는 User-Agent에 고유 이메일을 포함할 것을 강력히 요구합니다.
s = requests.Session()
s.headers.update({"User-Agent": "BuffettArchive buffettarchive1@gmail.com"})

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ─────────────────────────────────────────────────────────
# 데이터로마(Dataroma) 슈퍼 인베스터 48인 CIK 총망라
GURUS = {
    "워런 버핏 (버크셔 해서웨이)": "0001067983",
    "마이클 버리 (사이언 에셋)": "0001649339",
    "리 루 (히말라야 캐피탈)": "0001569205",
    "모니시 파브라이 (파브라이 인베스트먼츠)": "0001548760",
    "빌 애크먼 (퍼싱 스퀘어)": "0001336528",
    "데이비드 테퍼 (아팔루사)": "0001006438",
    "스탠리 드러켄밀러 (듀케인)": "0001525287",
    "세스 클라만 (바우포스트 그룹)": "0001061768",
    "하워드 막스 (오크트리 캐피탈)": "0000940517",
    "데이비드 아인혼 (그린라이트)": "0001072971",
    "가이 스피어 (아쿠아마린 캐피탈)": "0001569420",
    "척 아크레 (아크레 캐피탈)": "0001158172",
    "칼 아이칸 (아이칸 캐피탈)": "0000921669",
    "단 롭 (서드 포인트)": "0001040273",
    "체이스 콜먼 (타이거 글로벌)": "0001136363",
    "넬슨 펠츠 (트리안 펀드)": "0001345471",
    "브루스 버코위츠 (페어홈 캐피탈)": "0001083622",
    "스티븐 맨델 (론 파인 캐피탈)": "0001041693",
    "빌 & 멀린다 게이츠 재단": "0001320414",
    "메이슨 호킨스 (사우스이스턴)": "0000868148",
    "리 애인슬리 (매버릭 캐피탈)": "0000939016",
    "크리스 혼 (TCI 펀드)": "0001603508",
    "토마스 루소 (가드너 루소)": "0000862022",
    "도지 앤 콕스": "0000029669",
    "트위디 브라운": "0001009309",
    "루안 커니프 (세쿼이아 펀드)": "0000311471",
    "퍼스트 이글 인베스트먼트": "0001318060",
    "얙트먼 에셋 매니지먼트": "0000906473",
    "테리 스미스 (펀드스미스)": "0001567330",
    "데이비드 에이브럼스 (아브람스 캐피탈)": "0001386403",
    "빌 니그렌 (오크마크 / 해리스)": "0000870233",
    "프렘 왓사 (페어팩스 파이낸셜)": "0000915191",
    "칸 브라더스 그룹": "0001026003",
    "토마스 게이너 (마켈 그룹)": "0001096343",
    "리차드 제나 (제나 인베스트먼트)": "0001390777",
    "존 로저스 (아리엘 인베스트먼트)": "0000881855",
    "아놀드 반 덴 버그 (센추리 매니지먼트)": "0001053150",
    "그린헤이븐 어소시에이츠": "0001062660",
    "써드 애비뉴 매니지먼트": "0000898567",
    "단 용핑 (H&H 인베스트먼트)": "0001763131",
    "노버트 루 (펀치 카드 매니지먼트)": "0001509993",
    "팻 도시 (도시 애셋 매니지먼트)": "0001605634",
    "크리스토퍼 블룸스트란 (셈퍼 아우구스투스)": "0001452932",
    "프란시스 추 (추 어소시에이츠)": "0001222472",
    "프랑수아 로숑 (지베르니 캐피탈)": "0001518428",
    "로버트 비날 (RV 캐피탈)": "0001607519",
    "조쉬 타라소프 (그린리아 레인)": "0001567332",
    "밸류액트 캐피탈": "0001130626"
}
# ─────────────────────────────────────────────────────────

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
    clean = name.upper().replace(".", "").replace(",", "").strip()
    for key in TRANSLATE:
        if clean.startswith(key):
            return TRANSLATE[key]
    return clean

def get_latest_13f_xml_url(cik):
    sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    r = s.get(sub_url, timeout=15)
    
    if r.status_code != 200:
        print(f"  [경고] SEC API 거부 (응답코드: {r.status_code})")
        return None, None
    
    recent = r.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    
    for i, form in enumerate(forms):
        if form.startswith("13F-HR"):
            accession = recent["accessionNumber"][i]
            report_date = recent["reportDate"][i]
            accession_no_dash = accession.replace("-", "")
            
            idx_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dash}/index.json"
            idx_r = s.get(idx_url, timeout=15)
            if idx_r.status_code == 200:
                files = idx_r.json().get("directory", {}).get("item", [])
                for file in files:
                    name = file["name"].lower()
                    if name.endswith(".xml") and "primary_doc" not in name:
                        xml_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dash}/{file['name']}"
                        return xml_url, report_date
            break
    return None, None

def parse_13f_xml(xml_content):
    text = xml_content.decode('utf-8', errors='ignore')
    text = re.sub(r'\sxmlns(?::[a-zA-Z0-9\-]+)?="[^"]+"', '', text)
    text = re.sub(r'<(/?)[a-zA-Z0-9\-]+:', r'<\1', text)
    
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        print(f"  [오류] XML 파싱 실패: {e}")
        return [], 0

    holdings = {}
    total_val = 0
    
    for info in root.findall('.//infoTable'):
        issuer = info.findtext('nameOfIssuer')
        if not issuer: continue
        
        name = clean_issuer_name(issuer)
        val_str = info.findtext('value') or "0"
        val = int(float(val_str)) * 1000
        
        shrs_el = info.find('.//shrsOrPrnAmt/sshPrnamt')
        shares = int(float(shrs_el.text)) if (shrs_el is not None and shrs_el.text) else 0
        
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

def gh_get_file():
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}?ref={GH_BRANCH}"
    r = s.get(url, headers=GH_HEADERS, timeout=15)
    if r.status_code == 200:
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
    s.put(url, headers=GH_HEADERS, json=body, timeout=15)

def main():
    try:
        sha = gh_get_file()
        portfolios = {}
        
        for guru_name, cik in GURUS.items():
            print(f"[scan] {guru_name} (CIK: {cik}) 조회 중...")
            xml_url, report_date = get_latest_13f_xml_url(cik)
            
            if xml_url:
                r = s.get(xml_url, timeout=20)
                if r.status_code == 200:
                    holdings, total_val = parse_13f_xml(r.content)
                    portfolios[guru_name] = {
                        "report_date": report_date,
                        "total_value_usd": total_val,
                        "holdings": holdings
                    }
                    print(f"  → 성공: {len(holdings)}개 종목 확인 (보고일: {report_date})")
                
                # SEC 서버 차단을 막기 위해 한 번 조회 후 반드시 1초씩 휴식
                time.sleep(1) 
                
        payload = {
            "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "portfolios": portfolios
        }
        
        if portfolios:
            gh_put_file(payload, sha)
            print(f"\n[완료] 총 {len(portfolios)}명의 거장 포트폴리오 갱신 및 업로드 성공!")
        else:
            print("\n[실패] 수집된 포트폴리오 데이터가 없습니다.")
            
    except Exception as e:
        print(f"[치명적 오류 발생] {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
