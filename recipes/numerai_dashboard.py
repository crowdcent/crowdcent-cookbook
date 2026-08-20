# A read-only dashboard over Numerai's public GraphQL API. It submits
# nothing, stakes nothing, and holds no credential of any kind — everything
# below is public data, fetched live wherever the notebook wakes up.
#
# The only wrinkle is how the data arrives. Numerai's API answers CORS
# preflights for numer.ai alone, so a browser tab cannot query it directly;
# framed by the site, the tab posts the same query through the reviewed
# relay for this one host. Everywhere else — a laptop, a scheduled run —
# the notebook speaks to the API itself.
#
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo",
#     "numpy",
#     "plotly==6.9.0",
#     "urllib3==2.7.0",
# ]
#
# [tool.marimo.opengraph]
# title = "Numerai dashboard"
# description = "Live public performance for any Numerai account: payouts, stakes, leaderboard standing, and per-model scores across Classic, Signals, and Crypto. Read-only, no key, in a tab or on a daily schedule."
#
# [tool.crowdcent.cloud]
# default_view = "app"
# ///

import marimo

__generated_with = "0.23.15"
app = marimo.App(width="full")


@app.cell
def _():
    import datetime
    import json
    import os
    import sys

    import marimo as mo

    # Pyodide reports this platform and nothing else does, so it is the one
    # honest way for a notebook to know where it woke up.
    IN_BROWSER = sys.platform == "emscripten"

    API_HOST = "api-tournament.numer.ai"
    TOURNAMENTS = {"classic": 8, "signals": 11, "crypto": 12}
    # Charts sit on whatever ground the page provides — CrowdCent navy when
    # the site frames this notebook, white when marimo runs it plain — so the
    # one color that must switch with the theme is Classic's silver.
    DARK = mo.app_meta().theme == "dark"
    # The palette the CrowdCent NMR LP dashboards have always used, so the
    # tournaments read the same here as everywhere else.
    COLORS = {
        "classic": "#c9c6bc" if DARK else "#7d7a71",
        "signals": "#24aac2",
        "crypto": "#17c843",
        "total": "#7b68ee",
    }
    # And a second pair for score metrics, which are not tournaments.
    METRIC_COLORS = ("#4fb3d9", "#ff8a5c") if DARK else ("#2380a5", "#e4572e")

    # A shared link names the account in the URL, a schedule names it in the
    # environment, and anyone can simply type a name into the box.
    DEFAULT_ACCOUNT = (
        mo.query_params().get("account") or ""
    ).strip() or os.environ.get("NUMERAI_ACCOUNT", "crowdcent")
    return (
        API_HOST,
        COLORS,
        DEFAULT_ACCOUNT,
        IN_BROWSER,
        METRIC_COLORS,
        TOURNAMENTS,
        datetime,
        json,
        mo,
    )


@app.cell
def _(mo):
    mo.md("""
    # Numerai dashboard

    Public performance for any Numerai account, read live from Numerai's
    GraphQL API: daily payouts, stakes at risk, where every model sits on
    the leaderboards, and per-round scores for any model you pick. Nothing
    here holds a key of any kind — every figure below is data anyone could
    fetch.
    """)
    return


@app.cell
def _(DEFAULT_ACCOUNT, mo):
    account_input = mo.ui.text(
        value=DEFAULT_ACCOUNT, label="Numerai account", debounce=True
    )
    # Retyping the account refetches; everything below the fetch recomputes
    # from data already in hand.
    percent_switch = mo.ui.switch(label="as % of stake")
    account_input
    return account_input, percent_switch


