#!/usr/bin/env python3
"""
직방 단기임대 네이버 검색 노출 모니터 - 일일 수집기

NAVER API HUB(네이버 클라우드) 검색 API + 검색어 트렌드 API를 호출해
검색어 x 검색영역별 '직방 자체 콘텐츠 노출/순위/점유율'을 매일 기록합니다.

필요 환경변수
  NAVER_API_HUB_CLIENT_ID      API HUB 애플리케이션 Client ID
  NAVER_API_HUB_CLIENT_SECRET  API HUB 애플리케이션 Client Secret
  SLACK_WEBHOOK_URL            (선택) 변동 알림을 보낼 Slack Incoming Webhook

사용법
  python3 collector.py                  # 오늘 데이터 수집
  python3 collector.py --date 2026-09-28
  python3 collector.py --demo-days 30 --out demo_data   # API 키 없이 가짜 데이터로 파이프라인 테스트

표준 라이브러리만 사용합니다 (pip 설치 불필요).
"""
import argparse
import csv
import datetime as dt
import email.utils
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KST = dt.timezone(dt.timedelta(hours=9))

V_LABEL = {"blog": "블로그", "cafearticle": "카페", "news": "뉴스", "webkr": "웹문서"}

RAW_FIELDS = [
    "date", "query", "query_type", "vertical", "rank", "total",
    "owned", "owned_asset", "mention", "competitors",
    "title", "source", "link", "posted",
]


# --------------------------------------------------------------------------- utils
def strip_tags(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return (s.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<")
             .replace("&gt;", ">").replace("&#39;", "'").strip())


def parse_posted(vertical, item):
    """검색영역별 날짜 필드를 date 로 변환 (없으면 None)."""
    try:
        if vertical == "blog" and item.get("postdate"):
            return dt.datetime.strptime(item["postdate"], "%Y%m%d").date()
        if vertical == "news" and item.get("pubDate"):
            return email.utils.parsedate_to_datetime(item["pubDate"]).astimezone(KST).date()
    except Exception:
        pass
    return None


def item_links(vertical, item):
    """자체 콘텐츠 판별에 쓸 URL 후보들."""
    keys = {
        "blog": ["link", "bloggerlink"],
        "cafearticle": ["link", "cafeurl"],
        "news": ["originallink", "link"],
        "webkr": ["link"],
    }.get(vertical, ["link"])
    return [item.get(k, "") for k in keys if item.get(k)]


def item_source(vertical, item):
    if vertical == "blog":
        return item.get("bloggername", "")
    if vertical == "cafearticle":
        return item.get("cafename", "")
    if vertical == "news":
        m = re.match(r"https?://([^/]+)", item.get("originallink") or item.get("link", ""))
        return m.group(1) if m else ""
    m = re.match(r"https?://([^/]+)", item.get("link", ""))
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- API clients
class ApiHub:
    def __init__(self, base_url, client_id, client_secret):
        self.base = base_url.rstrip("/")
        self.h = {
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
        }
        self.calls = 0
        self.errors = []
        self.auth_failed = False

    def _request(self, url, data=None, retries=3):
        if self.auth_failed:
            return None
        headers = dict(self.h)
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")
        for attempt in range(retries):
            self.calls += 1
            req = urllib.request.Request(url, data=body, headers=headers,
                                         method="POST" if body else "GET")
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "ignore")[:300]
                if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                self.errors.append(f"{e.code} {url} {msg}")
                if e.code in (401, 403):
                    self.auth_failed = True  # 키 문제면 나머지 호출은 건너뜀
                return None
            except Exception as e:  # 네트워크 오류 등
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                self.errors.append(f"ERR {url} {e}")
                return None
            finally:
                time.sleep(0.12)  # 초당 호출 과다 방지

    def search(self, vertical, query, display, sort="sim", start=1):
        qs = urllib.parse.urlencode({"query": query, "display": display,
                                     "start": start, "sort": sort})
        return self._request(f"{self.base}/search/v1/{vertical}?{qs}")

    def trend(self, body):
        return self._request(f"{self.base}/search-trend/v1/search", data=body)


