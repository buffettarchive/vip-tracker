# 지분의 흔적 — VIP자산운용 5% 공시 추적 (MVP)

DB도 서버도 없는 최소 구성. 레포 하나로 끝납니다.

```
GitHub Actions(15분) → fetch_vip.py → docs/data.json 커밋
                                          │
                              GitHub Pages(docs/) → 화면 표시
```

## 배포 4단계

1. **DART 인증키**: opendart.fss.or.kr 에서 발급.

2. **레포 생성**: 이 폴더를 GitHub 레포로 push.
   - Settings → Secrets and variables → Actions → `DART_API_KEY` 등록.
   - Settings → Pages → Source를 **Deploy from a branch**, 폴더 **/docs** 로 지정.

3. **첫 실행**: Actions 탭 → vip-tracker → Run workflow.
   `docs/data.json`이 실제 공시로 갱신되고, 커밋이 한 건 생깁니다.

4. **확인**: `https://<아이디>.github.io/<레포명>/` 접속.
   VIP 공시가 표로 뜨면 성공. 이후 15분마다 자동 갱신됩니다.

## 운용사 추가
`fetch_vip.py`의 `WATCH_FIRMS`에 한 줄 추가하면 끝.
프론트 탭은 데이터에 있는 운용사를 자동으로 만듭니다.

## 검증 메모 (DART 원자료 대조)
- `majorstock`의 `stkrt`(보유비율)·`stkrt_irds`(증감) 필드명은 가이드 기준입니다.
  첫 실행 로그/`data.json`에서 값이 비면 실제 응답 키를 한 번 찍어 대조하세요.
- `stkrt_prev`(직전 비율)는 상세 응답에 없으면 빈칸으로 둡니다. 화면에서는
  직전값이 없으면 "신규 5% 진입"으로 표기합니다. 정확한 직전값이 필요하면
  같은 corp_code의 이전 보고를 시계열로 이어 계산하는 로직을 나중에 붙입니다.

## 알아둘 한계
- 5% 미만 포지션과 5% 이탈 후는 추적 불가(제도상 공시가 없음).
- 보고는 변동일로부터 5영업일 이내 → 실제 매매보다 늦습니다.
- 이름이 펀드·일임·특별관계자로 갈려 보고되면 일부 누락 가능. 발견되는 대로
  `WATCH_FIRMS`에 표기 변형을 추가하면 됩니다.