@app.cell
def _(API_HOST, IN_BROWSER, json, mo):
    def _post(payload):
        """One POST to Numerai, by whichever road this environment has.

        The client is urllib3 everywhere — inside Pyodide it speaks the
        browser's own fetch machinery. Only the address differs: a tab cannot
        reach Numerai directly, because their CORS answers only numer.ai, so
        framed on the site it posts the same document through the reviewed
        relay named in the frame's own URL — form-encoded, which crosses
        origins without a preflight.
        """
        import urllib3

        if not IN_BROWSER:
            answer = urllib3.request(
                "POST",
                f"https://{API_HOST}/",
                json=payload,
                # Numerai's edge refuses urllib3's default agent outright.
                headers={"User-Agent": "crowdcent-cloud-numerai-dashboard/1.0"},
                timeout=60,
            )
        else:
            from urllib.parse import urlencode

            params = mo.query_params()
            grant, site = params.get("g") or "", params.get("site") or ""
            if not site:
                raise RuntimeError("this tab has no relay to route through")
            form = {
                "body": json.dumps(payload),
                **({"grant": grant} if grant else {}),
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            if not grant:
                # The same-origin dev fallback: no grant, but the session rides
                # along and this header names the caller.
                headers["X-CrowdCent-Cloud"] = "notebook"
            answer = urllib3.request(
                "POST",
                f"{site}/cloud/relay/{API_HOST}/",
                body=urlencode(form),
                headers=headers,
                timeout=60,
            )
        if answer.status != 200:
            refusal = answer.data.decode(errors="replace").strip()[:300]
            raise RuntimeError(f"the road refused ({answer.status}): {refusal}")
        return answer.json()

    def graphql(query, variables):
        """One public GraphQL query, with a short retry for a flaky edge."""
        import time

        for attempt in (1, 2, 3):
            try:
                payload = _post({"query": query, "variables": variables})
                break
            except Exception:  # noqa: BLE001 - the last attempt re-raises
                if attempt == 3:
                    raise
                time.sleep(2 * attempt)
        if payload.get("errors"):
            raise RuntimeError(f"Numerai returned errors: {payload['errors']}")
        return payload["data"]

    return (graphql,)


@app.cell
def _(TOURNAMENTS, graphql, mo):
    MODELS = """
    query($username: String!, $tournament: Int) {
      accountProfile(username: $username, tournament: $tournament) {
        models { id displayName }
      }
    }
    """

    def _models(account, tournament_id):
        data = graphql(MODELS, {"username": account, "tournament": tournament_id})
        profile = data.get("accountProfile") or {}
        return [
            (model["id"], model["displayName"]) for model in profile.get("models") or []
        ]

    def _batch_query(model_ids, tournament_id, days):
        """One document asking after up to three models — Numerai's alias limit.

        Round-level and flat on the wire: the nested per-metric score arrays
        were measured at ~20 s per model where this shape costs well under one.
        """
        aliases = " ".join(
            f'm{index}: v2RoundModelPerformances(modelId: "{model_id}", '
            f"tournament: {tournament_id}, resolvedWithinLastNDays: {days}, "
            "distinctOnRound: true) { atRisk payout roundResolveTime }"
            for index, model_id in enumerate(model_ids)
        )
        return "query { " + aliases + " }"

    def _rounds(model_ids, *, tournament_id, days):
        data = graphql(_batch_query(model_ids, tournament_id, days), {})
        return [data.get(f"m{index}") or [] for index in range(len(model_ids))]

    def _each(function, items, tick=None):
        """Threads where they exist. Pyodide has none and takes them in turn."""
        import sys

        if sys.platform == "emscripten" or len(items) < 2:
            results = []
            for item in items:
                results.append(function(item))
                if tick:
                    tick()
            return results
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(function, item) for item in items]
            for _done in concurrent.futures.as_completed(futures):
                if tick:
                    tick()
            return [future.result() for future in futures]

    def _tournament(models, daily):
        """Fold one tournament's models into the shared per-day ledger.

        The API also returns rounds that have not resolved yet: their resolve
        day sits in the future and their payout is a running projection. They
        stay — the shaded band on the charts marks them — and the at-stake
        figure is each model's newest round, because live rounds overlap and
        summing them would count the same staked NMR several times over.
        """
        at_stake = 0.0
        for rounds in models:
            newest = ("", 0.0)
            for entry in rounds:
                day = (entry.get("roundResolveTime") or "")[:10]
                if not day:
                    continue
                ledger = daily.setdefault(day, [0.0, 0.0])
                ledger[0] += float(entry.get("payout") or 0)
                at_risk = float(entry.get("atRisk") or 0)
                ledger[1] += at_risk
                if at_risk and day > newest[0]:
                    newest = (day, at_risk)
            at_stake += newest[1]
        return at_stake

    def fetch_account(account, days=400):
        """Daily payouts and stakes, across every model in the account.

        Returns ``(rows, stakes, roster, provenance)``. Rows are one small
        dict per tournament-day — tournament, date, payout, NMR at risk, and
        whether that day's rounds are still pending. Stakes map each
        tournament to its models' newest at-risk NMR, and the roster maps it
        to the model names the drill-down below can ask after.
        """
        import datetime as dt
        import functools

        today = dt.date.today().isoformat()
        rows = []
        stakes = {}
        roster = {}
        for name, tournament_id in TOURNAMENTS.items():
            models = _models(account, tournament_id)
            if models:
                roster[name] = [display for _, display in models]
            # Three models per request, the batch ceiling. This matters most in
            # a tab, which has no threads and takes the requests in turn.
            identifiers = [identifier for identifier, _ in models]
            batches = [identifiers[i : i + 3] for i in range(0, len(identifiers), 3)]
            work = functools.partial(_rounds, tournament_id=tournament_id, days=days)
            if mo.running_in_notebook():
                with mo.status.progress_bar(
                    total=max(len(batches), 1),
                    title=f"{name.capitalize()} · {len(models)} models",
                    remove_on_exit=True,
                ) as bar:
                    per_batch = _each(work, batches, tick=bar.update)
            else:
                print(f"{name}: {len(models)} models")
                per_batch = _each(work, batches)

            daily = {}
            at_stake = _tournament(
                [rounds for batch in per_batch for rounds in batch], daily
            )
            if at_stake:
                stakes[name] = round(at_stake, 2)
            rows += [
                {
                    "tournament": name,
                    "date": day,
                    "payout": round(payout, 4),
                    "at_risk": round(at_risk, 2),
                    "pending": day > today,
                }
                for day, (payout, at_risk) in sorted(daily.items())
            ]

        model_count = sum(len(names) for names in roster.values())
        provenance = (
            f"live · {account} · {model_count} models · fetched "
            f"{dt.date.today().isoformat()}"
        )
        return rows, stakes, roster, provenance

    # Each board reports CORR under its own name: corr20V2 on Classic,
    # corrV4 on Signals, plain corr on Crypto. MMC is MMC everywhere.
    _BOARDS = {
        "classic": ("v2Leaderboard", "corr20V2Rep"),
        "signals": ("signalsLeaderboard", "corrV4Rep"),
        "crypto": ("cryptosignalsLeaderboard", "corrRep"),
    }

    def fetch_leaderboards(page=6000):
        """Every model on all three boards — names, ranks, reps, stakes.

        Account-independent, so it is fetched once and matched locally: model
        names need not resemble their account's name. Paged because the
        Classic board alone runs past fifteen thousand entries, and the
        browser road carries answers only up to a fixed size.
        """
        boards = {}
        for name, (query, rep) in _BOARDS.items():
            entries = []
            for offset in range(0, 20 * page, page):
                document = (
                    f"query {{ board: {query}(limit: {page}, offset: {offset}) "
                    f"{{ username rank nmrStaked {rep} mmcRep "
                    "return13Weeks return52Weeks rankChange3m } }"
                )
                batch = graphql(document, {}).get("board") or []
                entries += [
                    {
                        "model": entry["username"],
                        "rank": entry["rank"],
                        "stake": float(entry.get("nmrStaked") or 0),
                        "corr_rep": entry.get(rep),
                        "mmc_rep": entry.get("mmcRep"),
                        "return_13w": entry.get("return13Weeks"),
                        "return_52w": entry.get("return52Weeks"),
                        "rank_shift_3m": entry.get("rankChange3m"),
                    }
                    for entry in batch
                ]
                if len(batch) < page:
                    break
            boards[name] = entries
        return boards

    SCORES = """
    query($modelName: String!, $tournament: Int) {
      v3UserProfile(modelName: $modelName, tournament: $tournament) {
        roundModelPerformances {
          roundNumber roundResolveTime roundResolved
          corr20V2 corr20V2Percentile corr corrPercentile
          fncV4 fncV4Percentile mmc mmcPercentile
          mmc20d mmc20dPercentile payout selectedStakeValue
          corrMultiplier mmcMultiplier
        }
      }
    }
    """

    # Each tournament grades its own pair of metrics, under its own names.
    _METRICS = {
        "classic": (("corr20V2", "CORR"), ("mmc", "MMC")),
        "signals": (("fncV4", "FNCv4"), ("mmc20d", "MMC20d")),
        "crypto": (("corr", "CORR"), ("mmc", "MMC")),
    }

    def fetch_model_scores(model, tournament):
        """Every scored round of one model, flat on the wire and ~1 s to land.

        Returns ``(rounds, labels)``: per-round values and percentiles for
        the two metrics the tournament actually grades, and what to call them.
        """
        data = graphql(
            SCORES, {"modelName": model, "tournament": TOURNAMENTS[tournament]}
        )
        profile = data.get("v3UserProfile") or {}
        (first, first_label), (second, second_label) = _METRICS[tournament]
        rounds = []
        for entry in profile.get("roundModelPerformances") or []:
            values = entry.get(first), entry.get(second)
            if values == (None, None):
                continue
            percentiles = (
                entry.get(f"{first}Percentile"),
                entry.get(f"{second}Percentile"),
            )
            rounds.append(
                {
                    "round": entry["roundNumber"],
                    "date": (entry.get("roundResolveTime") or "")[:10],
                    "resolved": bool(entry.get("roundResolved")),
                    "values": values,
                    "percentiles": tuple(
                        None if pct is None else 100 * pct for pct in percentiles
                    ),
                    "stake": float(entry.get("selectedStakeValue") or 0),
                    "multipliers": (
                        entry.get("corrMultiplier"),
                        entry.get("mmcMultiplier"),
                    ),
                }
            )
        rounds.sort(key=lambda scored: scored["round"])
        return rounds, (first_label, second_label)

    return fetch_account, fetch_leaderboards, fetch_model_scores