class FakeApi:
    """API 키 없이 전체 파이프라인을 검증하기 위한 가짜 응답 생성기."""

    def __init__(self, cfg, day):
        self.cfg, self.day = cfg, day
        self.calls, self.errors = 0, []

    def search(self, vertical, query, display, sort="sim", start=1):
        self.calls += 1
        seed = f"{self.day}|{vertical}|{query}|{sort}"
        rnd = random.Random(seed)
        stable = random.Random(f"{vertical}|{query}|{sort}")  # 날짜와 무관한 기본 순위 구조
        brand = "직방" in query
        drift = (dt.date.fromisoformat(self.day) - dt.date(2026, 1, 1)).days % 40 / 40
        items = []
        for i in range(display):
            owned_p = (0.2 if brand else 0.04) * (1.0 if i < 10 else 0.6) * (0.75 + drift * 0.5)
            if vertical == "news":
                owned_p *= 0.15
            base_owned = stable.random() < owned_p
            # 일별 변동: 기존 자체 콘텐츠는 15% 확률로 빠지고, 새로 진입할 확률은 낮게
            is_owned = (rnd.random() > 0.15) if base_owned else (rnd.random() < owned_p * 0.25)
            r = 0.0 if is_owned else 1.0
            posted = dt.date.fromisoformat(self.day) - dt.timedelta(days=rnd.randint(0, 60 if sort == "sim" else 35))
            if r < owned_p:
                if vertical == "blog":
                    link, extra = f"https://blog.naver.com/zigbang/2244{rnd.randint(10**5, 10**6)}", {"bloggerlink": "blog.naver.com/zigbang", "bloggername": "직방 공식 블로그"}
                elif vertical == "webkr":
                    link, extra = rnd.choice(["https://str.zigbang.com/guide/", "https://www.zigbang.com/stay/map", "https://str.zigbang.com/faq_h/"]), {}
                else:
                    link, extra = "https://www.zigbang.com/stay", {}
                title = "<b>직방 단기임대</b> 호스트 가이드 " + str(i)
            else:
                comp = rnd.choice(["삼삼엠투", "리브애니웨어", "엔코스테이", "", "", "", ""])
                mention = rnd.random() < (0.55 if brand else 0.12)
                title = f"{'직방 ' if mention else ''}{comp} 단기임대 후기 {i}".strip()
                uid = rnd.randint(1000, 9999)
                link = f"https://blog.naver.com/user{uid}/2244{rnd.randint(10**5, 10**6)}"
                extra = {"bloggerlink": f"blog.naver.com/user{uid}", "bloggername": f"블로거{uid}"}
            it = {"title": title, "link": link, "description": title + " 내용 요약", **extra}
            if vertical == "blog":
                it["postdate"] = posted.strftime("%Y%m%d")
            if vertical == "news":
                it["pubDate"] = email.utils.format_datetime(dt.datetime.combine(posted, dt.time(9), KST))
                it["originallink"] = link.replace("blog.naver.com", "news.example.com")
            if vertical == "cafearticle":
                it["cafename"], it["cafeurl"] = "부동산 스터디", "https://cafe.naver.com/jaegebal"
            items.append(it)
        base_total = {"blog": 42000, "cafearticle": 18000, "news": 900, "webkr": 6100}[vertical]
        return {"total": int(base_total * (1 if brand else 12) * (0.9 + drift * 0.3)), "items": items}

    def trend(self, body):
        self.calls += 1
        start = dt.date.fromisoformat(body["startDate"])
        end = dt.date.fromisoformat(body["endDate"])
        res = []
        for gi, g in enumerate(body["keywordGroups"]):
            rnd = random.Random(g["groupName"])
            base = [35, 70, 25, 90][gi % 4]
            data, d = [], start
            while d <= end:
                wk = 1.15 if d.weekday() < 5 else 0.8
                data.append({"period": d.isoformat(),
                             "ratio": round(max(1, base * wk * (0.85 + rnd.random() * 0.3)
                                                * (1 + (d - start).days / 400)), 5)})
                d += dt.timedelta(days=1)
            res.append({"title": g["groupName"], "keywords": g["keywords"], "data": data})
        mx = max(p["ratio"] for r in res for p in r["data"])
        for r in res:
            for p in r["data"]:
                p["ratio"] = round(p["ratio"] / mx * 100, 5)
        return {"results": res}


# --------------------------------------------------------------------------- core
def compile_cfg(cfg):
    owned = [(a["label"], re.compile(a["pattern"], re.I)) for a in cfg["owned_assets"]]
    comps = [(c["key"], re.compile(c["pattern"], re.I)) for c in cfg["competitors"]]
    brand = re.compile(cfg["brand_mention"], re.I)
    return owned, comps, brand


def classify_owned(links, owned_patterns):
    for label, pat in owned_patterns:
        if any(pat.search(l) for l in links):
            return label
    return ""


