#!/usr/bin/env python3
"""demo_data/ 의 CSV 를 dashboard.html 안에 샘플 데이터로 넣습니다.
(data/summary.csv 를 찾지 못했을 때 대시보드가 보여주는 기본 화면)

  python3 collector.py --demo-days 45 --out demo_data
  python3 embed_demo.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
src = ROOT / "demo_data"
html_path = ROOT / "dashboard.html"

payload = {
    "summary": (src / "summary.csv").read_text(encoding="utf-8-sig"),
    "trend": (src / "trend.csv").read_text(encoding="utf-8-sig"),
    "raw": (src / "latest_raw.csv").read_text(encoding="utf-8-sig"),
    "meta": json.loads((src / "meta.json").read_text(encoding="utf-8")),
}
blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
html = html_path.read_text(encoding="utf-8")
html, n = re.subn(r'(<script id="demo-data" type="application/json">).*?(</script>)',
                  lambda m: m.group(1) + blob + m.group(2), html, flags=re.S)
assert n == 1, "demo-data 블록을 찾지 못했어요"
html_path.write_text(html, encoding="utf-8")
print(f"embedded {len(blob)/1024:.0f} KB into dashboard.html")
