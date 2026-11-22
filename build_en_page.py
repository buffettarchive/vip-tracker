"""
build_en_page.py - 대시보드 원본(src/dashboard.html)에서 언어별 페이지 생성

  docs/dashboard.html     영어판 (기본 주소)
  docs/ko/dashboard.html  한국어판
  docs/en/dashboard.html  예전 영어판 주소 → 기본 주소로 이동

화면 로직은 원본 하나를 공유하고, 언어별로 다른 부분만 바꿉니다.
대시보드를 고칠 때는 src/dashboard.html만 수정하세요. docs 쪽 파일은 덮어써집니다.
방문자가 언어 버튼으로 한국어를 고르면 기억해 두었다가 다음 방문부터 한국어판으로 보냅니다.
"""

import os, re

SRC = "src/dashboard.html"
OUT_EN = "docs/dashboard.html"
OUT_KO = "docs/ko/dashboard.html"
OUT_OLD_EN = "docs/en/dashboard.html"

GEN_NOTE = "<!-- 자동 생성 파일입니다. 수정은 src/dashboard.html에서 하세요 (build_en_page.py) -->"

TITLE = "Buffett Archive | Korean Insider Buying, 5% Stake Filings and Buybacks"
DESC = ("Track Korean stock market signals in English: insider open-market purchases, "
        "5% stake filings by asset managers, and share buyback decisions from DART filings, updated every few minutes.")

FOOTER_EN = """    <div class="ba-f-legal">
      <p>※ Korean ownership filings are due within 5 business days of the trigger date, so they can lag the actual trade.</p>
      <p>※ 13F reports are filed within 45 days after quarter end and include long positions in reportable securities only.</p>
      <p>※ Company and person names are shown in English using official DART English names where available; other names are romanized.</p>
      <p>※ This site summarizes public filings only and does not recommend buying or selling any security. Investment decisions are your own responsibility.</p>
    </div>"""

REDIRECT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Buffett Archive</title>
<link rel="canonical" href="https://www.buffettarchive.co.kr/dashboard.html" />
<meta name="robots" content="noindex" />
<script>location.replace("/dashboard.html" + location.search);</script>
<meta http-equiv="refresh" content="0; url=/dashboard.html" />
</head>
<body><a href="/dashboard.html">Buffett Archive</a></body>
</html>
"""


def sub(pattern, repl, s, count=1, flags=0):
    new, n = re.subn(pattern, repl, s, count=count, flags=flags)
    if n == 0:
        raise SystemExit(f"[build_en_page] 패턴을 찾지 못함: {pattern[:60]}")
    return new


def common(s):
    s = sub(r"<head>\n", '<head>\n<base href="/" />\n', s)
    s = s.replace("<!-- 원본 파일: 이 파일을 고친 뒤 build_en_page.py가 docs/dashboard.html(영어, 기본)과 "
                  "docs/ko/dashboard.html(한국어)을 만듭니다 -->", GEN_NOTE)
    return s


def build_ko(src):
    return common(src)


def build_en(src):
    s = common(src)
    s = sub(r'<html lang="ko" data-lang="ko">', '<html lang="en" data-lang="en">', s)
    s = sub(r"<title>.*?</title>", f"<title>{TITLE}</title>", s)
    s = sub(r'<meta name="description" content="[^"]*" />', f'<meta name="description" content="{DESC}" />', s)
    s = sub(r'<meta property="og:site_name" content="[^"]*" />', '<meta property="og:site_name" content="Buffett Archive" />', s)
    s = sub(r'<meta property="og:title" content="[^"]*" />', f'<meta property="og:title" content="{TITLE}" />', s)
    s = sub(r'<meta property="og:description" content="[^"]*" />', f'<meta property="og:description" content="{DESC}" />', s)
    s = sub(r'<meta property="og:locale" content="[^"]*" />', '<meta property="og:locale" content="en_US" />', s)
    s = sub(r'<meta name="twitter:title" content="[^"]*" />', f'<meta name="twitter:title" content="{TITLE}" />', s)
    s = sub(r'<meta name="twitter:description" content="[^"]*" />', f'<meta name="twitter:description" content="{DESC}" />', s)

    # 메뉴: 영어판 주소와 문구 (자바스크립트 없이 읽는 검색엔진도 영어로 보이게)
    s = sub(r'<a href="index.html"', '<a href="dashboard.html?view=insider"', s)
    s = sub(r'href="ko/dashboard.html\?view=insider" id="nav-insider">[^<]*<', 'href="dashboard.html?view=insider" id="nav-insider">Insider Buying<', s)
    s = sub(r'href="ko/dashboard.html\?view=firm" id="nav-firm">[^<]*<', 'href="dashboard.html?view=firm" id="nav-firm">Firm Filings<', s)
    s = sub(r'href="ko/dashboard.html\?view=buyback" id="nav-buyback">[^<]*<', 'href="dashboard.html?view=buyback" id="nav-buyback">Buybacks<', s)
    s = sub(r'<a href="guru.html" id="nav-guru">[^<]*</a>', '<a href="guru.html" id="nav-guru" style="display:none">Guru Portfolio</a>', s)
    s = sub(r'<a href="dashboard.html\?view=insider" id="langToggle" class="lang-toggle" hreflang="en">English</a>',
            '<a href="ko/dashboard.html?view=insider" id="langToggle" class="lang-toggle" hreflang="ko">한국어</a>', s)
    s = sub(r'(id="tabInsider">)[^<]*<', r'\1Insider Buying<', s)
    s = sub(r'(id="tabFirm">)[^<]*<', r'\1Asset Manager Filings<', s)
    s = sub(r'(id="tabBuyback">)[^<]*<', r'\1Treasury Buybacks<', s)
    s = sub(r'placeholder="[^"]*검색"', 'placeholder="Search company, ticker, or filer"', s)
    s = sub(r'    <div class="ba-f-legal">.*?    </div>', FOOTER_EN, s, flags=re.S)
    return s


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if old != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[build_en_page] {path} 갱신")
    else:
        print(f"[build_en_page] {path} 변경 없음")


def main():
    src = open(SRC, encoding="utf-8").read()
    write(OUT_EN, build_en(src))
    write(OUT_KO, build_ko(src))
    write(OUT_OLD_EN, REDIRECT)


if __name__ == "__main__":
    main()