def collect_day(api, cfg, day):
    owned_p, comp_p, brand_p = compile_cfg(cfg)
    depth = int(cfg.get("depth", 30))
    win = int(cfg.get("new_window_days", 7))
    day_d = dt.date.fromisoformat(day)
    raw_rows, summary_rows = [], []

    for qobj in cfg["queries"]:
        q, qtype = qobj["q"], qobj.get("type", "")
        for v in cfg["verticals"]:
            res = api.search(v, q, display=depth, sort="sim")
            if res is None:
                continue
            items = res.get("items", [])
            ranks_owned, assets = [], {}
            mention_n = 0
            comp_n = {k: 0 for k, _ in comp_p}
            for rank, it in enumerate(items, 1):
                links = item_links(v, it)
                title = strip_tags(it.get("title"))
                desc = strip_tags(it.get("description"))
                text = f"{title} {desc}"
                asset = classify_owned(links, owned_p)
                mention = bool(brand_p.search(text)) or bool(asset)
                comps_hit = [k for k, p in comp_p if p.search(text)]
                if asset:
                    ranks_owned.append(rank)
                    assets.setdefault(rank, (asset, links[0]))
                mention_n += mention
                for k in comps_hit:
                    comp_n[k] += 1
                posted = parse_posted(v, it)
                raw_rows.append({
                    "date": day, "query": q, "query_type": qtype, "vertical": v, "rank": rank,
                    "total": res.get("total", ""), "owned": int(bool(asset)), "owned_asset": asset,
                    "mention": int(mention), "competitors": "|".join(comps_hit),
                    "title": title[:120], "source": item_source(v, it),
                    "link": links[0] if links else "", "posted": posted.isoformat() if posted else "",
                })

            n = len(items) or 1
            best = min(ranks_owned) if ranks_owned else ""
            row = {
                "date": day, "query": q, "query_type": qtype, "vertical": v,
                "total": res.get("total", ""), "fetched": len(items),
                "owned_top10": int(any(r <= 10 for r in ranks_owned)),
                "owned_count_top10": sum(1 for r in ranks_owned if r <= 10),
                "owned_count_topN": len(ranks_owned),
                "best_owned_rank": best,
                "best_owned_asset": assets[best][0] if best else "",
                "best_owned_link": assets[best][1] if best else "",
                "owned_share": round(len(ranks_owned) / n, 4),
                "mention_share": round(mention_n / n, 4),
            }
            for k, _ in comp_p:
                row[f"comp_{k}_share"] = round(comp_n[k] / n, 4)

            # 최신순 호출로 최근 N일 신규 콘텐츠 수 (날짜 필드가 있는 blog/news 만)
            row["new_count"], row["owned_new_count"] = "", ""
            if v in ("blog", "news"):
                res_d = api.search(v, q, display=100, sort="date")
                if res_d:
                    cnt = own = 0
                    for it in res_d.get("items", []):
                        p = parse_posted(v, it)
                        if p and (day_d - p).days < win:
                            cnt += 1
                            own += int(bool(classify_owned(item_links(v, it), owned_p)))
                    row["new_count"], row["owned_new_count"] = cnt, own
            summary_rows.append(row)
    return raw_rows, summary_rows


def collect_trend(api, cfg, day):
    t = cfg.get("trend")
    if not t:
        return []
    end = dt.date.fromisoformat(day) - dt.timedelta(days=1)  # 당일은 집계 미완료
    start = end - dt.timedelta(days=int(t.get("lookback_days", 90)) - 1)
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
            "timeUnit": "date", "keywordGroups": t["keyword_groups"][:5]}
    res = api.trend(body)
    rows = []
    for r in (res or {}).get("results", []):
        for p in r.get("data", []):
            rows.append({"period": p["period"], "group": r["title"], "ratio": p["ratio"]})
    return rows


# --------------------------------------------------------------------------- storage
def read_csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else [])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def upsert_summary(path, new_rows, day):
    old = [r for r in read_csv(path) if r["date"] != day]
    rows = old + new_rows
    fields = list(new_rows[0].keys()) if new_rows else (list(old[0].keys()) if old else [])
    rows.sort(key=lambda r: (r["date"], r["query"], r["vertical"]))
    write_csv(path, rows, fields)
    return rows


