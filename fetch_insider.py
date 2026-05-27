"""
fetch_insider.py  (v2 · 코스닥 내부자 '장내/장외 매수'만 정확히 추적)
─────────────────────────────────────────────────────────────
1단계: list로 코스닥(corp_cls=K) 내부자보고(D002) 후보 회사 수집
2단계: elestock로 회사별 변동을 받아 소유증가(매수 후보)만 1차 선별
3단계: 후보의 공시 본문(document.xml)을 읽어 '세부변동내역'의
       보고사유를 확인 → '장내매수/장외매수'가 있는 것만 최종 채택.
       (증여·상속·신규상장·전환·인수성 취득 등은 제외)
       취득단가와 매수금액(증감수×단가)도 함께 기록.

본문은 매수 후보에 한해서만 읽으므로 부담을 최소화한다.
"""

import os
import io
import re
import sys
import json
import time
import zipfile
import base64
import datetime as dt

import requests

DART_KEY = os.environ["DART_API_KEY"]
GH_TOKEN = os.environ["GH_TOKEN"]

GH_OWNER = "buffettarchive"
GH_REPO = "vip-tracker"
GH_PATH = "docs/insider.json"     # 운용사(data.json)와 분리된 별도 파일
GH_BRANCH = "main"

DART = "https://opendart.fss.or.kr/api"
GH_API = "https://api.github.com"

SCAN_DAYS = 3
INSIDER_REPORT = "임원ㆍ주요주주특정증권등소유상황보고서"

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker-insider/1.0"})
GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def dart(endpoint, **params):
    params["crtfc_key"] = DART_KEY
    for i in range(3):
        try:
            return s.get(f"{DART}/{endpoint}", params=params, timeout=20).json()
        except Exception as e:  # noqa
            print(f"[retry {i}] {endpoint}: {e}", file=sys.stderr)
            time.sleep(1.5 * (i + 1))
    return {"status": "999", "list": []}


def to_int(v):
    try:
        return int(str(v).replace(",", "").replace("+", "").strip())
    except (ValueError, TypeError):
        return 0


# 진짜 매수로 인정할 취득방법 키워드
BUY_KEYWORDS = ["장내매수", "장외매수", "장내매매", "시간외매매", "시간외매수"]
# 명백히 매수가 아닌 것(있으면 후보에서 제외 보조판단용)
NON_BUY_KEYWORDS = ["증여", "상속", "신규상장", "전환", "주식배당", "무상", "교환", "수증", "합병", "현물출자", "스톡옵션", "주식매수선택권"]


def parse_insider_doc(rcept_no):
    """
    내부자 보고 본문(document.xml=zip)에서 '세부변동내역'을 읽어
    장내/장외 매수가 있는지 판정. 매수 증감수와 평균단가도 추출.
    반환: {"is_buy": bool, "buy_qty": int, "avg_price": int|None, "method": str}
    """
    try:
        r = s.get(f"{DART}/document.xml",
                  params={"crtfc_key": DART_KEY, "rcept_no": rcept_no}, timeout=30)
        if r.headers.get("content-type", "").startswith("application/json"):
            return {}
        z = zipfile.ZipFile(io.BytesIO(r.content))
        name = max(z.namelist(), key=lambda n: z.getinfo(n).file_size)
        raw = z.read(name)
        text = None
        for enc in ("utf-8", "euc-kr", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="ignore")

        plain = re.sub(r"<[^>]+>", " ", text)
        plain = re.sub(r"&[a-zA-Z#0-9]+;", " ", plain)
        plain = re.sub(r"\s+", " ", plain)

        # 세부변동내역에 장내/장외 매수가 한 번이라도 등장하는지
        has_buy = any(k in plain for k in BUY_KEYWORDS)
        method = next((k for k in BUY_KEYWORDS if k in plain), "")

        # 평균 취득단가 추정: '장내매수' 줄들의 단가 숫자를 평균
        prices = []
        for m in re.finditer(r"(장내매수|장외매수|시간외매매)\D{0,40}?([\d,]{3,})\s+([\d,]{2,})", plain):
            p = to_int(m.group(3))
            if 0 < p < 10_000_000:
                prices.append(p)
        avg_price = round(sum(prices) / len(prices)) if prices else None

        return {"is_buy": has_buy, "avg_price": avg_price, "method": method}
    except Exception as e:  # noqa
        print(f"[warn] 내부자 본문 파싱 실패 {rcept_no}: {e}", file=sys.stderr)
        return {}


def gh_get():
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}?ref={GH_BRANCH}"
    r = s.get(url, headers=GH_HEADERS, timeout=20)
    if r.status_code == 200:
        j = r.json()
        return json.loads(base64.b64decode(j["content"]).decode("utf-8")), j["sha"]
    return {"disclosures": [], "last_seen": ""}, None


