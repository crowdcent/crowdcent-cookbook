"""Numerai's public GraphQL API, read into polars frames."""

import time
import warnings

import polars as pl
import urllib3

HOST = "api-tournament.numer.ai"
TOURNAMENTS = {"classic": 8, "signals": 11, "crypto": 12}

# Each tournament grades its own pair of metrics under its own names.
METRICS = {
    "classic": ("corr20V2", "mmc"),
    "signals": ("fncV4", "mmc20d"),
    "crypto": ("corr", "mmc"),
}


def _post(document):
    """One POST to Numerai's GraphQL endpoint."""
    answer = urllib3.request(
        "POST",
        f"https://{HOST}/",
        json=document,
        headers={"User-Agent": "crowdcent-cookbook/1.0"},
        timeout=60,
    )
    if answer.status != 200:
        raise RuntimeError(f"{HOST} answered {answer.status}: {answer.data[:200]!r}")
    return answer.json()


def graphql(query, variables=None):
    """One GraphQL query, with two more tries for a flaky edge."""
    for attempt in (1, 2, 3):
        try:
            payload = _post({"query": query, "variables": variables or {}})
        except (urllib3.exceptions.HTTPError, RuntimeError):
            if attempt == 3:
                raise
            time.sleep(2 * attempt)
            continue
        if payload.get("errors"):
            raise RuntimeError(f"Numerai returned errors: {payload['errors']}")
        return payload["data"]


def models(account):
    """Every model in an account: one row per model, with its tournament."""
    query = """
    query($username: String!, $tournament: Int) {
      accountProfile(username: $username, tournament: $tournament) {
        models { id displayName }
      }
    }
    """
    rows = []
    failures = []
    for tournament, number in TOURNAMENTS.items():
        try:
            data = graphql(query, {"username": account, "tournament": number})
        except (urllib3.exceptions.HTTPError, RuntimeError) as exc:
            failures.append(tournament)
            warnings.warn(
                f"{tournament.capitalize()} is unavailable: {exc}", stacklevel=2
            )
            continue
        profile = data["accountProfile"] or {}
        rows += [
            {"tournament": tournament, "model": model["displayName"], "id": model["id"]}
            for model in profile.get("models") or []
        ]
    if len(failures) == len(TOURNAMENTS):
        raise RuntimeError("All Numerai tournaments are unavailable. Try again later.")
    return pl.DataFrame(
        rows, schema={"tournament": pl.String, "model": pl.String, "id": pl.String}
    )


def rounds(models, days=365, tick=None):
    """One row per model and round: stake at risk and payout, resolved or open.

    Numerai answers at most three models per query, so the models go in
    batches of three; ``tick`` is called with each batch's size.
    """
    rows = []
    attempted = answered = 0
    for tournament, number in TOURNAMENTS.items():
        ids = models.filter(pl.col("tournament") == tournament)["id"].to_list()
        for start in range(0, len(ids), 3):
            batch = ids[start : start + 3]
            aliases = " ".join(
                f'm{i}: v2RoundModelPerformances(modelId: "{model_id}", '
                f"tournament: {number}, resolvedWithinLastNDays: {days}, "
                "distinctOnRound: true) "
                "{ roundNumber roundResolved roundResolveTime atRisk payout }"
                for i, model_id in enumerate(batch)
            )
            attempted += 1
            try:
                data = graphql("query { " + aliases + " }")
            except (urllib3.exceptions.HTTPError, RuntimeError) as exc:
                warnings.warn(
                    f"{tournament.capitalize()} rounds are incomplete: {exc}",
                    stacklevel=2,
                )
                if tick:
                    tick(len(batch))
                continue
            answered += 1
            for i, model_id in enumerate(batch):
                rows += [
                    {
                        "id": model_id,
                        "round": entry["roundNumber"],
                        "date": (entry.get("roundResolveTime") or "")[:10] or None,
                        "resolved": bool(entry["roundResolved"]),
                        "at_risk": float(entry["atRisk"] or 0),
                        "payout": float(entry["payout"] or 0),
                    }
                    for entry in data[f"m{i}"] or []
                ]
            if tick:
                tick(len(batch))
    if attempted and not answered:
        raise RuntimeError(
            "Numerai could not return rounds for any model. Try again later."
        )
    schema = {
        "id": pl.String,
        "round": pl.Int64,
        "date": pl.String,
        "resolved": pl.Boolean,
        "at_risk": pl.Float64,
        "payout": pl.Float64,
    }
    return models.join(pl.DataFrame(rows, schema=schema), on="id").with_columns(
        pl.col("date").str.to_date()
    )


def scores(model, tournament):
    """Every scored round of one model: the two metrics its tournament grades."""
    first, second = METRICS[tournament]
    query = f"""
    query($model: String!, $tournament: Int) {{
      v3UserProfile(modelName: $model, tournament: $tournament) {{
        roundModelPerformances {{
          roundNumber roundResolveTime
          {first} {first}Percentile {second} {second}Percentile
        }}
      }}
    }}
    """
    data = graphql(query, {"model": model, "tournament": TOURNAMENTS[tournament]})
    profile = data["v3UserProfile"] or {}
    rows = [
        {
            "round": entry["roundNumber"],
            "date": entry["roundResolveTime"][:10],
            "metric": metric,
            "value": entry[metric],
            "percentile": (
                100 * entry[f"{metric}Percentile"]
                if entry.get(f"{metric}Percentile") is not None
                else None
            ),
        }
        for entry in profile.get("roundModelPerformances") or []
        for metric in (first, second)
        if entry.get(metric) is not None and entry.get("roundResolveTime")
    ]
    schema = {
        "round": pl.Int64,
        "date": pl.String,
        "metric": pl.String,
        "value": pl.Float64,
        "percentile": pl.Float64,
    }
    return (
        pl.DataFrame(rows, schema=schema)
        .with_columns(pl.col("date").str.to_date())
        .sort("round")
    )