# --------------------------------------------------------------------------- alerts
def build_alerts(all_summary, cfg, day):
    a = cfg.get("alerts", {})
    core = set(a.get("core_queries", []))
    th = int(a.get("rank_change_threshold", 3))
    dates = sorted({r["date"] for r in all_summary if r["date"] < day})
    if not dates:
        return []
    prev_day = dates[-1]
    prev = {(r["query"], r["vertical"]): r for r in all_summary if r["date"] == prev_day}
    msgs = []
    for r in all_summary:
        if r["date"] != day or r["query"] not in core:
            continue
        p = prev.get((r["query"], r["vertical"]))
        if not p:
            continue
        tag = f"[{r['query']} / {V_LABEL.get(r['vertical'], r['vertical'])}]"
        if str(p["owned_top10"]) == "1" and str(r["owned_top10"]) == "0":
            msgs.append(f":small_red_triangle_down: {tag} 상위 10위 내 자체 콘텐츠 사라짐 (전일 최고 {p['best_owned_rank']}위)")
        elif str(p["owned_top10"]) == "0" and str(r["owned_top10"]) == "1":
            msgs.append(f":white_check_mark: {tag} 상위 10위 진입 ({r['best_owned_rank']}위, {r['best_owned_asset']})")
        elif r["best_owned_rank"] and p["best_owned_rank"]:
            d = int(p["best_owned_rank"]) - int(r["best_owned_rank"])
            if abs(d) >= th:
                arrow = "상승" if d > 0 else "하락"
                msgs.append(f"{tag} 최고 순위 {p['best_owned_rank']}위 → {r['best_owned_rank']}위 ({arrow} {abs(d)})")
    return msgs


def post_slack(webhook, text):
    req = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print("Slack 전송 실패:", e, file=sys.stderr)


# --------------------------------------------------------------------------- main
def run_one(api, cfg, day, out, do_trend=True, quiet=False):
    raw, summ = collect_day(api, cfg, day)
    if raw:  # 전부 실패한 날은 기존 데이터를 덮어쓰지 않음
        write_csv(out / "raw" / f"{day}.csv", raw, RAW_FIELDS)
        write_csv(out / "latest_raw.csv", raw, RAW_FIELDS)
    all_summary = upsert_summary(out / "summary.csv", summ, day) if summ else read_csv(out / "summary.csv")
    if do_trend:
        tr = collect_trend(api, cfg, day)
        if tr:
            write_csv(out / "trend.csv", tr, ["period", "group", "ratio"])
    alerts = build_alerts(all_summary, cfg, day)
    meta = {"last_run": dt.datetime.now(KST).isoformat(timespec="seconds"), "date": day,
            "api_calls": api.calls, "errors": api.errors[:20], "alerts": alerts,
            "demo": isinstance(api, FakeApi)}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if not quiet:
        print(f"[{day}] raw={len(raw)} summary={len(summ)} calls={api.calls} errors={len(api.errors)}")
        for m in alerts:
            print("  ALERT", m)
    return alerts, summ


def daily_digest(cfg, summ, alerts, day):
    core = cfg.get("alerts", {}).get("core_queries", [])
    lines = [f"*직방 단기임대 네이버 검색 노출 리포트* ({day})"]
    for q in core:
        parts = []
        for r in summ:
            if r["query"] == q:
                rank = f"{r['best_owned_rank']}위" if r["best_owned_rank"] else "미노출"
                parts.append(f"{V_LABEL.get(r['vertical'], r['vertical'])} {rank}")
        if parts:
            lines.append(f"• {q}: " + " / ".join(parts))
    if alerts:
        lines.append("*변동*")
        lines += [f"• {m}" for m in alerts]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--out", default=str(ROOT / "data"))
    ap.add_argument("--date", default=dt.datetime.now(KST).date().isoformat())
    ap.add_argument("--no-trend", action="store_true")
    ap.add_argument("--demo-days", type=int, default=0,
                    help="API 키 없이 N일치 가짜 데이터 생성 (파이프라인/대시보드 테스트용)")
    ap.add_argument("--slack-digest", action="store_true",
                    help="변동이 없어도 매일 요약을 Slack 으로 전송")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.demo_days:
        end = dt.date.fromisoformat(args.date)
        for i in range(args.demo_days - 1, -1, -1):
            d = (end - dt.timedelta(days=i)).isoformat()
            run_one(FakeApi(cfg, d), cfg, d, out, do_trend=(i == 0), quiet=i > 0)
        print(f"데모 데이터 {args.demo_days}일치 생성 완료 → {out}")
        return

    cid = os.environ.get("NAVER_API_HUB_CLIENT_ID")
    sec = os.environ.get("NAVER_API_HUB_CLIENT_SECRET")
    if not cid or not sec:
        sys.exit("환경변수 NAVER_API_HUB_CLIENT_ID / NAVER_API_HUB_CLIENT_SECRET 를 설정해 주세요.")
    api = ApiHub(cfg["base_url"], cid, sec)
    alerts, summ = run_one(api, cfg, args.date, out, do_trend=not args.no_trend)

    hook = os.environ.get("SLACK_WEBHOOK_URL")
    if hook and (alerts or args.slack_digest):
        post_slack(hook, daily_digest(cfg, summ, alerts, args.date))
    if api.errors:
        print("오류:", *api.errors[:5], sep="\n  ", file=sys.stderr)
        if not summ:
            sys.exit(1)


if __name__ == "__main__":
    main()
