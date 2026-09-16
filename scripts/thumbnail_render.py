"""Shared visual treatment for real notebook figures and small saved artifacts."""

import base64
import datetime as dt
import html
import json
from pathlib import Path

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
import polars as pl

CSS = Path(__file__).with_name("thumbnail.css")


def source_date(captured, figure=None):
    dates = [d["through"] for d in captured["datasets"].values() if d.get("through")]
    if figure:
        for trace in figure.data:
            for value in trace.x if trace.x is not None else []:
                try:
                    dates.append(dt.date.fromisoformat(str(value)[:10]).isoformat())
                except ValueError:
                    continue
    return max(dates) if dates else None


def styled(figure, spec):
    """Only presentation changes; x/y values stay exactly as the notebook produced."""
    fig = go.Figure(figure)
    colors = ("#62e4fb", "#ab8cff", "#e7bf78", "#7fe3b1", "#ef97b6")
    fig.update_layout(
        template="plotly_dark",
        title=None,
        width=552,
        height=218,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Arial, sans-serif", "size": 12, "color": "#9ab3c0"},
        margin={"l": 57, "r": 8, "t": 29, "b": 37},
        legend={
            "orientation": "h",
            "y": 1.18,
            "x": 0,
            "title": None,
            "font": {"size": 12},
        },
    )
    fig.update_xaxes(
        title=None, gridcolor="rgba(154,179,192,.10)", zeroline=False, nticks=5
    )
    fig.update_yaxes(
        title=None, gridcolor="rgba(154,179,192,.10)", zeroline=False, nticks=5
    )
    for i, trace in enumerate(fig.data):
        if trace.type in {"scatter", "scattergl"} and trace.mode != "markers":
            trace.line.update(
                color=colors[i % len(colors)], width=1.5 if len(fig.data) > 3 else 2.5
            )
            trace.update(mode="lines")
        elif trace.type == "bar":
            trace.marker.update(color=colors[i % len(colors)])
        if i < len(spec.get("legend", [])):
            trace.name = spec["legend"][i]
        elif spec.get("legend_prefix"):
            trace.name = spec["legend_prefix"] + str(trace.name)
    if spec.get("x_label"):
        fig.update_xaxes(title={"text": spec["x_label"], "font": {"size": 11}})
    if spec.get("y_label"):
        fig.update_yaxes(title={"text": spec["y_label"], "font": {"size": 11}})
    if spec.get("y_suffix"):
        fig.update_yaxes(ticksuffix=spec["y_suffix"], tickformat="~s")
    if fig.layout.coloraxis.colorscale:
        fig.update_layout(
            coloraxis={
                "colorscale": [[0, colors[0]], [1, colors[1]]],
                "colorbar": {
                    "thickness": 7,
                    "len": 0.85,
                    "title": {"font": {"size": 11}},
                    "tickfont": {"size": 10},
                },
            }
        )
    return fig


