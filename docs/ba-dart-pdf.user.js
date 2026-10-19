// ==UserScript==
// @name         버핏아카이브 DART PDF 일괄 다운로드
// @namespace    https://www.buffettarchive.co.kr
// @version      1.0
// @description  버핏아카이브 내부자매수에서 고른 공시의 PDF를 DART에서 한 번에 받습니다
// @match        https://dart.fss.or.kr/pdf/download/main.do*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(async function () {
  "use strict";

  // 버핏아카이브가 열어준 창인지 확인 (주소 끝 #ba= 뒤에 받을 목록이 들어 있음)
  const m = location.hash.match(/[#&]ba=([^&]+)/);
  if (!m) return;
  const items = decodeURIComponent(m[1]).split("|").map(s => {
    const [r, d, n] = s.split("~");
    return { r, d, n: n || r };
  }).filter(x => /^\d{14}$/.test(x.r) && /^\d+$/.test(x.d));
  if (!items.length) return;

  // 새로고침해도 다시 받지 않도록 주소에서 목록 제거
  history.replaceState(null, "", location.pathname + location.search);

  // 진행 상황 표시
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;z-index:2147483647;top:16px;right:16px;background:#0047FF;color:#fff;" +
    "font:700 14px/1.5 sans-serif;padding:12px 18px;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.25);max-width:360px;white-space:pre-line";
  document.body.appendChild(box);
  const show = t => { box.textContent = t; };

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const safe = s => s.replace(/[\\/:*?"<>|]/g, " ").replace(/\s+/g, " ").trim().slice(0, 120);

  // DART 다운로드 창을 같은 사이트 안의 숨긴 창으로 열어 실제 PDF 링크를 얻음
  function popupLink(pop) {
    return new Promise(resolve => {
      const f = document.createElement("iframe");
      f.style.display = "none";
      let done = false;
      const finish = v => { if (done) return; done = true; f.remove(); resolve(v); };
      f.onload = () => {
        try {
          const a = f.contentDocument.querySelector('a[href*="pdf.do"]');
          finish(a ? a.getAttribute("href") : null);
        } catch (e) { finish(null); }
      };
      setTimeout(() => finish(null), 15000);
      f.src = pop;
      document.body.appendChild(f);
    });
  }

  let ok = 0;
  const fail = [];
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    show(`PDF 받는 중 ${i + 1} / ${items.length}\n${it.n}`);
    try {
      const pop = `/pdf/download/main.do?rcp_no=${it.r}&dcm_no=${it.d}`;
      let href = await popupLink(pop);
      if (!href) {
        const html = await (await fetch(pop, { credentials: "include" })).text();
        const mm = html.match(/href\s*=\s*["']([^"']*pdf\.do[^"']*)["']/i);
        href = mm ? mm[1].replace(/&amp;/g, "&") : `/pdf/download/pdf.do?rcp_no=${it.r}&dcm_no=${it.d}`;
      }
      const res = await fetch(new URL(href, location.origin).href, {
        credentials: "include",
        referrer: location.origin + pop,
      });
      const ct = res.headers.get("content-type") || "";
      const blob = await res.blob();
      if (!res.ok || blob.size < 500 || /html/i.test(ct)) throw new Error(`${res.status} ${ct}`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = safe(it.n) + ".pdf";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 10000);
      ok++;
    } catch (e) {
      console.warn("[버핏아카이브] 실패", it, e);
      fail.push(it.n);
    }
    await sleep(600);
  }

  if (!fail.length) {
    show(`완료: ${ok}개 PDF 저장`);
    setTimeout(() => window.close(), 2500);
  } else {
    show(`완료: ${ok}개 저장, ${fail.length}개 실패\n${fail.slice(0, 5).join("\n")}`);
    box.style.background = "#e0473b";
  }
})();
