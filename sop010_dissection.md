# sop010.html 정밀 분석 (1단 재현 기준)

`견본/sop010.html` v0.10의 추출 메커니즘을 줄 단위로 뜯어, 우리 `src/page_extractor.py` 재현 상태와 대조한다. 상태: ✅재현 / ⚠️부분 / ❌누락 / ❗가정과 실제가 다름.

## 1. 파이프라인 개요
- 1-Pass. 정찰 없이 페이지 1장을 1회 호출로 직접 추출(line 164). 청크 분할 없음. → ✅

## 2. 렌더링 (line 1144-1184)
- `scale = 300/72`(300 DPI), `rotation = (page.rotate + globalRotation) % 360`.
- Step1 `ctx.filter='grayscale(1)'`로 그레이스케일 렌더 → Step2 밝기 분석 → Step3 새 캔버스에 `contrast()/brightness()` 적용.
- 우리: PyMuPDF 300 DPI 렌더 후 `_preprocess_page`에서 PIL `convert('L')`+대비/밝기. 회전 미적용. → ⚠️ 회전(globalRotation) 미구현, 나머지 ✅.

## 3. 적응형 전처리 (line 247-265)
- `analyzeBrightness`: 샘플 영역 x10%,y15%,w80%,h35%의 R채널 평균.
- `getAdaptiveFilter`: <85 → contrast1.8/bright1.3(어두움), <170 → 1.5/1.1(보통), else 1.3/1.0(밝음).
- 우리 `_preprocess_page`: 동일 영역(0.1,0.15,0.9,0.5), 동일 임계값, PIL ImageEnhance. → ✅ 충실.

## 4. 이미지 인코딩 (line 1177)
- `finalCanvas.toDataURL(webp 0.85 / jpeg 0.9)`. → 우리는 PNG 전송. → ⚠️ 무손실이라 품질 무관, 용량만 큼.

## 5. EXTRACT_PROMPT (line 665-695)
- 헤더명을 key로, 빈 칸은 key 자체 생략, "0"은 보존. 첫 줄=헤더 JSON 배열. 모든 거래행 누락 금지.
- 집계행(소계/합계/총계/총합/월계/누계)·빈행·안내문구 제외. 애매하면 `"__skip": true`.
- JSON 외 출력 금지. → 우리 `prompts/page_extract_jsonl.md`는 충실 이식 + 검산용 `__total` 최소 확장. → ✅(+확장).

