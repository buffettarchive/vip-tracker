"""
build_en_page.py - docs/dashboard.html(한국어판)에서 docs/en/dashboard.html(영어판) 생성

화면 로직은 한국어판과 같은 파일을 그대로 쓰고, 영어판에 필요한 부분만 바꿉니다.
  - <html data-lang="en">, <base href="/"> (데이터 파일과 이미지는 사이트 루트에서 읽음)
  - 제목, 검색엔진 설명, 공유 미리보기(OG) 문구
  - 메뉴 주소와 문구, 언어 전환 버튼, 하단 안내문
dashboard.html을 고친 뒤 이 스크립트를 다시 실행하면 영어판도 같이 갱신됩니다.
"""

import os, re

SRC = "docs/dashboard.html"
DST = "docs/en/dashboard.html"

TITLE = "Buffett Archive | Korean Insider Buying, 5% Stake Filings and Buybacks"
DESC = ("Track Korean stock market signals in English: insider open-market purchases, "
        "5% stake filings by asset managers, and share buyback decisions from DART filings, updated every few minutes.")

FOOTER_EN = """    <div class="ba-f-legal">
      <p>※ Korean ownership filings are due within 5 business days of the trigger date, so they can lag the actual trade.</p>
      <p>※ 13F reports are filed within 45 days after quarter end and include long positions in reportable securities only.</p>
      <p>※ Company and person names are shown in English using official DART English names where available; other names are romanized.</p>
      <p>※ This site summarizes public filings only and does not recommend buying or selling any security. Investment decisions are your own responsibility.</p>
    </div>"""


def sub(pattern, repl, s, count=1, flags=0):
    new, n = re.subn(pattern, repl, s, count=count, flags=flags)
    if n == 0:
        raise SystemExit(f"[build_en_page] 패턴을 찾지 못함: {pattern[:60]}")
    return new


def main():
    s = open(SRC, encoding="utf-8").read()

    s = sub(r'<html lang="ko" data-lang="ko">', '<html lang="en" data-lang="en">', s)
    s = sub(r"<head>\n", '<head>\n<base href="/" />\n', s)
    s = sub(r"<title>.*?</title>", f"<title>{TITLE}</title>", s)
    s = sub(r'<meta name="description" content="[^"]*" />', f'<meta name="description" content="{DESC}" />', s)
    s = sub(r'<meta property="og:site_name" content="[^"]*" />', '<meta property="og:site_name" content="Buffett Archive" />', s)
    s = sub(r'<meta property="og:title" content="[^"]*" />', f'<meta property="og:title" content="{TITLE}" />', s)
    s = sub(r'<meta property="og:description" content="[^"]*" />', f'<meta property="og:description" content="{DESC}" />', s)
    s = sub(r'<meta property="og:url" content="[^"]*" />',
            '<meta property="og:url" content="https://www.buffettarchive.co.kr/en/dashboard.html?view=insider" />', s)
    s = sub(r'<meta property="og:locale" content="[^"]*" />', '<meta property="og:locale" content="en_US" />', s)
    s = sub(r'<meta name="twitter:title" content="[^"]*" />', f'<meta name="twitter:title" content="{TITLE}" />', s)
    s = sub(r'<meta name="twitter:description" content="[^"]*" />', f'<meta name="twitter:description" content="{DESC}" />', s)

    # 메뉴: 영어판 주소, 영어 문구 (자바스크립트 없이 읽는 검색엔진도 영어로 보이게)
    s = sub(r'<a href="index.html"', '<a href="en/dashboard.html?view=insider"', s)
    s = sub(r'href="dashboard.html\?view=insider" id="nav-insider">[^<]*<', 'href="en/dashboard.html?view=insider" id="nav-insider">Insider Buying<', s)
    s = sub(r'href="dashboard.html\?view=firm" id="nav-firm">[^<]*<', 'href="en/dashboard.html?view=firm" id="nav-firm">Firm Filings<', s)
    s = sub(r'href="dashboard.html\?view=buyback" id="nav-buyback">[^<]*<', 'href="en/dashboard.html?view=buyback" id="nav-buyback">Buybacks<', s)
    s = sub(r'<a href="guru.html" id="nav-guru">[^<]*</a>', '<a href="guru.html" id="nav-guru" style="display:none">Guru Portfolio</a>', s)
    s = sub(r'<a href="en/dashboard.html\?view=insider" id="langToggle" class="lang-toggle" hreflang="en">English</a>',
            '<a href="dashboard.html?view=insider" id="langToggle" class="lang-toggle" hreflang="ko">한국어</a>', s)
    s = sub(r'(id="tabInsider">)[^<]*<', r'\1Insider Buying<', s)
    s = sub(r'(id="tabFirm">)[^<]*<', r'\1Asset Manager Filings<', s)
    s = sub(r'(id="tabBuyback">)[^<]*<', r'\1Treasury Buybacks<', s)
    s = sub(r'placeholder="[^"]*검색"', 'placeholder="Search company, ticker, or filer"', s)
    s = sub(r'    <div class="ba-f-legal">.*?    </div>', FOOTER_EN, s, flags=re.S)

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    old = open(DST, encoding="utf-8").read() if os.path.exists(DST) else ""
    if old != s:
        with open(DST, "w", encoding="utf-8") as f:
            f.write(s)
        print(f"[build_en_page] {DST} 갱신")
    else:
        print("[build_en_page] 변경 없음")


if __name__ == "__main__":
    main()
