"""
MLB Pipeline Top 100, current and each preseason (for the personal model, not the site).

The list page builds itself in the browser, so this opens it in headless Chromium,
expands the full list, and reads rank, name and MLB id (from the headshot URL).
Preseason lists come from Wayback Machine snapshots near the end of March.

Output: research_out/history/pipeline/<label>.json
"""
import json, os, re, sys
from playwright.sync_api import sync_playwright

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research_out", "history", "pipeline")
PAGE = "https://www.mlb.com/prospects/top100/"
TARGETS = {"current": PAGE}
for y in (2023, 2024, 2025, 2026):
    TARGETS[f"preseason_{y}"] = f"https://web.archive.org/web/{y}0325000000/{PAGE}"

JS = """
() => {
  const out = [];
  document.querySelectorAll('img[alt^="Photo headshot of"]').forEach(img => {
    const m = (img.getAttribute('src') || '').match(/people\\/(\\d+)\\//);
    const row = img.closest('tr') || img.closest('[class*="row"]');
    let rank = null;
    if (row) { const t = row.innerText.match(/^\\s*(\\d{1,3})\\b/); if (t) rank = +t[1]; }
    out.push({id: m ? +m[1] : null, name: img.getAttribute('alt').replace('Photo headshot of ', ''), rank,
              text: row ? row.innerText.replace(/\\s+/g, ' ').slice(0, 160) : ''});
  });
  return out;
}
"""


CAPTURED = []


def on_response(resp):
    try:
        ct = resp.headers.get("content-type", "")
        if "json" not in ct: return
        body = resp.text()
        if len(body) > 2000 and ("prospect" in body.lower() or "rank" in body.lower()):
            CAPTURED.append({"url": resp.url, "body": body[:3_000_000]})
    except Exception:
        pass


def grab(page, url):
    CAPTURED.clear()
    page.goto(url, wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(6000)
    for label in ("Show Full List", "Show full list", "Load More", "Show More"):
        try:
            b = page.get_by_text(label, exact=False).first
            if b and b.is_visible():
                b.click(); page.wait_for_timeout(4000)
        except Exception:
            pass
    for _ in range(12):   # lazy-loaded rows
        page.mouse.wheel(0, 4000); page.wait_for_timeout(700)
    try:
        buttons = page.evaluate("() => [...document.querySelectorAll('button, a')].map(b => b.innerText.trim()).filter(t => t && t.length < 40)")
        page.evaluate("() => [...document.querySelectorAll('button, a')].filter(b => /full list|show all|view all|see all/i.test(b.innerText)).forEach(b => b.click())")
        page.wait_for_timeout(5000)
    except Exception:
        buttons = []
    rows = page.evaluate(JS)
    page._dbg = {"buttons": buttons[:300], "captured": [c["url"] for c in CAPTURED]}
    seen, clean = set(), []
    for r in rows:
        key = r["id"] or r["name"]
        if key in seen: continue
        seen.add(key); clean.append(r)
    for i, r in enumerate(clean):
        if not r["rank"]: r["rank"] = i + 1
    return clean


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1400, "height": 2000},
                          user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36")
        page.on("response", on_response)
        for label, url in TARGETS.items():
            try:
                rows = grab(page, url)
            except Exception as e:  # noqa: BLE001
                print(label, "failed:", repr(e)[:200]); continue
            print(f"{label}: {len(rows)} prospects; first: {[r['name'] for r in rows[:3]]}")
            with open(os.path.join(OUT, f"{label}.json"), "w", encoding="utf-8") as f:
                json.dump({"url": url, "rows": rows, "debug": getattr(page, "_dbg", {})}, f, ensure_ascii=False, indent=0)
            for i, c in enumerate(CAPTURED[:6]):
                with open(os.path.join(OUT, f"{label}_net{i}.json"), "w", encoding="utf-8") as f:
                    json.dump(c, f, ensure_ascii=False)
        b.close()


if __name__ == "__main__":
    main()
