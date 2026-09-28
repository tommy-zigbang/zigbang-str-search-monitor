# 직방 단기임대 · 네이버 검색 노출 모니터

NAVER API HUB(네이버 클라우드) **검색 API + 검색어 트렌드 API**로
"직방 단기임대" 관련 검색어에서 직방 자체 콘텐츠가 **어디에, 몇 위로, 얼마나** 노출되는지 매일 기록하고 대시보드로 봅니다.

```
zigbang-str-search-monitor/
├─ config.json              # 검색어, 검색영역, 자체 채널 URL 패턴, 경쟁사, 트렌드 그룹
├─ collector.py             # 일일 수집기 (표준 라이브러리만 사용)
├─ index.html               # dashboard.html 로 이동
├─ dashboard.html           # 대시보드 (단일 파일, 외부 라이브러리 없음, 샘플 데이터 내장, 비밀번호 화면)
├─ embed_demo.py            # demo_data 를 대시보드 샘플로 넣는 도구
├─ demo_data/               # 가짜 데이터 45일치 (구조 확인용)
├─ .github/workflows/daily.yml  # 매일 09:00 KST 수집 + Pages 배포
└─ data/                    # 실제 수집 결과 (첫 실행 시 생성)
   ├─ summary.csv           # 날짜 x 검색어 x 영역별 KPI (대시보드 메인 데이터)
   ├─ trend.csv             # 검색어 트렌드 (최근 90일, 일간)
   ├─ latest_raw.csv        # 최신 수집일의 개별 검색 결과
   ├─ raw/YYYY-MM-DD.csv    # 일자별 원본 결과 아카이브
   └─ meta.json             # 마지막 실행 시각, 호출 수, 오류, 변동 알림
```

## 1. API 키 발급 (NAVER API HUB)

개발자센터 검색 API는 2026-07-31부터 신규 신청이 막혔고, 이제 NAVER API HUB에서 신청해야 합니다.

1. 네이버 클라우드 플랫폼 계정 가입 후 콘솔 접속
2. **NAVER API HUB** 이용 신청 → 애플리케이션 등록 → **검색**, **검색어 트렌드** API 선택
3. 발급된 **Client ID / Client Secret** 확인

호출 형식 (개발자센터와 다름):

| 항목 | 값 |
|---|---|
| 도메인 | `https://naverapihub.apigw.ntruss.com` |
| 검색 | `GET /search/v1/{blog,cafearticle,news,webkr}` |
| 검색어 트렌드 | `POST /search-trend/v1/search` |
| 인증 헤더 | `X-NCP-APIGW-API-KEY-ID`, `X-NCP-APIGW-API-KEY` |

## 2. 로컬에서 실행

```bash
export NAVER_API_HUB_CLIENT_ID=xxxx
export NAVER_API_HUB_CLIENT_SECRET=xxxx
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...   # 선택

python3 collector.py                 # 오늘 수집 → data/
python3 collector.py --slack-digest  # 변동이 없어도 매일 요약 전송
python3 -m http.server 8000          # 브라우저에서 http://localhost:8000/dashboard.html
```

- 키 없이 동작 확인: `python3 collector.py --demo-days 30 --out demo_data`
- 하루 호출량: 검색어 8개 x 4개 영역 + 최신순 16회 + 트렌드 1회 = **약 49회** (하루 한도 25,000회)
- 같은 날 다시 실행하면 그날 데이터를 덮어씁니다.

## 3. 매일 자동 실행 + 웹 게시 (GitHub Actions + Pages)

- 저장소: https://github.com/tommy-zigbang/zigbang-str-search-monitor
- 대시보드: https://tommy-zigbang.github.io/zigbang-str-search-monitor/ (비밀번호 `str`)

1. Settings → Secrets and variables → Actions 에 등록:
   `NAVER_API_HUB_CLIENT_ID`, `NAVER_API_HUB_CLIENT_SECRET`, (선택) `SLACK_WEBHOOK_URL`
2. 매일 09:00 KST에 수집 → `data/` 커밋 → Pages 재배포가 자동으로 돌아갑니다.
   Actions 탭 → daily-naver-search-monitor → **Run workflow** 로 즉시 실행할 수 있어요.