def render(spec, captured, browser):
    figure = None
    output = spec["output"]
    if output == "figure":
        index = 0
        if not isinstance(index, int) or not 0 <= index < len(captured["figures"]):
            raise ValueError(
                "Notebook did not produce the selected figure; check its data and form parameters."
            )
        figure = styled(captured["figures"][index], spec)
        if not figure.data or not any(
            len(trace.y) for trace in figure.data if trace.y is not None
        ):
            raise ValueError("Notebook figure contains no data.")
        body = figure.to_html(
            full_html=False,
            include_plotlyjs=False,
            config={"displayModeBar": False, "staticPlot": True},
        )
    else:
        if Path(output).suffix == ".json":
            content = json.dumps(captured["artifact"], indent=2)
            if len(content) > 600:
                raise ValueError(
                    "Choose a smaller JSON artifact for a readable thumbnail."
                )
            body = f'<div class="terminal"><div class="terminal-bar"><span>OUTPUT / {html.escape(output)}</span><span class="ok">✓ SAVED</span></div><pre>{html.escape(content)}</pre></div>'
        else:
            frame = pl.DataFrame(captured["artifact"])
            if frame.is_empty() or frame.width > 4:
                raise ValueError(
                    "A thumbnail table needs rows and at most four columns."
                )
            if spec.get("sort"):
                frame = frame.sort(spec["sort"], descending=True)
            labels = spec.get("columns", {})
            headers = "".join(
                f"<th>{html.escape(labels.get(c, c))}</th>" for c in frame.columns
            )
            rows = []
            for row in frame.head(6).iter_rows():
                cells = "".join(
                    f"<td>{html.escape(f'{v:.3f}' if isinstance(v, float) else str(v))}</td>"
                    for v in row
                )
                rows.append(f"<tr>{cells}</tr>")
            body = f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    through = source_date(captured, figure)
    date_label = (
        f"Through {through}" if through else f"Captured {captured['captured_at'][:10]}"
    )
    markup = f"""<!doctype html><meta charset="utf-8"><style>{CSS.read_text()}</style>
    <script>{get_plotlyjs()}</script><article id="cookbook-preview">
    <header><h1>{html.escape(spec["title"])}</h1><span class="badge">{html.escape(spec.get("badge", "REAL DATA"))}</span></header>
    <div class="preview-body">{body}</div><footer class="provenance"><span>{html.escape(captured["label"])}</span><span>{date_label}</span></footer></article>"""
    page = browser.new_page(
        viewport={"width": 600, "height": 315}, device_scale_factor=2
    )
    try:
        page.route("**/*", lambda route: route.abort())
        page.set_content(markup, wait_until="load")
        page.wait_for_function(
            "!document.querySelector('.plotly-graph-div') || document.querySelector('.plotly-graph-div')._fullLayout !== undefined"
        )
        page.evaluate("document.fonts.ready")
        page.locator(".provenance").wait_for(state="visible")
        png = page.locator("#cookbook-preview").screenshot()
    finally:
        page.close()
    return png, through


def gallery(specs, root):
    """A standalone, offline gallery: no Django login or network requests."""
    from thumbnails import assets, preview

    cards = []
    for slug in specs:
        card = preview((root / "recipes" / slug / f"{slug}.py").read_text())
        directory = assets(slug, root)
        image = directory / "opengraph.png"
        if not image.is_file():
            visual = '<p class="missing">Thumbnail not generated yet</p>'
        else:
            url = (
                "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
            )
            visual = f'<a href="{url}" download="{slug}.png"><img src="{url}" alt="{html.escape(card["title"])}" width="1200" height="630"></a>'
        cards.append(
            f'<article class="card">{visual}<div class="card-body"><h2>{html.escape(card["title"])}</h2><p>{html.escape(card["description"])}</p></div></article>'
        )
    target = root / "out" / "thumbnails" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Cookbook thumbnail review</title><style>{CSS.read_text()}
    body{{background:var(--preview-bg);color:var(--preview-fg);font:15px/1.5 Arial,sans-serif;margin:0;}}
    main{{max-width:1260px;margin:auto;padding:32px 20px;}} h1{{font-size:30px;}} h2{{font-size:20px;line-height:1.3;}}
    .gallery{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;}} .card{{border:1px solid var(--preview-line);background:var(--preview-panel);}}
    .card img{{display:block;width:100%;height:auto;border-bottom:1px solid var(--preview-line);}} .card-body{{padding:18px;}} p{{color:var(--preview-muted);}}
    .missing{{padding:48px 20px;}} @media(max-width:1000px){{.gallery{{grid-template-columns:repeat(2,minmax(0,1fr));}}}}
    @media(max-width:600px){{.gallery{{grid-template-columns:1fr;}}}}
    </style></head><body><main><h1>Cookbook thumbnail review</h1><p>Resize the window to review card readability. Click an image to download the full-size PNG.</p>
    <div class="gallery">{"".join(cards)}</div></main></body></html>""")
    return target