@app.cell
def _(datetime):
    def sample_account():
        """A generated account with the exact shape the live fetch returns.

        The offline fallback, nothing more: it renders only when a tab has no
        route to Numerai at all, and it is labelled as a sample everywhere it
        appears, so it can never be mistaken for a live report. The sections
        that only make sense live — leaderboards, per-model scores — say so
        instead of pretending.
        """
        import numpy as np

        rng = np.random.default_rng(0)
        end = datetime.date(2026, 7, 28)
        drifts = {"classic": 0.35, "signals": 0.10, "crypto": 0.22}
        stakes = {"classic": 1200.0, "signals": 340.0, "crypto": 610.0}
        rows = [
            {
                "tournament": tournament,
                "date": (end - datetime.timedelta(days=offset)).isoformat(),
                "payout": round(drift + float(rng.normal(0, 2.4)), 4),
                "at_risk": stakes[tournament],
                "pending": False,
            }
            for tournament, drift in drifts.items()
            for offset in range(180, 0, -1)
        ]
        return (
            rows,
            stakes,
            {},
            f"sample data · generated through {end.isoformat()}",
        )

    return (sample_account,)


@app.cell
def _(
    DEFAULT_ACCOUNT,
    IN_BROWSER,
    account_input,
    fetch_account,
    sample_account,
):
    account = (account_input.value or "").strip() or DEFAULT_ACCOUNT

    try:
        rows, stakes, roster, provenance = fetch_account(account)
        live = True
    except Exception as refusal:  # noqa: BLE001 - a run re-raises, a tab degrades
        if not IN_BROWSER:
            # A scheduled report that quietly rendered a sample would look
            # current while saying nothing. Here, no data is an incident.
            raise
        print(f"no live data from this tab ({refusal}); showing the sample")
        rows, stakes, roster, provenance = sample_account()
        live = False

    if not rows:
        raise RuntimeError(
            f"Numerai returned no resolved rounds for {account!r}. Check the "
            "account name, or try again after today's rounds resolve."
        )
    print(f"{len(rows)} tournament-day rows · {provenance}")
    return live, provenance, roster, rows, stakes


