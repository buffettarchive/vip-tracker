"""
fetch_13f.py — 미국 가치투자 거장 13F 공시 수집 (한국판 데이터로마)
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

# 추적할 거장들의 CIK (미국 SEC 고유식별번호)
GURUS = {
    "버크셔 해서웨이 (워런 버핏)": "0001067983",
    "히말라야 캐피탈 (리 루)": "0001569205",
    "파브라이 인베스트먼츠": "0001548760",
    "아크레 캐피탈 (척 아크레)": "0001158172"
}

# 주요 종목 한글 번역 사전
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
    "CHIPOTLE MEAT COM": "치폴레 (CMG)"
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
        if form == "13F-HR":
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
    # XML 네임스페이스 및 접두사 완벽 제거 (파싱 오류 원천 차단)
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
                time.sleep(1)
                
        payload = {
            "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "portfolios": portfolios
        }
        
        if portfolios:
            gh_put_file(payload, sha)
            print("[완료] us_vips.json 갱신 및 업로드 성공!")
        else:
            print("[실패] 수집된 포트폴리오 데이터가 없습니다.")
            
    except Exception as e:
        print(f"[치명적 오류 발생] {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
