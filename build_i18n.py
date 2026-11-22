"""
build_i18n.py - 영어판 대시보드용 번역 사전(docs/i18n_en.json) 생성

번역 순서
  1. 회사명: DART 고유번호 목록(corpCode.xml)의 공식 영문명, 없으면 기업개황 API(corp_name_eng)
  2. 보고자: 영문이면 그대로, 개인 이름이면 로마자 표기(성씨 예외표 적용),
             법인이면 DART 영문명과 대조, 없으면 DeepL(키가 있을 때), 그래도 없으면 로마자 표기
  3. 직위, 자사주 취득목적과 방법, 운용사 보고사유: 용어집 규칙으로 정규화, 남는 것은 DeepL
  4. 한 번 번역한 결과는 i18n_en.json에 누적 캐시 (새로 생긴 항목만 처리)

환경변수
  DART_API_KEY   필수 (회사 영문명)
  DEEPL_API_KEY  선택 (없으면 규칙 기반 번역과 로마자 표기만 사용)
"""

import os, io, re, json, time, zipfile
import datetime as dt
import xml.etree.ElementTree as ET
import requests

DOCS = "docs"
OUT = os.path.join(DOCS, "i18n_en.json")
DART_KEY = os.environ.get("DART_API_KEY", "")
DEEPL_KEY = os.environ.get("DEEPL_API_KEY", "")
DEEPL_BUDGET = 40000          # 1회 실행당 DeepL 최대 글자 수 (무료 한도 보호)
HANGUL = re.compile(r"[가-힣]")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ══════════════════════════════════════════════════════════════════
# 로마자 표기 (국어의 로마자 표기법, 인명은 음절 단위)
# ══════════════════════════════════════════════════════════════════
CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi",
        "yu", "eu", "ui", "i"]
JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t",
        "ng", "t", "t", "k", "t", "p", "t"]

SURNAME = {
    "김": "Kim", "이": "Lee", "박": "Park", "최": "Choi", "정": "Jung", "강": "Kang", "조": "Cho", "윤": "Yoon",
    "장": "Jang", "임": "Lim", "한": "Han", "오": "Oh", "서": "Seo", "신": "Shin", "권": "Kwon", "황": "Hwang",
    "안": "Ahn", "송": "Song", "전": "Jeon", "홍": "Hong", "유": "Yoo", "고": "Ko", "문": "Moon", "양": "Yang",
    "손": "Son", "배": "Bae", "백": "Baek", "허": "Heo", "남": "Nam", "심": "Shim", "노": "Noh", "하": "Ha",
    "곽": "Kwak", "성": "Sung", "차": "Cha", "주": "Joo", "우": "Woo", "구": "Koo", "민": "Min", "류": "Ryu",
    "나": "Na", "진": "Jin", "지": "Ji", "엄": "Eom", "채": "Chae", "원": "Won", "천": "Cheon", "방": "Bang",
    "공": "Kong", "현": "Hyun", "함": "Ham", "변": "Byun", "염": "Yeom", "여": "Yeo", "추": "Choo", "도": "Do",
    "소": "So", "석": "Seok", "선": "Sun", "설": "Seol", "마": "Ma", "길": "Gil", "연": "Yeon", "위": "Wi",
    "표": "Pyo", "명": "Myung", "기": "Ki", "반": "Ban", "왕": "Wang", "금": "Keum", "옥": "Ok", "육": "Yook",
    "인": "In", "맹": "Maeng", "제": "Je", "모": "Mo", "탁": "Tak", "국": "Kook", "어": "Eo", "은": "Eun",
    "편": "Pyeon", "용": "Yong", "예": "Ye", "경": "Kyung", "봉": "Bong", "사": "Sa", "부": "Boo", "가": "Ka",
    "복": "Bok", "태": "Tae", "목": "Mok", "형": "Hyung", "계": "Kye", "피": "Pi", "두": "Doo", "감": "Kam",
    "음": "Eum", "빈": "Bin", "동": "Dong", "온": "On", "호": "Ho", "범": "Beom", "좌": "Jwa", "승": "Seung",
    "상": "Sang", "갈": "Kal", "라": "Ra", "로": "Ro", "견": "Kyun", "당": "Dang", "란": "Ran", "진": "Jin",
}
SURNAME2 = {"남궁": "Namgoong", "황보": "Hwangbo", "제갈": "Jegal", "선우": "Sunwoo", "독고": "Dokgo",
            "사공": "Sagong", "서문": "Seomun", "동방": "Dongbang"}


