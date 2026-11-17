"""Build one portable HTML file with hourly data and no CDN dependencies."""

import html
import json
from pathlib import Path

from .core import ROOT


def build_site(output, manifest, series, threshold):
    web = ROOT / "heat_exposure/web"
    content = (web / "template.html").read_text(encoding="utf-8")
    palette = ["#ae4b26", "#246a80", "#6657a5", "#397548"]
    legend = "".join(f'<span><b style="color:{palette[i % len(palette)]}">■</b> {html.escape(site["name"])}</span>'
                     for i, site in enumerate(manifest["sites"]))
    payload = {"manifest": manifest, "threshold": threshold,
               "values": {site: [temp for _, temp in rows] for site, rows in series.items()}}
    # Prevent source metadata from terminating the JSON script element.
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    content = content.replace("<!--LEGEND-->", legend)
    content = content.replace("__METRICS__", (web / "metrics.js").read_text(encoding="utf-8"))
    content = content.replace("__APP__", (web / "app.js").read_text(encoding="utf-8"))
    content = content.replace("__DATA__", encoded)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(content, encoding="utf-8")
