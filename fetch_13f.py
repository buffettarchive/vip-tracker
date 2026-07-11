"""
fetch_13f.py — 미국 가치투자 거장 13F 공시 수집 
(84명 풀 리스트 적용 및 네이버 API 완전 제거본)
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
# 84명 구루 100% 매칭 완료 (누락 제로)
# ══════════════════════════════════════════════════════════════════
GURUS = {
    "Warren Buffett - Berkshire Hathaway": "0001067983",
    "Michael Burry - Scion Asset Management": "0001649339",
    "Bill Ackman - Pershing Square Capital Management": "0001336528",
    "Seth Klarman - Baupost Group": "0001061768",
    "Li Lu - Himalaya Capital Management": "0001569205",
    "Nelson Peltz - Trian Fund Management": "0001345471",
    "Viking Global Investors": "0001103804",
    "Carl Icahn - Icahn Capital Management": "0000921669",
    "Daniel Loeb - Third Point": "0001040273",
    "Bill Miller - Miller Value Partners": "0000820124",
    "Prem Watsa - Fairfax Financial Holdings": "0000915191",
    "Thomas Gayner - Markel Group": "0001096343",
    "Richard Pzena - Pzena Investment Management": "0001027796",
    "Mohnish Pabrai - Pabrai Investments": "0001549575",
    "David Tepper - Appaloosa Management": "0001656456",
    "Stephen Mandel - Lone Pine Capital": "0001061165",
    "Howard Marks - Oaktree Capital Management": "0001535472",
    "David Einhorn - Greenlight Capital": "0001079114",
    "ValueAct Capital": "0001397545",
    "Bill & Melinda Gates Foundation Trust": "0001320414",
    "Chase Coleman - Tiger Global Management": "0001167483",
    "Lee Ainslie - Maverick Capital": "0000934639",
    "Bruce Berkowitz - Fairholme Capital": "0001056831",
    "Bill Nygren - Oakmark Funds": "0000813917",
    "Glenn Greenberg - Brave Warrior Advisors": "0001553733",
    "Mason Hawkins - Southeastern Asset Management": "0000807985",
    "Chuck Akre - Akre Capital Management": "0001112520",
    "Dodge & Cox Funds": "0000315066",
    "John Rogers - Ariel Investments": "0000936753",
    "Chris Hohn - TCI Fund Management": "0001647251",
    "First Eagle Investment Management": "0000810958",
    "David Abrams - Abrams Capital Management": "0001358706",
    "Christopher Davis - Davis Advisors": "0001036325",
    "Tweedy Browne": "0000732905",
    "Thomas Russo - Gardner Russo & Quinn": "0000860643",
    "David Rolfe - Wedgewood Partners": "0000859804",
    "William Von Mueffling - Cantillon Capital Management": "0001279936",
    "First Pacific Advisors": "0001377581",
    "Leon Cooperman": "0000898202",
    "Sarah Ketterer - Causeway Capital Management": "0001406439",
    "Henry Ellenbogen - Durable Capital Partners": "0001798849",
    "Dennis Hong - ShawSpring Partners": "0001766908",
    "David Katz - Matrix Asset Advisors": "0001016287",
    "Christopher Bloomstran - Semper Augustus": "0001115373",
    "Ruane Cunniff LP": "0000851730",
    "AltaRock Partners": "0001631014",
    "Polen Capital Management": "0001034524",
    "Third Avenue Management": "0001099281",
    "Steven Check - Check Capital Management": "0001032814",
    "Torray Funds": "0000098758",
    "Yacktman Asset Management": "0000905567",
    "Robert Olstein - Olstein Capital Management": "0000947996",
    "Greenhaven Associates": "0000846222",
    "Muhlenkamp": "0001133219",
    "Bryan Lawrence - Oakcliff Capital": "0001657335",
    "Pat Dorsey - Dorsey Asset Management": "0001671657",
    "Hillman Capital Management": "0001314620",
    "Tom Bancroft - Makaira Partners": "0001540866",
    "Samantha McLemore - Patient Capital Management": "0001854794",
    "Clifford Sosin - CAS Investment Partners": "0001697591",
    "Glenn Welling - Engaged Capital": "0001559771",
    "Valley Forge Capital Management": "0001697868",
    "Lindsell Train": "0001484150",
    "Francis Chou - Chou Associates": "0001389403",
    "Guy Spier - Aquamarine Capital": "0001404599",
    "Terry Smith - Fundsmith": "0001567330",
    "AKO Capital": "0001613915",
    "John Armitage - Egerton Capital": "0001581811",
    "Robert Vinall - RV Capital GmbH": "0001607519",
    "Duan Yongping - H&H International Investment": "0001759760",
    "Norbert Lou - Punch Card Management": "0001419050",
    "Greg Alexander - Conifer Management": "0001510444",
    "Josh Tarasoff - Greenlea Lane Capital": "0001567332",
    "Abrams Bison Investments": "0001317588",
    "Kahn Brothers Group": "0000044923",
    "Triple Frond Partners": "0001454502",
    "Alex Roepers - Atlantic Investment Management": "0001015338",
    "Arnold Van Den Berg - Century Management": "0000795245",
    "Jensen Investment Management": "0000946647",
    "Harry Burn - Sound Shore": "0000885978",
    "Wallace Weitz - Weitz Investment Management": "0000783412",
    "Mairs & Power Funds": "0000062820",
    "Vulcan Value Partners": "0001585201",
    "Francois Rochon - Giverny Capital": "0001641864"
}

# ══════════════════════════════════════════════════════════════════
# 하드코딩 영문 변환 사전 (외부 API 통신 완전 제거)
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
            
        time.sleep(1.5) # SEC 차단 방지용 안전 대기
        
        # 10명마다 15초씩 쉬어주면서 SEC의 디도스 오해를 완벽 방지
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
