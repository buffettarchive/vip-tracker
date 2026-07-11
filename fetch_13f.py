"""
fetch_13f.py — 미국 가치투자 거장 13F 공시 수집 (최종 CIK 교정본)
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
# CIK 최종 교정본 — SEC EDGAR 검색 + 웹 크로스체크 완료
# 출처: EFTS 자동탐색 결과 괄호 내 CIK + SEC.gov 직접 확인
# ══════════════════════════════════════════════════════════════════
GURUS = {
    # ── 1차 검증 완료 (기존 정상 작동) ──
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

    # ── 2차 교정 성공 (CIK 변경 후 정상 작동 확인) ──
    "모니시 파브라이 (파브라이 인베스트먼트)": "0001549575",
    "데이비드 테퍼 (아팔루사)": "0001656456",
    "스탠리 드러켄밀러 (듀케인)": "0001536411",
    "하워드 막스 (오크트리)": "0001535472",
    "데이비드 아인혼 (그린라이트)": "0001079114",
    "밸류액트 캐피탈": "0001397545",
    "빌 & 멀린다 게이츠 재단 (캐스케이드)": "0001166559",
    "체이스 콜먼 (타이거 글로벌)": "0001167483",
    "스티븐 맨델 (론 파인)": "0001061165",
    "브루스 버코위츠 (페어홈)": "0001056831",
    "메이슨 호킨스 (사우스이스턴)": "0000807985",
    "척 아크레 (아크레 캐피탈)": "0001112520",
    "도지 앤 콕스": "0000315066",
    "크리스 혼 (TCI 펀드)": "0001647251",
    "퍼스트 이글 인베스트먼트": "0000810958",
    "데이비드 에이브럼스 (아브람스 캐피탈)": "0001358706",
    "트위디 브라운": "0000732905",

    # ── 3차 교정 (EFTS 탐색 + SEC.gov 웹 확인) ──
    "리 애인슬리 (매버릭 캐피탈)": "0000934639",     # sec.gov 직접 확인
    "빌 니그렌 (해리스 어소시에이츠)": "0000813917",  # sec.gov 직접 확인
    "글렌 그린버그 (브레이브 워리어)": "0001553733",  # EFTS 발견
    "존 로저스 (아리엘 인베스트먼트)": "0000936753",  # sec.gov 직접 확인
    "크리스토퍼 데이비스 (데이비스 어드바이저스)": "0001036325",  # EFTS 발견
    "토마스 루소 (가드너 루소)": "0000860643",        # sec.gov 직접 확인
    "데이비드 롤프 (웨지우드)": "0000859804",          # EFTS 발견
    "윌리엄 폰 뮈플링 (칸티용)": "0001279936",       # EFTS 발견
    "퍼스트 퍼시픽 어드바이저스": "0001377581",       # EFTS 발견
    "레온 쿠퍼만 (오메가)": "0000898202",             # fallback 확인, 13F-HR 19건
    "헨리 엘렌보겐 (듀러블 캐피탈)": "0001798849",   # EFTS 발견
    "데니스 홍 (쇼스프링)": "0001766908",             # EFTS 발견
    "데이비드 카츠 (매트릭스)": "0001016287",          # EFTS 발견
    "크리스토퍼 블룸스트란 (셈퍼 아우구스투스)": "0001115373",  # EFTS 발견
    "루안 커니프 (세쿼이아)": "0001720792",            # EFTS 발견
    "알타록 파트너스": "0001631014",                  # EFTS 발견
    "폴렌 캐피탈": "0001034524",                      # sec.gov 직접 확인
    "써드 애비뉴 매니지먼트": "0001099281",            # EFTS 발견
    "스티븐 체크 (체크 캐피탈)": "0001032814",        # fallback 확인, 13F-HR 126건
    "토레이 펀드": "0000098758",                       # EFTS 발견
    "얙트먼 에셋 매니지먼트": "0000905567",            # EFTS 발견
    "로버트 올스타인 (올스타인)": "0000947996",        # fallback 확인, 13F-HR 111건
    "그린헤이븐 어소시에이츠": "0000846222",           # stockzoa CIK 확인
    "뮬렌캠프": "0001133219",                          # EFTS 발견
    "브라이언 로렌스 (오크클리프)": "0001657335",      # EFTS 발견
    "팻 도시 (도시 애셋)": "0001671657",               # EFTS 발견
    "힐만 캐피탈": "0001314620",                       # EFTS 발견
    "톰 밴크로프트 (마카이라)": "0001540866",          # EFTS 발견
    "사만다 맥레모어 (페이션트)": "0001854794",        # EFTS 발견
    "클리포드 소신 (CAS)": "0001697591",              # EFTS 발견
    "글렌 웰링 (인게이지드)": "0001559771",           # EFTS 발견
    "밸리 포지 캐피탈": "0001697868",                 # EFTS 발견
    "린셀 트레인": "0001484150",                       # EFTS 발견 (UK 소재, 13F 미보장)
    "프란시스 추 (추 어소시에이츠)": "0001389403",    # EFTS 발견 (캐나다, 13F 미보장)
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
                print(f"    [경고] SEC 차단 ({r.status_code}). {wait}초 대기... ({attempt+1}/5)")
                time.sleep(wait)
            else:
                return r
        except Exception as e:
            wait = min(5 * (2 ** attempt), 60)
            print(f"    [에러] {e}. {wait}초 대기... ({attempt+1}/5)")
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
        print(f"    [DIAG] submissions 실패 ({r.status_code if r else 'None'})")
        return [], 0, None
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    hr_indices = [i for i, f in enumerate(forms) if f.startswith("13F-HR")]
    if not hr_indices:
        form_types = {}
        for f in forms:
            form_types[f] = form_types.get(f, 0) + 1
        top = sorted(form_types.items(), key=lambda x: -x[1])[:3]
        print(f"    [DIAG] 13F-HR 없음 (폼 {len(forms)}건, 상위: {top})")
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
            else:
                print(f"    [건너뜀] {report_date} 비어있음, 이전 분기 탐색")
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
                print(f"  → [실패]")
        except Exception as e:
            failed.append(guru_name)
            print(f"  → [치명적 오류] {str(e)}")
        time.sleep(1.5)
        if idx % 10 == 0 and idx < total:
            print(f"\n  ⏳ [{idx}/{total}] 쿨다운 30초...\n")
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