## 6. callExtract (line 792-881)
- `systemInstruction = EXTRACT_PROMPT + headerHint`, user parts [text, inlineData].
- generationConfig: `responseMimeType: text/plain`, `temperature:0`, `topP:0.1`, `maxOutputTokens`.
- safetySettings BLOCK_NONE **5종**(HARASSMENT/HATE/SEXUAL/DANGEROUS/**CIVIC_INTEGRITY**).
- 우리 `_call_gemini_text`: 동일하나 safety **4종**(CIVIC_INTEGRITY 누락), 엔드포인트 generativelanguage(HTML은 aiplatform, 사용자 지시로 무시). → ⚠️ CIVIC_INTEGRITY 추가 필요.

## 7. ❗ 헤더 힌트 — 실제는 강제(FORCED), 소프트 아님 (line 795-797, 814-816)
- `headerHint = '... [중요] 이 페이지에는 표 헤더가 없습니다. 반드시 아래 헤더명을 키로 사용하세요 (임의 생성 금지): {knownHeader} 첫 줄 헤더 배열도 위 헤더 그대로 출력하세요.'`
- `userText(knownHeader 있을 때) = '첫 줄은 반드시 {knownHeader} 배열을 그대로 출력하세요.'`
- 즉 **같은 파일 2쪽~는 1쪽 헤더를 강제 적용**한다. `headersCompatible`(Jaccard 0.75)는 파일 간(append) 충돌 검사용이고, 한 파일 안에서는 무조건 1쪽 헤더로 통일.
- ❗ 사용자 가정("헤더 못 찾는 경우만 1쪽 헤더 사용")과 실제 코드가 다르다. 내가 바꾼 소프트 힌트는 HTML 재현이 아니라 의도적 개선이다.
- 함의: HTML도 신한_11 page 6의 일시불/공과금 구간을 1쪽 할부 헤더로 강제했을 것이다. 그래도 HTML이 문제없던 이유는 8·13에 있다(아래).

## 8. 재시도/백오프 (line 800-879)
- MAX_RETRIES=4. 429 → 30s, 그 외 `5000*2^(attempt-1)`. 400/401/403은 즉시 throw(재시도 안 함). MAX_TOKENS는 페이지 검토 플래그.
- 우리 `_extract_one_page`: 동일. → ✅.

## 9. RPM/동시성 (line 267-289, 1040-1044, 1189-1259)
- `SlidingWindowQueue(LIMIT_RPM-2, 60000)` acquire 후 호출. CONCURRENCY_LIMIT=2.
- 1쪽 단독 await로 헤더 확정 → 2쪽~ `Promise.race`로 executing<2 유지.
- 우리: `_SlidingWindowRateLimiter(rpm_limit-2,60)` + `ThreadPoolExecutor(max_workers=2)`, 1쪽 선처리. → ✅. (RPM=15, 슬롯13)

## 10. ❗ parseRawText — 정규화 안 함, raw 컬럼 보존이 핵심 (line 395-517)
- JSON Lines 경로: 첫 string배열(len≥2)→header. 객체는 `__skip`·AGGREGATE_RE(vals[0])·전부빈값 제외 후 수집.
- header 없으면 객체 key 합집합으로 추론. 최종 row = `header.map(h => o[h] ?? '')` — **헤더 순서로 정렬, 빈 칸은 ''**.
- ❗ **canonical amount를 만들지 않는다.** 그냥 raw 표를 헤더 순서로 보존해 Excel로 덤프(line 1368-1414). 어떤 컬럼이 "진짜 금액"인지 고르지 않는다.
- 우리 `_parse_jsonl`: 동일(헤더 정렬, __skip, AGGREGATE_RE, key합집합) + `__total`→totals. → ✅(+totals 확장).

## 11. isLikelyDate / 탭폴백 (line 300-322, 469-516)
- JSON 0건일 때만 탭 분리 폴백. isLikelyDate는 폴백 보조용(역참조 \1, 8자리 YYYYMMDD, 6자리는 allowShort일 때만).
- 우리: 탭폴백 ❌ 미구현(Gemini가 JSON 반환하므로 사실상 미발생). → ⚠️ 안전망 누락.

## 12. isRealMoney (line 522-531) — Excel 숫자 변환용
- 12자리 이상 연속숫자(콤마 없음)는 식별번호로 차단, 그 외 콤마/소수 패턴만 숫자화. → 우리 export 단계 별개. 1단 무관.

## 13. ❗ 시스템 검토(조건 A/B/C) = 우리 validator 대응물 (line 357-390)
- 조건 A(금액 누락): `COL_PATTERNS.amountAll`(금액|원금|단가|합계|매출|결제|청구|이용금|공급가|부가세|총액)에 매칭되는 **모든 컬럼이 비었을 때만** 경고.
- ❗ 즉 HTML은 `금액`·`원금`·`이용금액`을 **모두 amount 후보로 동등 취급**하고, 그중 하나라도 값이 있으면 정상으로 본다. 일시불 행의 `금액` 값도 amountAll에 매칭되므로 경고 없음 → HTML이 신한_11에서 문제없던 진짜 이유.
- 조건 B(데이터 유실): 비어있지 않은 셀 ≤2개. 조건 C(중복): 날짜+가맹점+금액+할부 키 중복.
- 우리 2단: normalizer가 `금액`을 '할인'으로 좁게 보고 canonical amount를 비워 충돌. → ❗ HTML의 "amountAll 동등 취급" 철학을 안 따름.

## 14. 집계/합계(totals) — HTML은 버린다
- HTML은 집계행을 제외만 하고 검산을 안 한다(검산 기준 없음). 우리는 `__total`로 보존해 2단 검산에 쓴다(의도적 확장).

---

## 핵심 결론
1. ❗ **헤더는 강제(파일 내 1쪽 헤더 통일)** — 내 소프트 힌트는 재현이 아니라 개선. 재현하려면 강제로, 개선을 택하려면 소프트로(근거 명시).
2. ❗ **HTML은 canonical amount를 안 만든다.** raw 컬럼만 보존하고, 검토 단계에서 `금액|원금|이용금액`을 동등한 amount 후보로 본다. 우리 2단이 `금액`을 '할인'으로 좁게 본 게 일시불 충돌의 원인.
3. 그래서 일시불 `금액` 문제의 HTML식 해법 = **강제 코드 보정이 아니라, amount 후보 컬럼을 넓게(금액/원금/이용금액) 동등 취급**하는 매핑 철학.
4. 재현 갭(우선순위): ⚠️ CIVIC_INTEGRITY safety, ⚠️ 회전 처리, ⚠️ 탭폴백 안전망. (기능상 영향 작음)