@app.cell
def _(IN_BROWSER, fetch_leaderboards, mo):
    boards = None
    try:
        if mo.running_in_notebook():
            with mo.status.spinner(title="Reading the three leaderboards…"):
                boards = fetch_leaderboards()
        else:
            boards = fetch_leaderboards()
    except Exception as _refusal:  # noqa: BLE001 - a run re-raises, a tab degrades
        if not IN_BROWSER:
            raise
        print(f"leaderboards out of reach from this tab ({_refusal})")
    return (boards,)


@app.cell
def _(datetime, mo, rows):
    # A real date range, spanning the data itself — resolved history and the
    # pending tail both — so the unresolved months sit on the slider, not past
    # its right edge. It opens on the last six months plus everything pending.
    first_day = datetime.date.fromisoformat(min(row["date"] for row in rows))
    _last_day = datetime.date.fromisoformat(max(row["date"] for row in rows))
    _today = min(datetime.date.today(), _last_day)
    date_slider = mo.ui.range_slider(
        start=0,
        stop=(_last_day - first_day).days,
        step=1,
        value=[
            max(0, (_today - datetime.timedelta(days=180) - first_day).days),
            (_last_day - first_day).days,
        ],
        debounce=True,
        full_width=True,
        label="Date range",
    )
    date_slider
    return date_slider, first_day


@app.cell
def _(date_slider, datetime, first_day, rows):
    window_start = first_day + datetime.timedelta(days=date_slider.value[0])
    window_end = first_day + datetime.timedelta(days=date_slider.value[1])
    _start, _end = window_start.isoformat(), window_end.isoformat()
    windowed = [row for row in rows if _start <= row["date"] <= _end]

    # The band starts where history ends: today, clamped into the window.
    anchor = max(window_start, min(datetime.date.today(), window_end))

    # Percentage view: that day's payout against that day's resolving stake.
    daily = [
        dict(row, pct=round(100 * row["payout"] / row["at_risk"], 3))
        for row in windowed
        if row["at_risk"]
    ]

    cumulative = []
    _running = {}
    for _row in sorted(windowed, key=lambda r: (r["tournament"], r["date"])):
        _running[_row["tournament"]] = (
            _running.get(_row["tournament"], 0) + _row["payout"]
        )
        cumulative.append(
            {
                "tournament": _row["tournament"],
                "date": _row["date"],
                "cumulative": round(_running[_row["tournament"]], 4),
            }
        )

    # One more line for the whole account, the way the LP dashboard drew it.
    _by_day = {}
    for _row in windowed:
        _by_day[_row["date"]] = _by_day.get(_row["date"], 0.0) + _row["payout"]
    _total = 0.0
    for _day in sorted(_by_day):
        _total += _by_day[_day]
        cumulative.append(
            {
                "tournament": "total",
                "date": _day,
                "cumulative": round(_total, 4),
            }
        )

    # The headline numbers keep settled and projected apart; the charts show
    # both, with the shaded band marking what may still move.
    totals = {}
    pending = {}
    for _row in windowed:
        _bucket = pending if _row["pending"] else totals
        _bucket[_row["tournament"]] = (
            _bucket.get(_row["tournament"], 0) + _row["payout"]
        )
    return (
        anchor,
        cumulative,
        daily,
        pending,
        totals,
        window_end,
        window_start,
        windowed,
    )


