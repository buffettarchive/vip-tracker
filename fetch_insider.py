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
MARKETS = [("Y", "KOSPI"), ("K", "KOSDAQ")]  # 코스피, 코스닥

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
        # 본문이 아직 안 올라왔으면 JSON으로 '파일 없음'(status 014)이 옴 → nodoc
        if r.headers.get("content-type", "").startswith("application/json"):
            return {"doc_status": "nodoc"}
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

        has_buy = any(k in plain for k in BUY_KEYWORDS)
        method = next((k for k in BUY_KEYWORDS if k in plain), "")
        # 본문은 있는데 매수 키워드가 없으면 notbuy (증여·상속·인수성 등) → 확정 제외
        return {"doc_status": "buy" if has_buy else "notbuy",
                "is_buy": has_buy, "method": method}
    except Exception as e:  # noqa
        print(f"[warn] 내부자 본문 파싱 실패 {rcept_no}: {e}", file=sys.stderr)
        # 파싱 실패는 일시적일 수 있으니 nodoc 취급(다음 실행 재시도)
        return {"doc_status": "nodoc"}


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

    # 1) 코스피·코스닥 내부자 보고 후보 수집 (last_seen 비교만, max_seen 갱신은 elestock 매칭 후에)
    targets = {}        # corp_code -> set(rcept_no)
    meta = {}           # rcept_no -> (corp_name, stock_code, market)
    candidates = []     # list of rcept_no
    for cls_code, cls_name in MARKETS:
        stop, page = False, 1
        while not stop:
            d = dart("list.json", bgn_de=bgn, end_de=end,
                     pblntf_ty="D", corp_cls=cls_code,
                     page_no=page, page_count=100, sort="date", sort_mth="desc")
            st = d.get("status")
            if st == "013":
                break
            if st != "000":
                print(f"[warn] list({cls_name}) status={st} msg={d.get('message')}", file=sys.stderr)
                break
            for row in d.get("list", []) or []:
                rcept_no = row["rcept_no"]
                if INSIDER_REPORT not in row.get("report_nm", ""):
                    continue
                if last_seen and rcept_no <= last_seen:
                    stop = True
                    break
                cc = row.get("corp_code", "")
                if not cc:
                    continue
                targets.setdefault(cc, set()).add(rcept_no)
                candidates.append(rcept_no)
                meta[rcept_no] = (row.get("corp_name", ""), row.get("stock_code", ""), cls_name)
            tp = int(d.get("total_page", 1) or 1)
            if page >= tp:
                break
            page += 1
            time.sleep(0.2)

    print(f"[info] 내부자 보고 후보 회사 {len(targets)}곳, 접수 {len(candidates)}건 (코스피+코스닥)")

    # 2) 회사별 elestock 호출 → 매칭된 접수번호만 처리
    #    elestock 응답에 아직 없는 후보는 "미처리"로 남겨 last_seen 갱신에서 제외
    added = 0
    resolved_rcepts = set()   # 완전히 처리(수집 or 확정 제외)된 접수번호

    def process_company(cc, rcept_set):
        """elestock 호출 후 매칭된 건을 처리.
        - elestock+본문 모두 확인돼 매수면 → existing 추가, '완료'(resolved) 표시
        - elestock 있고 본문상 매수 아니면 → 제외하되 '완료' 표시(다시 안 봄)
        - elestock에 없거나 본문이 아직 없으면 → '미완료'(보류) → last_seen 안 올림
        """
        nonlocal added
        d = dart("elestock.json", corp_code=cc)
        if d.get("status") != "000":
            return 0   # elestock 호출 실패 → 전부 미완료(보류)
        elestock_map = {it.get("rcept_no",""): it for it in (d.get("list") or [])}
        local_added = 0
        for rcept_no in rcept_set:
            if rcept_no in existing:
                resolved_rcepts.add(rcept_no)   # 이미 수집됨 = 완료
                continue
            item = elestock_map.get(rcept_no)
            if item is None:
                continue   # elestock에 아직 없음 → 미완료(보류)
            irds = to_int(item.get("sp_stock_lmp_irds_cnt"))
            if irds <= 0:
                resolved_rcepts.add(rcept_no)   # 매도/변동없음 = 확정 제외(완료)
                continue
            doc = parse_insider_doc(rcept_no)
            time.sleep(0.25)
            ds = doc.get("doc_status")
            if ds == "nodoc":
                continue   # 본문 아직 없음 → 미완료(보류), 다음 실행 재시도
            if ds == "notbuy":
                resolved_rcepts.add(rcept_no)   # 본문 있고 매수 아님 = 확정 제외(완료)
                continue
            # ds == "buy" → 매수 확정
            corp_name, stock_code, market = meta.get(rcept_no, (item.get("corp_name", ""), "", ""))
            existing[rcept_no] = {
                "rcept_no": rcept_no,
                "rcept_dt": item.get("rcept_dt", ""),
                "corp_name": corp_name or item.get("corp_name", ""),
                "stock_code": stock_code,
                "market": market,
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
            }
            resolved_rcepts.add(rcept_no)   # 매수 수집 완료
            added += 1
            local_added += 1
        return local_added

    # 1차 시도
    for cc, rcept_set in targets.items():
        process_company(cc, rcept_set)
        time.sleep(0.15)

    # 1차에서 처리 못한(미완료) 후보가 있으면 잠깐 대기 후 그 회사들만 재시도
    pending_after_first = [r for r in candidates if r not in resolved_rcepts]
    if pending_after_first:
        retry_targets = {}
        for r in pending_after_first:
            for cc, rs in targets.items():
                if r in rs:
                    retry_targets.setdefault(cc, set()).add(r)
                    break
        print(f"[info] 미반영(본문/elestock 대기) 후보 {len(pending_after_first)}건 — 15초 대기 후 1회 재시도")
        time.sleep(15)
        for cc, rcept_set in retry_targets.items():
            process_company(cc, rcept_set)
            time.sleep(0.15)

    # 3) last_seen 안전 갱신 (핵심):
    #    "완전히 처리(resolved)된 건"만 기준으로 올린다.
    #    아직 본문/elestock가 안 올라온 미완료 건이 있으면, 그 최솟값을 절대 넘지 않게 해서
    #    다음 실행에서 반드시 다시 보도록 한다. (elestock엔 있지만 본문이 없는 경우 누락 방지)
    pending = [r for r in candidates if r not in resolved_rcepts]
    if pending:
        print(f"[info] 본문/elestock 대기 {len(pending)}건 — 다음 실행에서 또 시도")
        # 핵심 규칙: last_seen은 '대기 중 가장 작은 건'보다 반드시 작아야 한다.
        #   기존 last_seen이 이미 그보다 크면(과거 오염), 무시하고 끌어내린다.
        min_pending = min(pending)
        safe = [r for r in resolved_rcepts if r < min_pending]
        if last_seen and last_seen < min_pending:
            safe.append(last_seen)
        if safe:
            new_last_seen = max(safe)
        elif last_seen and last_seen < min_pending:
            new_last_seen = last_seen
        else:
            # 안전 후보 없음 + 기존 last_seen도 오염 → SCAN 범위 직전으로 리셋(다 다시 봄)
            new_last_seen = ""
    else:
        # 모두 처리됨 → 후보 중 최대까지 last_seen 올림
        all_seen = list(resolved_rcepts) + ([last_seen] if last_seen else [])
        new_last_seen = max(all_seen) if all_seen else last_seen

    if added == 0 and new_last_seen == last_seen:
        print("[info] 새 내부자 매수 없음 — 변경 없이 종료")
        return
    max_seen = new_last_seen

    merged = sorted(existing.values(), key=lambda x: x.get("rcept_no", ""), reverse=True)
    payload = {
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="minutes"),
        "market": "KOSPI+KOSDAQ",
        "last_seen": max_seen,
        "disclosures": merged,
    }
    if gh_put(payload, sha):
        print(f"[info] 신규 매수 {added}건 추가 → 총 {len(merged)}건, GitHub 반영 완료")


if __name__ == "__main__":
    main()