def roman_syllables(s, sep=""):
    out = []
    for ch in s:
        c = ord(ch) - 0xAC00
        if 0 <= c < 11172:
            out.append(CHO[c // 588] + JUNG[(c % 588) // 28] + JONG[c % 28])
        else:
            out.append(ch)
    return sep.join(out)


def roman_person(name):
    name = name.strip()
    if len(name) == 4 and name[:2] in SURNAME2:
        sur, given = SURNAME2[name[:2]], name[2:]
    else:
        sur, given = SURNAME.get(name[0], roman_syllables(name[0]).capitalize()), name[1:]
    g = roman_syllables(given, "-")
    return f"{sur} {g.capitalize()}" if g else sur


ENTITY_WORDS = [
    ("사모투자합자회사", " PEF"), ("투자합자회사", " Investment LP"), ("투자조합", " Investment Association"),
    ("우리사주조합", " Employee Stock Ownership Association"), ("자산운용", " Asset Management"),
    ("인베스트먼트", " Investment"), ("파트너스", " Partners"), ("홀딩스", " Holdings"), ("캐피탈", " Capital"),
    ("코리아", " Korea"), ("에쿼티", " Equity"), ("프라이빗", " Private"), ("벤처스", " Ventures"),
    ("인터내셔널", " International"), ("글로벌", " Global"), ("테크놀로지", " Technology"), ("증권", " Securities"),
    ("생명보험", " Life Insurance"), ("화재해상보험", " Fire & Marine Insurance"), ("손해보험", " Insurance"),
    ("보험", " Insurance"), ("은행", " Bank"), ("재단", " Foundation"), ("공단", " Corporation"),
    ("금융지주", " Financial Group"), ("지주", " Holdings"), ("재단법인", ""), ("사단법인", ""),
    ("문화재단", " Cultural Foundation"), ("장학재단", " Scholarship Foundation"),
    ("주식회사", ""), ("(주)", ""), ("㈜", ""),
]
ENTITY_HINT = re.compile("|".join(re.escape(k) for k, _ in ENTITY_WORDS) +
                         r"|회사|법인|펀드|조합|그룹|건설|산업|전자|화학|제약|바이오|에너지|미디어|모터스|물산|상사|"
                         r"해운|텍스타일|시큐리티|모바일|소재|반도체|전선|스틸|중공업|엔터|네트웍스|시스템|솔루션|"
                         r"[A-Za-z0-9]")


def is_person(name):
    n = name.replace(" ", "")
    return bool(re.fullmatch(r"[가-힣]{2,4}", n)) and not ENTITY_HINT.search(n)


def roman_entity(name):
    s = name
    for k, v in sorted(ENTITY_WORDS, key=lambda x: -len(x[0])):
        s = s.replace(k, "\x00" + v.strip() + "\x00")
    parts = [p for p in s.split("\x00") if p.strip()]
    res = []
    for p in parts:
        if HANGUL.search(p):
            res.append(re.sub(r"[가-힣]+", lambda m: roman_syllables(m.group(0)).capitalize(), p).strip())
        else:
            res.append(p.strip())
    return re.sub(r"\s+", " ", " ".join(res)).strip()


def tidy_latin(name):
    """KWON SANG HOON -> Kwon Sang Hoon, 단 3글자 이하 약어(SK, LG)는 유지"""
    if name.upper() == name and re.search(r"[A-Z]{4,}", name):
        return " ".join(w if len(w) <= 3 and w.isalpha() else w.capitalize() for w in name.split())
    return name


def tidy_person_latin(name):
    """보고자 이름이 영문 대문자 개인명(2~4단어)이면 모두 첫 글자만 대문자로"""
    w = name.split()
    if 2 <= len(w) <= 4 and all(x.isalpha() for x in w) and name.upper() == name:
        return " ".join(x.capitalize() for x in w)
    return tidy_latin(name)


LEGAL_SUFFIX = re.compile(r"[\s,]*(CO\.?\s*,?\s*LTD\.?|CORPORATION|CORP\.?|INC\.?|LIMITED|LTD\.?|CO\.?)\s*$", re.I)


def tidy_company(eng):
    e = re.sub(r"\s+", " ", (eng or "").replace(" ", " ")).strip()
    for _ in range(2):
        e = LEGAL_SUFFIX.sub("", e).strip(" ,.")
    return tidy_latin(e)


# ══════════════════════════════════════════════════════════════════
# 용어집 규칙
# ══════════════════════════════════════════════════════════════════
ROLE_TERMS = [
    ("대표이사 회장", "Chairman & CEO"), ("대표이사회장", "Chairman & CEO"), ("대표이사 부회장", "Vice Chairman & CEO"),
    ("대표이사 사장", "President & CEO"), ("대표이사사장", "President & CEO"), ("대표사장", "President & CEO"),
    ("공동대표이사", "Co-CEO"), ("각자 대표이사", "Co-CEO"), ("대표집행임원", "CEO"), ("부대표이사", "Deputy CEO"),
    ("대표이사", "CEO"), ("총괄대표", "CEO"), ("부문대표", "Division CEO"), ("부대표", "Deputy CEO"), ("대표", "CEO"),
    ("명예회장", "Honorary Chairman"), ("부회장", "Vice Chairman"), ("회장", "Chairman"),
    ("수석부사장", "Senior Executive Vice President"), ("부사장", "Executive Vice President"),
    ("사장", "President"), ("전무이사", "Senior Vice President"), ("전무", "Senior Vice President"),
    ("상무이사", "Vice President"), ("상무대우", "Vice President"), ("상무보", "Associate Vice President"),
    ("상무(보)", "Associate Vice President"), ("상무", "Vice President"),
    ("이사회 의장", "Board Chair"), ("이사회의장", "Board Chair"), ("의장", "Board Chair"),
    ("기타비상무이사", "Non-Executive Director"), ("기타 비상무이사", "Non-Executive Director"),
    ("기타비등기이사", "Non-Registered Director"), ("비상임이사", "Non-Standing Director"),
    ("사내이사", "Inside Director"), ("사외이사", "Outside Director"), ("독립이사", "Independent Director"),
    ("등기이사", "Registered Director"), ("이사대우", "Director"), ("이사보", "Associate Director"),
    ("연구이사", "Research Director"), ("상근감사", "Standing Auditor"), ("비상근감사", "Non-Standing Auditor"),
    ("감사위원", "Audit Committee Member"), ("감사", "Auditor"), ("최대주주", "Largest Shareholder"),
    ("경영임원", "Executive"), ("경영리더", "Executive"), ("담당임원", "Executive"), ("경영자", "Executive"),
    ("임원", "Executive"), ("고문", "Advisor"), ("연구위원", "Research Fellow"), ("수석", "Principal"),
    ("파트너", "Partner"), ("디렉터", "Director"), ("법인장", "Head of Subsidiary"), ("본부장", "Division Head"),
    ("부문장", "Division Head"), ("그룹장", "Group Head"), ("센터장", "Center Head"), ("소장", "Institute Head"),
    ("실장", "Office Head"), ("팀장", "Team Lead"), ("원장", "Head"), ("담당", "Head"), ("이사", "Director"),
    ("준법감시인", "Compliance Officer"), ("최고재무책임자", "CFO"), ("최고 기술책임자", "CTO"),
    ("총괄", "Head"), ("성과리더", "Lead"), ("리더", "Lead"),
]


ROLE_DEPTS = [
    ("반도체사업부", "Semiconductor Business"), ("사업부", "Business Unit"), ("연구소", "R&D Center"),
    ("품질혁신", "Quality Innovation"), ("재무전략", "Finance Strategy"), ("재무", "Finance"), ("인사기획", "HR Planning"),
    ("인사", "HR"), ("영업구매", "Sales & Procurement"), ("영업", "Sales"), ("구매", "Procurement"),
    ("경영기획", "Corporate Planning"), ("기획관리", "Planning & Administration"), ("경영관리", "Management Support"),
    ("경영전략", "Corporate Strategy"), ("미래전략", "Future Strategy"), ("전략", "Strategy"), ("기획", "Planning"),
    ("관리", "Administration"), ("커뮤니케이션", "Communications"), ("고객서비스", "Customer Service"),
    ("엔지니어링기술", "Engineering"), ("기술", "Technology"), ("컴플라이언스", "Compliance"), ("지급결제", "Payments"),
    ("매니지먼트", "Management"), ("글로벌", "Global"), ("성장사업", "Growth Business"), ("신사업", "New Business"),
    ("투자", "Investment"), ("의약품사업", "Pharmaceutical Business"), ("브랜드", "Brand"), ("신뢰기술", "Trust & Safety"),
    ("제조", "Manufacturing"), ("설계", "Design"), ("연구", "Research"), ("경영", "Management"),
    ("추진", ""), ("부문", ""), ("본부", ""), ("각자", ""), ("호주", "Australia"), ("미국", "US"), ("중국", "China"),
    ("AI", "AI"), ("BPR", "BPR"), ("IR", "IR"),
]
GENERIC_HEADS = {"Division Head", "Office Head", "Group Head", "Center Head", "Head", "Executive", "Team Lead",
                 "Institute Head", "Lead"}


def clean_ko(s):
    return re.sub(r"\s+", " ", (s or "").replace("ㆍ", " ")).strip()


def role_rule(raw):
    s = clean_ko(raw)
    if not s or s == "-":
        return s
    paren_en = re.findall(r"\(([A-Za-z][A-Za-z &/.-]+)\)", s)
    s_ko = re.sub(r"\(([A-Za-z][A-Za-z &/.-]+)\)", "", s)
    compact = s_ko.replace(" ", "")
    latin = [w for w in re.findall(r"\b(C[A-Z]{1,3}O|CEO|CFO|COO|CTO)\b", s_ko)]
    found, depts = [], []
    i = 0
    terms = [(k.replace(" ", ""), v, "role") for k, v in ROLE_TERMS] + [(k, v, "dept") for k, v in ROLE_DEPTS]
    terms.sort(key=lambda x: -len(x[0]))
    unknown = False
    while i < len(compact):
        for kk, v, kind in terms:
            if compact.startswith(kk, i):
                if kind == "dept":
                    if v and v not in depts:
                        depts.append(v)
                else:
                    if depts and v in GENERIC_HEADS:
                        d = " ".join(depts)
                        v = f"{d} Team Lead" if v == "Team Lead" else f"Head of {d}"
                        depts = []
                    if v not in found:
                        found.append(v)
                i += len(kk)
                break
        else:
            if HANGUL.match(compact[i]):
                unknown = True
            i += 1
    if depts:
        found.append(" ".join(depts))
    for p in paren_en + latin:
        if p not in found:
            found.append(p)
    full_titles = [p for p in paren_en if " " in p or len(p) > 5]
    if full_titles:
        return ", ".join(full_titles + [x for x in latin if x not in full_titles])
    if unknown:
        return ", ".join(paren_en + latin) if (paren_en or latin) else None
    return ", ".join(found) if found else None


def buyback_purpose_rule(raw):
    s = clean_ko(raw).replace(" ", "")
    if not s or re.match(r"^-?\d", s.strip("- ")):
        return ""
    tags = []
    def add(t):
        if t not in tags:
            tags.append(t)
    if re.search(r"주가안정|주식가격.*안정|주가.*안정|가격안정|변동성완화|주주안정", s): add("Price stabilization")
    if re.search(r"주주가치|주식가치|주주환원|기업가치|주주권익|주주이익|밸류업", s): add("Shareholder value")
    if "소각" in s: add("Cancellation")
    if re.search(r"임직원|종업원|성과보상|주식보상|상여|보상", s): add("Employee compensation")
    if re.search(r"상환|우선주", s): add("Preferred share redemption")
    if re.search(r"합병|분할|교환", s): add("Restructuring")
    if "단주" in s: add("Odd-lot purchase")
    if re.search(r"지급취소|반환|회수", s): add("Reclaim of stock awards")
    return ", ".join(tags) if tags else None


def buyback_method_rule(raw):
    s = clean_ko(raw).replace(" ", "")
    if not s or s.startswith("-"):
        return ""
    if "공개매수" in s: return "Tender offer"
    if "신탁" in s: return "Via trust contract"
    if "무상" in s: return "Gratuitous acquisition"
    if "시간외" in s: return "After-hours block trade"
    if "장외" in s: return "Off-market purchase"
    if re.search(r"유가증권|코스피|KOSPI", s, re.I): return "On-market (KOSPI)"
    if re.search(r"코스닥|KOSDAQ", s, re.I): return "On-market (KOSDAQ)"
    if re.search(r"장내|직접취득|매수|취득", s): return "On-market purchase"
    return None


def resn_rule(raw):
    s = clean_ko(raw).replace(" ", "")
    if not s:
        return ""
    tags = []
    def add(t):
        if t not in tags:
            tags.append(t)
    if re.search(r"신규", s): add("New 5%+ stake")
    if "의결권공동행사" in s: add("Voting agreement")
    if "보유목적" in s or "목적변경" in s or re.search(r"투자목적에서|투자목적으로변경", s): add("Change in holding purpose")
    if "운용펀드추가" in s: add("Fund added")
    if "운용펀드해소" in s: add("Fund removed")
    if re.search(r"InvestmentManager", s, re.I): add("Investment manager change")
    if "시간외" in s: add("After-hours trade")
    if re.search(r"장내매수|매수|취득", s) and "신규" not in s: add("Purchase")
    if re.search(r"장내매도|매도|처분", s): add("Sale")
    if re.search(r"1%|변동", s) and not tags: add("1%+ change")
    if "5%미만" in s: add("Below 5%")
    if "질권" in s or "담보" in s: add("Pledge")
    if "주식매매계약" in s: add("Share purchase agreement")
    if "특별관계자" in s and not tags: add("Related party change")
    if "정정" in s and not tags: add("Amendment")
    return ", ".join(tags[:2]) if tags else None


# ══════════════════════════════════════════════════════════════════
# 외부 API
# ══════════════════════════════════════════════════════════════════
def dart_corp_list():
    """corp_code -> (한글명, 영문명). 실패하면 빈 dict"""
    if not DART_KEY:
        return {}
    try:
        r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml", params={"crtfc_key": DART_KEY}, timeout=60)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(z.read(z.namelist()[0]))
        out = {}
        for el in root.iter("list"):
            code = (el.findtext("corp_code") or "").strip()
            out[code] = ((el.findtext("corp_name") or "").strip(), (el.findtext("corp_eng_name") or "").strip())
        print(f"[DART] 고유번호 목록 {len(out)}건")
        return out
    except Exception as e:
        print(f"[DART] 고유번호 목록 실패: {e}")
        return {}


def dart_company_eng(code):
    try:
        r = requests.get("https://opendart.fss.or.kr/api/company.json",
                         params={"crtfc_key": DART_KEY, "corp_code": code}, timeout=15)
        j = r.json()
        return (j.get("corp_name_eng") or "").strip()
    except Exception:
        return ""


_deepl_used = 0


def deepl(texts):
    """한국어 문자열 목록을 영어로. 키가 없거나 한도 초과면 빈 dict"""
    global _deepl_used
    if not DEEPL_KEY or not texts:
        return {}
    host = "https://api-free.deepl.com" if DEEPL_KEY.endswith(":fx") else "https://api.deepl.com"
    out = {}
    batch = []
    def flush(b):
        if not b:
            return
        try:
            r = requests.post(f"{host}/v2/translate", headers={"Authorization": f"DeepL-Auth-Key {DEEPL_KEY}"},
                              data=[("text", t) for t in b] + [("source_lang", "KO"), ("target_lang", "EN-US")],
                              timeout=30)
            if r.status_code == 200:
                for src, tr in zip(b, r.json().get("translations", [])):
                    out[src] = tr.get("text", "").strip()
            else:
                print(f"[DeepL] HTTP {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"[DeepL] 실패: {e}")
    for t in texts:
        if _deepl_used + len(t) > DEEPL_BUDGET:
            print("[DeepL] 이번 실행 한도 도달, 나머지는 다음 실행")
            break
        _deepl_used += len(t)
        batch.append(t)
        if len(batch) >= 40:
            flush(batch); batch = []
    flush(batch)
    return out


# ══════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════
def norm_ko_name(n):
    return re.sub(r"\s|\(주\)|㈜|주식회사", "", n or "")


def main():
    cache = load(OUT, {})
    for k in ("corp", "names", "roles", "text", "mkt", "auto"):
        cache.setdefault(k, {})
    auto = cache["auto"]          # 규칙이나 로마자로 임시 처리한 항목 (DeepL 키가 생기면 다시 번역)

    ins = load(os.path.join(DOCS, "insider.json"), {}).get("disclosures", [])
    bb = load(os.path.join(DOCS, "buyback.json"), {}).get("entries", [])
    firm = load(os.path.join(DOCS, "data.json"), {}).get("disclosures", []) + \
        load(os.path.join(DOCS, "archive.json"), {}).get("disclosures", [])

    # 종목코드 → 시장 (KS: 코스피, KQ: 코스닥)
    for x in ins:
        if x.get("stock_code") and x.get("market") in ("KOSPI", "KOSDAQ"):
            cache["mkt"][x["stock_code"]] = "KS" if x["market"] == "KOSPI" else "KQ"
    for x in bb:
        if x.get("stock_code") and x.get("corp_cls") in ("Y", "K"):
            cache["mkt"][x["stock_code"]] = "KS" if x["corp_cls"] == "Y" else "KQ"

    # ── 1. 회사명 ──
    codes = {x["corp_code"]: x.get("corp_name", "") for x in ins + bb + firm if x.get("corp_code")}
    missing = [c for c in codes if c not in cache["corp"]]
    reporters = sorted({x.get("repror", "").strip() for x in ins if x.get("repror")} - {""})
    need_names = [r for r in reporters if r not in cache["names"] or (r in auto and DEEPL_KEY)]
    entity_need = [r for r in need_names if HANGUL.search(r) and not is_person(r)]
    corp_list = {}
    if missing or entity_need:
        corp_list = dart_corp_list()
    by_ko = {}
    for code, (ko, en) in corp_list.items():
        if en:
            by_ko.setdefault(norm_ko_name(ko), en)
    for c in missing:
        en = corp_list.get(c, ("", ""))[1]
        if not en and DART_KEY:
            en = dart_company_eng(c)
            time.sleep(0.15)
        if en:
            cache["corp"][c] = tidy_company(en)
        else:
            cache["corp"][c] = roman_entity(codes[c])
            auto[f"corp:{c}"] = 1
    print(f"[회사명] 신규 {len(missing)}건, 누적 {len(cache['corp'])}건")

    # ── 2. 보고자 ──
    to_deepl = []
    for r in need_names:
        if HANGUL.search(r) and len(re.findall(r"[A-Za-z]{2,}", r)) >= 2:
            cache["names"][r] = tidy_person_latin(re.sub(r"\s*[가-힣]+\s*", " ", r).strip())
            auto.pop(r, None)
        elif not HANGUL.search(r):
            cache["names"][r] = tidy_person_latin(r)
            auto.pop(r, None)
        elif is_person(r):
            cache["names"][r] = roman_person(r.replace(" ", ""))
            auto.pop(r, None)
        else:
            en = by_ko.get(norm_ko_name(r))
            if en:
                cache["names"][r] = tidy_company(en)
                auto.pop(r, None)
            else:
                to_deepl.append(r)

    # ── 3. 직위, 자사주, 보고사유 ──
    phrase_jobs = []   # (bucket, 원문, 규칙결과)
    for raw in {x.get("ofcps", "") for x in ins}:
        if raw and (raw not in cache["roles"] or (raw in auto and DEEPL_KEY)):
            phrase_jobs.append(("roles", raw, role_rule(raw)))
    for x in bb:
        for f, rule in (("acq_purpose", buyback_purpose_rule), ("acq_method", buyback_method_rule)):
            raw = x.get(f) or ""
            if raw and (raw not in cache["text"] or (raw in auto and DEEPL_KEY)):
                phrase_jobs.append(("text", raw, rule(raw)))
    for x in firm:
        raw = x.get("report_resn") or ""
        if raw and (raw not in cache["text"] or (raw in auto and DEEPL_KEY)):
            phrase_jobs.append(("text", raw, resn_rule(raw)))

    unresolved = [raw for _, raw, res in phrase_jobs if res is None]
    tr = deepl(sorted(set(to_deepl + [clean_ko(u) for u in unresolved])))

    for r in to_deepl:
        if tr.get(r):
            cache["names"][r] = tidy_latin(tr[r]); auto.pop(r, None)
        else:
            cache["names"][r] = roman_entity(r); auto[r] = 1
    for bucket, raw, res in phrase_jobs:
        if res is not None:
            cache[bucket][raw] = res; auto.pop(raw, None)
        elif tr.get(clean_ko(raw)):
            cache[bucket][raw] = tr[clean_ko(raw)]; auto.pop(raw, None)
        else:
            cache[bucket][raw] = {"roles": "Executive", "text": "Other"}[bucket]; auto[raw] = 1

    print(f"[보고자] 신규 {len(need_names)}건 / [문구] 신규 {len(phrase_jobs)}건 / DeepL {_deepl_used}자 "
          f"/ 임시 처리 {len(auto)}건")

    before = load(OUT, {})
    before.pop("updated_at", None)
    if before == {k: v for k, v in cache.items() if k != "updated_at"}:
        print("[저장] 변경 없음")
        return
    cache["updated_at"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0, sort_keys=True)


if __name__ == "__main__":
    main()