@app.cell
def _(mo, pending, stakes, totals, window_end, window_start, windowed):
    # The texture of the window, from data already in hand: how the account
    # earns, not just how much.
    _days = {}
    for _row in windowed:
        if not _row["pending"] and _row["at_risk"]:
            _days[_row["date"]] = _days.get(_row["date"], 0.0) + _row["payout"]
    _series = [payout for _, payout in sorted(_days.items())]

    _peak = _valley = _running = _drawdown = 0.0
    for _payout in _series:
        _running += _payout
        _peak = max(_peak, _running)
        _drawdown = max(_drawdown, _peak - _running)

    _streak = 0
    for _payout in reversed(_series):
        if _payout < 0:
            break
        _streak += 1

    _best = max(_days.items(), key=lambda item: item[1]) if _days else None
    _worst = min(_days.items(), key=lambda item: item[1]) if _days else None
    _hits = sum(1 for _payout in _series if _payout > 0)

    def _stat(tournament):
        earned = totals.get(tournament, 0.0)
        projected = pending.get(tournament, 0.0)
        notes = []
        if tournament in stakes:
            notes.append(f"{stakes[tournament]:,.0f} NMR at risk")
        if projected:
            notes.append(f"{projected:+,.1f} pending")
        return mo.stat(
            value=f"{earned:+,.1f} NMR",
            label=tournament.capitalize(),
            caption=" · ".join(notes) or "no stake",
            direction="increase" if earned >= 0 else "decrease",
        )

    _texture = []
    if stakes and _series:
        _return = 100 * sum(_series) / sum(stakes.values())
        _texture.append(
            mo.stat(
                value=f"{_return:+,.1f}%",
                label="Return on stake",
                caption="window payout ÷ stake at risk today",
                direction="increase" if _return >= 0 else "decrease",
            )
        )
    if _series:
        _texture += [
            mo.stat(
                value=f"{100 * _hits / len(_series):,.0f}%",
                label="Days in the green",
                caption=f"of {len(_series)} resolved days",
            ),
            mo.stat(
                value=f"{_streak}",
                label="Burn-free streak",
                caption="resolved days without a burn",
            ),
            mo.stat(
                value=f"{_drawdown:,.1f} NMR",
                label="Max drawdown",
                caption="peak to trough, resolved payouts",
            ),
            mo.stat(
                value=f"{_best[1]:+,.1f}",
                label="Best day",
                caption=_best[0],
                direction="increase",
            ),
            mo.stat(
                value=f"{_worst[1]:+,.1f}",
                label="Worst day",
                caption=_worst[0],
                direction="decrease" if _worst[1] < 0 else "increase",
            ),
        ]

    mo.vstack(
        [
            mo.md(
                "### Resolved payout · "
                f"{window_start.isoformat()} → {window_end.isoformat()}"
            ),
            mo.hstack(
                [_stat(name) for name in ("classic", "signals", "crypto")],
                justify="space-around",
                gap=2,
            ),
            mo.hstack(_texture, justify="space-around", gap=1),
        ]
    )
    return


@app.cell
def _(DARK):
    import plotly.graph_objects as go

    def rgba(hex_color, alpha):
        red, green, blue = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
        return f"rgba({red},{green},{blue},{alpha})"

    def styled(figure, *, title, subtitle="", height=340):
        """One voice for every chart: quiet grid, top legend, unified hover.

        Transparent grounds, so the figures sit on the page rather than on
        white cards floating in it — whichever theme the page brought.
        """
        figure.update_layout(
            template="plotly_dark" if DARK else "plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            title={
                "text": title,
                "subtitle": {"text": subtitle, "font": {"color": "#8a8a90"}},
            },
            height=height,
            margin={"l": 8, "r": 8, "t": 104, "b": 8},
            hovermode="x unified",
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "x": 1.0,
                "xanchor": "right",
                "title": None,
                "font": {"size": 11},
            },
            font={"family": "Inter, system-ui, sans-serif", "size": 12},
            xaxis={"type": "date", "title": None},
        )
        return figure

    def rolling(values, width=20):
        """A simple trailing mean, None-safe, warm from the first round."""
        window, out = [], []
        for value in values:
            if value is not None:
                window.append(value)
                if len(window) > width:
                    window.pop(0)
            out.append(sum(window) / len(window) if window else None)
        return out

    return go, rgba, rolling, styled


