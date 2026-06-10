"""솔브레인 대량보유 공시의 실제 flr_nm 확인"""
import os, time, datetime, requests

DART_KEY = os.environ.get("DART_API_KEY", "")
s = requests.Session()

def dart(**params):
    params["crtfc_key"] = DART_KEY
    return s.get("https://opendart.fss.or.kr/api/list.json", params=params, timeout=20).json()

today = datetime.date.today()
bgn = (today - datetime.timedelta(days=80)).strftime("%Y%m%d")
end = today.strftime("%Y%m%d")

page = 1
while True:
    d = dart(bgn_de=bgn, end_de=end, pblntf_ty="D",
             page_no=page, page_count=100, sort="date", sort_mth="desc")
    if d.get("status") not in ("000",):
        break
    for row in d.get("list", []) or []:
        corp = row.get("corp_name", "")
        # 솔브레인 또는 영문 flr_nm 가진 모든 공시 출력
        flr = row.get("flr_nm", "")
        if "솔브레인" in corp or (not any(c >= '\uac00' and c <= '\ud7a3' for c in flr) and len(flr) > 3):
            print(f"corp={corp} | flr_nm={flr} | report={row.get('report_nm','')} | rcept={row.get('rcept_no','')}")
    tp = int(d.get("total_page", 1) or 1)
    if page >= tp:
        break
    page += 1
    time.sleep(0.15)
print("[done]")
