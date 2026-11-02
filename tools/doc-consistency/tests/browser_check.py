import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def open_graph(page_path, shot_dir, channel="chrome", pick="docs/agents/workflow.md"):
    """用真实浏览器打开图谱页面，返回检查结果。网络请求只允许 file 与 data。"""
    errors, external = [], []
    shot_dir = Path(shot_dir)
    shot_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=channel, headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: external.append(r.url) if not r.url.startswith(("file:", "data:")) else None)
        page.goto(Path(page_path).resolve().as_uri())
        page.wait_for_function("window.__graphReady === true")
        out["stat"] = page.inner_text("#stat")
        out["nodes_collapsed"] = page.evaluate("__cy.nodes().length")
        page.screenshot(path=str(shot_dir / "graph.png"))
        # 点一份文档：上下游被高亮，其余变淡
        page.evaluate(f"__cy.getElementById({json.dumps(pick)}).emit('tap')")
        out["highlight"] = page.evaluate(
            "({up: __cy.nodes('.nbup').length, down: __cy.nodes('.nbdown').length, dim: __cy.elements('.dim').length})"
        )
        page.screenshot(path=str(shot_dir / "graph-highlight.png"))
        # 展开总图：出现节和缝
        page.click("#b-arch")
        page.wait_for_timeout(800)
        out["arch_children"] = page.evaluate(
            "({sections: __cy.nodes('[kind = \"section\"]').filter(n => n.id().startsWith('docs/architecture.html#')).length,"
            " seams: __cy.nodes('[kind = \"seam\"]').length})"
        )
        page.screenshot(path=str(shot_dir / "graph-arch-expanded.png"))
        browser.close()
    out["errors"] = errors
    out["external"] = external
    return out


if __name__ == "__main__":
    res = open_graph(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "chrome")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    sys.exit(1 if res["errors"] or res["external"] else 0)