@app.cell
def _(
    COLORS,
    anchor,
    cumulative,
    daily,
    go,
    mo,
    percent_switch,
    rgba,
    stakes,
    styled,
    windowed,
):
    _open_days = sorted(row["date"] for row in windowed if row["pending"])
    _pending_note = "Shaded rounds are still open; their payouts are projections."

    def _banded(figure):
        if _open_days:
            figure.add_vrect(
                x0=anchor.isoformat(),
                x1=_open_days[-1],
                fillcolor=rgba("#62e4fb", 0.13),
                line_width=0,
            )
        return figure

    def _zeroed(figure):
        figure.add_hline(y=0, line_width=1, line_color="#9a9aa0")
        return figure

    def _lines(names):
        figure = go.Figure()
        for _name in names:
            _points = [row for row in cumulative if row["tournament"] == _name]
            if not _points:
                continue
            figure.add_trace(
                go.Scatter(
                    x=[row["date"] for row in _points],
                    y=[row["cumulative"] for row in _points],
                    name=_name,
                    mode="lines",
                    line={
                        "color": COLORS[_name],
                        "width": 3.5 if _name == "total" else 2,
                    },
                    hovertemplate="%{y:+,.1f}<extra>" + _name + "</extra>",
                )
            )
        return figure

    cumulative_fig = _zeroed(
        _banded(
            styled(
                _lines(("classic", "signals", "crypto", "total")),
                title="Cumulative payout",
                subtitle=_pending_note,
            )
        )
    )
    cumulative_fig.update_yaxes(title="NMR", ticksuffix="")

    _percent = percent_switch.value
    daily_fig = go.Figure()
    for _name in ("classic", "signals", "crypto"):
        _bars = [row for row in daily if row["tournament"] == _name]
        if not _bars:
            continue
        daily_fig.add_trace(
            go.Bar(
                x=[row["date"] for row in _bars],
                y=[row["pct"] if _percent else row["payout"] for row in _bars],
                name=_name,
                marker={"color": COLORS[_name], "line": {"width": 0}},
                hovertemplate=(
                    "%{y:+,.2f}" + ("%" if _percent else "") + f"<extra>{_name}</extra>"
                ),
            )
        )
    daily_fig = _zeroed(
        _banded(
            styled(
                daily_fig,
                title="Earns and burns by resolution day",
                subtitle=_pending_note,
            )
        )
    )
    daily_fig.update_layout(barmode="relative", bargap=0.15)
    daily_fig.update_yaxes(title="% of stake" if _percent else "NMR")

    at_risk_fig = go.Figure()
    for _name in ("classic", "signals", "crypto"):
        _bars = [
            row for row in windowed if row["tournament"] == _name and row["at_risk"]
        ]
        if not _bars:
            continue
        # Bars, not area: tournaments resolve on different days, and an area
        # stacked over sparse dates saws down to zero between them.
        at_risk_fig.add_trace(
            go.Bar(
                x=[row["date"] for row in _bars],
                y=[row["at_risk"] for row in _bars],
                name=_name,
                marker={"color": COLORS[_name], "line": {"width": 0}},
                hovertemplate="%{y:,.0f} NMR<extra>" + _name + "</extra>",
            )
        )
    at_risk_fig = _banded(
        styled(
            at_risk_fig,
            title="NMR at risk by resolution day",
            subtitle="Shaded rounds are still open; that stake has not settled.",
        )
    )
    at_risk_fig.update_layout(barmode="stack", bargap=0.15)
    at_risk_fig.update_yaxes(title="NMR")

    _by_size = sorted(stakes, key=stakes.get, reverse=True)
    stake_fig = go.Figure(
        go.Bar(
            x=[stakes[name] for name in _by_size],
            y=[name.capitalize() for name in _by_size],
            orientation="h",
            marker={"color": [COLORS[name] for name in _by_size]},
            hovertemplate="%{x:,.0f} NMR<extra></extra>",
        )
    )
    stake_fig = styled(
        stake_fig,
        title="Stake at risk",
        subtitle="Each model's newest live round.",
    )
    stake_fig.update_layout(hovermode="y", xaxis={"title": "NMR", "type": "linear"})
    stake_fig.update_yaxes(autorange="reversed")

    view = mo.ui.tabs(
        {
            "Payouts": mo.vstack(
                [
                    mo.hstack([cumulative_fig, daily_fig], widths="equal", gap=1),
                    percent_switch,
                ]
            ),
            "Stakes": mo.hstack([at_risk_fig, stake_fig], widths="equal", gap=1),
        }
    )
    view
    return