def gh_put(payload, sha):
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}"
    body = {
        "message": f"insider: auto update {payload['updated_at']}",
        "content": base64.b64encode(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha:
        body["sha"] = sha
    r = s.put(url, headers=GH_HEADERS, data=json.dumps(body), timeout=20)
    if r.status_code not in (200, 201):
        print(f"[ERR] github push {r.status_code}: {r.text}", file=sys.stderr)
        return False
    return True


def main():
    data, sha = gh_get()
    existing = {d["rcept_no"]: d for d in data.get("disclosures", [])}
    last_seen = data.get("last_seen", "") or (max(existing) if existing else "")
    print(f"[info] 기존 {len(existing)}건, 마지막 본 번호={last_seen or '없음'}")

    today = dt.date.today()
    bgn = (today - dt.timedelta(days=SCAN_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    # 1) 코스닥 내부자 보고만 list로 훑어 (회사,접수번호) 후보 수집
    targets = {}        # corp_code -> set(rcept_no)
    meta = {}           # rcept_no -> (corp_name, stock_code)
    max_seen, stop, page = last_seen, False, 1
    while not stop:
        d = dart("list.json", bgn_de=bgn, end_de=end,
                 pblntf_ty="D", pblntf_detail_ty="D002",  # 내부자 소유보고만
                 corp_cls="K",                            # 코스닥만
                 page_no=page, page_count=100, sort="date", sort_mth="desc")
        st = d.get("status")
        if st == "013":
            break
        if st != "000":
            print(f"[warn] list status={st} msg={d.get('message')}", file=sys.stderr)
            break
        for row in d.get("list", []) or []:
            rcept_no = row["rcept_no"]
            if last_seen and rcept_no <= last_seen:
                stop = True
                break
            if rcept_no > max_seen:
                max_seen = rcept_no
            if INSIDER_REPORT not in row.get("report_nm", ""):
                continue
            cc = row.get("corp_code", "")
            if not cc:
                continue
            targets.setdefault(cc, set()).add(rcept_no)
            meta[rcept_no] = (row.get("corp_name", ""), row.get("stock_code", ""))
        tp = int(d.get("total_page", 1) or 1)
        if page >= tp:
            break
        page += 1
        time.sleep(0.2)

    print(f"[info] 코스닥 내부자 보고 후보 회사 {len(targets)}곳")

    # 2) 회사별 elestock 한 번씩 → 해당 접수번호의 '매수(증가)'만 기록
    added = 0
    for cc, rcept_set in targets.items():
        d = dart("elestock.json", corp_code=cc)
        if d.get("status") != "000":
            continue
        for item in d.get("list", []) or []:
            rcept_no = item.get("rcept_no", "")
            if rcept_no not in rcept_set or rcept_no in existing:
                continue
            irds = to_int(item.get("sp_stock_lmp_irds_cnt"))
            if irds <= 0:        # 1차: 소유 증가(매수 후보)만
                continue
            # 2차: 본문에서 장내/장외 매수인지 확인 (정확한 매수 시그널만)
            doc = parse_insider_doc(rcept_no)
            time.sleep(0.25)
            if not doc.get("is_buy"):
                continue  # 장내/장외 매수가 아니면 제외(증여·상속·인수성 등)
            avg_price = doc.get("avg_price")
            buy_amount = (avg_price * irds) if avg_price else None
            corp_name, stock_code = meta.get(rcept_no, (item.get("corp_name", ""), ""))
            existing[rcept_no] = {
                "rcept_no": rcept_no,
                "rcept_dt": item.get("rcept_dt", ""),
                "corp_name": corp_name or item.get("corp_name", ""),
                "stock_code": stock_code,
                "corp_code": cc,
                "repror": item.get("repror", ""),
                "ofcps": item.get("isu_exctv_ofcps", ""),
                "rgist": item.get("isu_exctv_rgist_at", ""),
                "main_shrholdr": item.get("isu_main_shrholdr", ""),
                "irds_cnt": item.get("sp_stock_lmp_irds_cnt", ""),
                "total_cnt": item.get("sp_stock_lmp_cnt", ""),
                "irds_rate": item.get("sp_stock_lmp_irds_rate", ""),
                "hold_rate": item.get("sp_stock_lmp_rate", ""),
                "method": doc.get("method", ""),
                "avg_price": avg_price,
                "buy_amount": buy_amount,
            }
            added += 1
        time.sleep(0.15)

    if added == 0 and max_seen == last_seen:
        print("[info] 새 내부자 매수 없음 — 변경 없이 종료")
        return

    merged = sorted(existing.values(), key=lambda x: x.get("rcept_no", ""), reverse=True)
    payload = {
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="minutes"),
        "market": "KOSDAQ",
        "last_seen": max_seen,
        "disclosures": merged,
    }
    if gh_put(payload, sha):
        print(f"[info] 신규 매수 {added}건 추가 → 총 {len(merged)}건, GitHub 반영 완료")


if __name__ == "__main__":
    main()