3. 키를 넣기 전에는 수집을 건너뛰고 샘플 데이터 대시보드만 배포합니다.
4. 비밀번호 화면은 브라우저에서만 확인하는 가벼운 잠금이에요 (저장소가 공개라 데이터 파일은 직접 볼 수 있어요).
   비밀번호를 바꾸려면 `dashboard.html` 의 `GATE_HASH` 를 새 비밀번호의 SHA-256 값으로 바꾸세요.

다른 방법: 사내 서버 crontab `0 9 * * * cd /path && python3 collector.py --slack-digest`

## 4. 대시보드 보는 법

- `data/summary.csv` 를 찾으면 실데이터를, 못 찾으면 내장 샘플을 보여줍니다 (상단 배지로 구분).
- 파일로 열었을 때는 **CSV 불러오기** 로 `summary.csv`, `trend.csv`, `latest_raw.csv`, `meta.json` 을 선택하거나 끌어다 놓으면 됩니다.

| 영역 | 내용 |
|---|---|
| KPI 카드 | 상위 10위 안에 들어간 영역 수, 블로그/웹문서 최고 순위, 자체 콘텐츠 점유율, 직방 언급 점유율, 검색 관심도(최근 7일과 직전 7일 비교) |
| 순위 표 | 검색어 x 영역별 최고 순위와 전일 대비 변동 (▲ 상승, ▼ 하락, NEW 진입, OUT 이탈) |
| 검색 관심도 | 직방 단기임대, 경쟁사, 카테고리 검색량의 상대 추이 |
| 최고 순위 추이 | 검색영역별 순위 변화 |
| 검색 점유율 추이 | 자체 콘텐츠, 직방 언급, 경쟁사 언급 비율 |
| 최신 검색 결과 | 개별 결과 30개 (자체 채널, 언급, 경쟁사 태그 표시) |
| 신규 콘텐츠 | 최근 7일 안에 새로 올라온 블로그·뉴스 글 수와 그중 자체 콘텐츠 수 |

## 5. 지표 정의 (`summary.csv`)

| 컬럼 | 의미 |
|---|---|
| `owned_top10` | 상위 10위 안에 자체 콘텐츠가 있으면 1 |
| `best_owned_rank` / `best_owned_asset` | 자체 콘텐츠 최고 순위와 채널 이름 (공식블로그, 호스트사이트, 직방stay 등) |
| `owned_count_top10`, `owned_count_topN` | 상위 10위 / 상위 N위(`depth`, 기본 30) 안의 자체 콘텐츠 수 |
| `owned_share` | 상위 N개 중 자체 콘텐츠 비율 |
| `mention_share` | 상위 N개 중 제목이나 요약에 '직방'이 들어간 비율 (자체 콘텐츠 포함, 체험단·후기 효과 측정용) |
| `comp_<key>_share` | 경쟁사 언급 비율 |
| `new_count`, `owned_new_count` | 최신순 100개 중 최근 7일 안에 올라온 글 수 (블로그·뉴스만 해당) |
| `total` | 전체 검색 결과 수 |

자체 콘텐츠 판별은 `config.json > owned_assets` 의 URL 정규식으로 합니다. 블로그는 `bloggerlink`, 뉴스는 `originallink`, 카페는 `cafeurl` 까지 확인합니다.
새 채널(예: 인스타그램, 유튜브)이나 체험단 블로그 ID 목록이 생기면 여기에 추가하세요.

## 6. 한계와 보완 방법

- 검색 API는 **영역별 검색 결과**를 줍니다. 통합검색 화면 배치(AI 브리핑, 광고, 클립, 스마트블록)나 개인화 결과는 반영하지 않습니다.
- 노출수와 클릭수는 없습니다. 아래 데이터와 함께 보세요.
  - **네이버 서치어드바이저**: str.zigbang.com 의 노출수, 클릭수, 검색어
  - **네이버 검색광고 키워드 도구**: 월간 검색량 절대값, 광고 성과
  - **GA/UTM**: 블로그·클립에서 들어온 유입과 전환 (호스트 등록, 문의)
- 검색어 트렌드 값은 요청할 때마다 기간 내 최대값을 100으로 다시 계산한 상대값입니다. 그래서 매일 90일치를 새로 받아 `trend.csv` 를 덮어씁니다.
- API HUB는 현재 무료 요금제만 있고 유료 요금제가 나올 예정이라, 호출량이 늘어나면 요금을 확인하세요.