@app.cell
def _(COLORS, DARK, boards, go, live, mo, rgba, roster):
    from plotly.subplots import make_subplots

    standing = []
    if boards:
        for _name, _models in roster.items():
            _wanted = set(_models)
            _field = boards.get(_name) or []
            for _entry in _field:
                if _entry["model"] in _wanted:
                    standing.append(
                        {**_entry, "tournament": _name, "field": len(_field)}
                    )
    standing.sort(key=lambda entry: entry["rank"] / entry["field"])

    def _percentile(entry):
        return 100 * entry["rank"] / entry["field"]

    if standing:
        _best = standing[0]
        _header = mo.md(
            "## Leaderboard standing\n"
            f"{len(standing)} models on the boards. Best seat: "
            f"**{_best['model']}** — rank {_best['rank']:,} of "
            f"{_best['field']:,} on {_best['tournament']} "
            f"(top {_percentile(_best):.1f}%)."
        )

        _map = make_subplots(
            rows=1,
            cols=3,
            subplot_titles=[
                f"{name.capitalize()} · {len(boards.get(name) or []):,} models"
                for name in ("classic", "signals", "crypto")
            ],
            horizontal_spacing=0.06,
        )
        for _column, _name in enumerate(("classic", "signals", "crypto"), start=1):
            _field = boards.get(_name) or []
            # The whole field as a quiet backdrop, decimated: its shape is the
            # point, not any single stranger's model.
            _backdrop = [
                entry
                for entry in _field
                if entry["corr_rep"] is not None and entry["mmc_rep"] is not None
            ]
            _step = max(1, len(_backdrop) // 3000)
            _backdrop = _backdrop[::_step]
            _map.add_trace(
                go.Scattergl(
                    x=[entry["corr_rep"] for entry in _backdrop],
                    y=[entry["mmc_rep"] for entry in _backdrop],
                    mode="markers",
                    marker={
                        "color": "#5c6b78" if DARK else "#d4d4da",
                        "size": 3,
                        "opacity": 0.5,
                    },
                    hoverinfo="skip",
                    showlegend=False,
                ),
                row=1,
                col=_column,
            )
            _mine = [
                entry
                for entry in standing
                if entry["tournament"] == _name
                and entry["corr_rep"] is not None
                and entry["mmc_rep"] is not None
            ]
            if not _mine:
                continue
            _heaviest = max(entry["stake"] for entry in _mine) or 1.0
            _map.add_trace(
                go.Scatter(
                    x=[entry["corr_rep"] for entry in _mine],
                    y=[entry["mmc_rep"] for entry in _mine],
                    mode="markers",
                    marker={
                        "color": rgba(COLORS[_name], 0.9),
                        "size": [
                            6 + 14 * (entry["stake"] / _heaviest) ** 0.5
                            for entry in _mine
                        ],
                        "line": {"color": "#ffffff", "width": 1},
                    },
                    text=[entry["model"] for entry in _mine],
                    customdata=[
                        [
                            entry["rank"],
                            entry["field"],
                            _percentile(entry),
                            entry["stake"],
                        ]
                        for entry in _mine
                    ],
                    hovertemplate=(
                        "<b>%{text}</b><br>rank %{customdata[0]:,} of "
                        "%{customdata[1]:,} · top %{customdata[2]:.1f}%<br>"
                        "stake %{customdata[3]:,.0f} NMR<extra></extra>"
                    ),
                    showlegend=False,
                ),
                row=1,
                col=_column,
            )
        _map.update_layout(
            template="plotly_dark" if DARK else "plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=380,
            margin={"l": 8, "r": 8, "t": 48, "b": 8},
            font={"family": "Inter, system-ui, sans-serif", "size": 12},
            title=None,
        )
        _map.update_xaxes(title="CORR reputation", title_font={"size": 11})
        _map.update_yaxes(title="MMC reputation", title_font={"size": 11}, col=1)

        _table = mo.ui.table(
            [
                {
                    "model": entry["model"],
                    "board": entry["tournament"],
                    "rank": entry["rank"],
                    "top %": round(_percentile(entry), 1),
                    "CORR rep": entry["corr_rep"],
                    "MMC rep": entry["mmc_rep"],
                    "stake": entry["stake"],
                    "13w return": entry["return_13w"],
                    "52w return": entry["return_52w"],
                }
                # Staked models first — that is where the money is — and every
                # column stays sortable for anyone after a different question.
                for entry in sorted(
                    standing, key=lambda e: (-e["stake"], e["rank"] / e["field"])
                )
            ],
            page_size=10,
            selection=None,
            format_mapping={
                "CORR rep": lambda v: "" if v is None else f"{v:+.4f}",
                "MMC rep": lambda v: "" if v is None else f"{v:+.4f}",
                "stake": lambda v: f"{v:,.0f}",
                "13w return": lambda v: "" if v is None else f"{v:+,.1f}%",
                "52w return": lambda v: "" if v is None else f"{v:+,.1f}%",
            },
        )
        _section = mo.vstack([_header, _map, _table])
    elif live:
        _section = mo.vstack(
            [
                mo.md("## Leaderboard standing"),
                mo.callout(
                    "None of this account's models appear on the current "
                    "leaderboards, or the boards could not be fetched from here.",
                    kind="info",
                ),
            ]
        )
    else:
        _section = mo.vstack(
            [
                mo.md("## Leaderboard standing"),
                mo.callout(
                    "Leaderboards need a live route to Numerai, and this tab "
                    "has none — open the notebook on crowdcent.com or run it "
                    "locally to see where the models sit.",
                    kind="info",
                ),
            ]
        )
    _section
    return (standing,)


@app.cell
def _(mo, roster, standing):
    # The drill-down picker: models carrying real stake first, because that
    # is where the reader's money and attention already are, then the rest by
    # rank. The roster catches models the boards have not seen.
    _options = {}
    for _entry in sorted(standing, key=lambda e: (-e["stake"], e["rank"] / e["field"])):
        _label = f"{_entry['model']} · {_entry['tournament']} · #{_entry['rank']:,}"
        if _entry["stake"]:
            _label += f" · {_entry['stake']:,.0f} NMR"
        _options[_label] = (_entry["model"], _entry["tournament"])
    _listed = {value for value in _options.values()}
    for _name, _models in roster.items():
        for _model in _models:
            if (_model, _name) not in _listed:
                _options[f"{_model} · {_name}"] = (_model, _name)

    model_picker = (
        mo.ui.dropdown(
            options=_options,
            value=next(iter(_options)),
            label="Model",
            searchable=True,
        )
        if _options
        else None
    )

    mo.vstack(
        [
            mo.md("## One model, every round"),
            model_picker
            if model_picker is not None
            else mo.callout(
                "Per-model scores need a live route to Numerai, and this tab has none.",
                kind="info",
            ),
        ]
    )
    return (model_picker,)


@app.cell
def _(
    METRIC_COLORS,
    datetime,
    fetch_model_scores,
    go,
    mo,
    model_picker,
    rgba,
    rolling,
    styled,
):
    drill = None
    if model_picker is not None:
        _model, _name = model_picker.value
        if mo.running_in_notebook():
            with mo.status.spinner(title=f"Reading every round of {_model}…"):
                scored, _labels = fetch_model_scores(_model, _name)
        else:
            scored, _labels = fetch_model_scores(_model, _name)

        _dates = [entry["date"] for entry in scored]
        _open = sorted(entry["date"] for entry in scored if not entry["resolved"])
        _today = datetime.date.today().isoformat()

        def _drill_banded(figure):
            if _open:
                figure.add_vrect(
                    x0=min(_open[0], _today),
                    x1=_open[-1],
                    fillcolor=rgba("#62e4fb", 0.13),
                    line_width=0,
                )
            return figure

        _scores_fig = go.Figure()
        for _index, _label in enumerate(_labels):
            # The raw rounds stay out of the legend; the mean line carries
            # the name for both.
            _scores_fig.add_trace(
                go.Scatter(
                    x=_dates,
                    y=[entry["values"][_index] for entry in scored],
                    mode="markers",
                    marker={
                        "color": rgba(METRIC_COLORS[_index], 0.35),
                        "size": 4,
                    },
                    showlegend=False,
                    hovertemplate="%{y:+.4f}<extra>" + _label + "</extra>",
                )
            )
            _scores_fig.add_trace(
                go.Scatter(
                    x=_dates,
                    y=rolling([entry["values"][_index] for entry in scored]),
                    name=_label,
                    mode="lines",
                    line={"color": METRIC_COLORS[_index], "width": 2.5},
                    hovertemplate="%{y:+.4f}<extra>" + _label + " mean</extra>",
                )
            )
        _scores_fig.add_hline(y=0, line_width=1, line_color="#9a9aa0")
        _scores_fig = _drill_banded(
            styled(
                _scores_fig,
                title=f"Scores by round · {_model}",
                subtitle=(
                    "Every scored round, all time. Shaded rounds are still "
                    "open; their scores are running."
                ),
            )
        )

        _pct_fig = go.Figure()
        for _index, _label in enumerate(_labels):
            _pct_fig.add_trace(
                go.Scatter(
                    x=_dates,
                    y=rolling([entry["percentiles"][_index] for entry in scored]),
                    name=f"{_label} percentile",
                    mode="lines",
                    line={"color": METRIC_COLORS[_index], "width": 2.5},
                    hovertemplate="%{y:.0f}th<extra>" + _label + "</extra>",
                )
            )
        _pct_fig.add_hline(y=50, line_width=1, line_color="#9a9aa0", line_dash="dot")
        _pct_fig = _drill_banded(
            styled(
                _pct_fig,
                title="Percentile in the field",
                subtitle="20-round trailing mean; 50 is the middle of the pack.",
            )
        )
        _pct_fig.update_yaxes(range=[0, 100], title="percentile")

        _settled = [entry for entry in scored if entry["resolved"]]
        _latest = scored[-1] if scored else None
        _facts = [f"{len(_settled):,} resolved rounds"]
        for _index, _label in enumerate(_labels):
            _values = [
                entry["values"][_index]
                for entry in _settled
                if entry["values"][_index] is not None
            ]
            if not _values:
                continue
            _hit = sum(1 for value in _values if value > 0) / len(_values)
            _facts.append(
                f"{_label} {sum(_values) / len(_values):+.4f} mean, "
                f"positive in {100 * _hit:,.0f}% of rounds"
            )
        if _latest and _latest["stake"]:
            _first_x, _second_x = (
                0 if value is None else value for value in _latest["multipliers"]
            )
            _facts.append(
                f"staking {_latest['stake']:,.0f} NMR at "
                f"{_first_x:g}× / {_second_x:g}× multipliers"
            )
        drill = mo.vstack(
            [
                mo.hstack([_scores_fig, _pct_fig], widths="equal", gap=1),
                mo.md(" · ".join(_facts)),
            ]
        )
    drill
    return


@app.cell
def _(mo, provenance):
    mo.md(f"""
    ---
    *{provenance}.* All figures are public data from Numerai's GraphQL API,
    denominated in NMR and gross of anything Numerai nets off elsewhere.
    This notebook cannot submit or stake: it holds no key anywhere it runs,
    and the one host it reads — directly on hardware, through the site's
    reviewed relay in a tab — is `api-tournament.numer.ai`.
    """)
    return


if __name__ == "__main__":
    app.run()
