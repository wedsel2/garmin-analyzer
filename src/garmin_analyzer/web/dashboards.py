"""The pages per metric family: charts over a period the user picks. See ADR 18."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from garmin_analyzer import training
from garmin_analyzer.intraday import INTRADAY_METRICS
from garmin_analyzer.metrics import DAILY_METRICS, daily_series, first_day, mean
from garmin_analyzer.models import User
from garmin_analyzer.web.api import MAX_DAYS
from garmin_analyzer.web.overview import day_label, phrase
from garmin_analyzer.web.shared import CurrentUser, Db, number, templates, today

router = APIRouter()

# The days a trend line averages over when a chart shows a point per day.
ROLLING_DAYS = 7


@dataclass(frozen=True)
class Period:
    label: str
    # None for everything there is.
    days: int | None
    # Long periods show an average per week instead of every day.
    weekly: bool = False


PERIODS = {
    "7d": Period("7 days", 7),
    "4w": Period("4 weeks", 28),
    "3m": Period("3 months", 91),
    "1y": Period("1 year", 365, weekly=True),
    "all": Period("All", None, weekly=True),
}
DEFAULT_PERIOD = "4w"


@dataclass(frozen=True)
class Chart:
    """A chart on a page. What the metrics mean depends on the kind:

    trend   the first is the line; a second and third are the low and high of a band
    lines   a line each; `band` names the low and high of a band behind them
    stack   stacked on each other, in this order
    span    a low and a high per day
    nights  none: from bed time to wake time
    volume  none: hours of activities per week, by sport
    """

    kind: str
    title: str
    metrics: tuple[str, ...] = ()
    about: str = ""
    # The metric whose average is the figure above the chart.
    headline: str | None = None
    # The figure is the latest value instead of the average.
    latest: bool = False
    band: tuple[str, str] | None = None
    band_label: str = ""


RECOVERY = (
    Chart("trend", "Resting heart rate", ("resting_hr",), headline="resting_hr"),
    Chart(
        "trend",
        "HRV",
        ("hrv", "hrv_baseline_low", "hrv_baseline_high"),
        "Average of the night. The band is the range Garmin calls balanced for you.",
        headline="hrv",
    ),
    Chart("trend", "Stress", ("avg_stress",), "Average of the day.", headline="avg_stress"),
    Chart(
        "span",
        "Body battery",
        ("body_battery_low", "body_battery_high"),
        "From the lowest to the highest level of the day.",
    ),
)

SLEEP = (
    Chart(
        "stack",
        "Sleep stages",
        ("sleep_deep", "sleep_light", "sleep_rem", "sleep_awake"),
        headline="sleep_duration",
    ),
    Chart("trend", "Sleep score", ("sleep_score",), headline="sleep_score"),
    Chart("nights", "Bed and wake times", about="In the time zone of this device."),
)


TRAINING = (
    Chart(
        "lines",
        "Training load",
        ("acute_load", "chronic_load"),
        "Acute is the load of the last 7 days, chronic that of the last 4 weeks. "
        "Acute load is optimal from 0.8 to 1.5 times the chronic load.",
        headline="acute_load",
        latest=True,
        band=("load_optimal_low", "load_optimal_high"),
        band_label="Optimal range",
    ),
    Chart(
        "stack",
        "Load focus",
        ("load_aerobic_low", "load_aerobic_high", "load_anaerobic"),
        "The load of the last 4 weeks per intensity, as Garmin sums it up.",
    ),
    Chart("trend", "Training readiness", ("training_readiness",), headline="training_readiness"),
    Chart("lines", "VO2 max", ("vo2max_running", "vo2max_cycling")),
    Chart("volume", "Time per week", about="Hours of activities per week, by sport."),
)


@dataclass(frozen=True)
class ChartView:
    """A chart as the template needs it."""

    chart: Chart
    # Where the chart script gets the values, or None when the chart cannot be shown.
    src: str | None
    labels: str
    unit: str
    # The figure above the chart: the average or the latest value of the headline.
    figure: float | None
    missing: str = ""
    weekly: bool = False


def start_of(period: Period, db: Session, user_id: uuid.UUID, end: date) -> date:
    if period.days is not None:
        return end - timedelta(days=period.days - 1)
    first = first_day(db, user_id) or end
    return max(first, end - timedelta(days=MAX_DAYS - 1))


def chart_views(
    db: Session, user_id: uuid.UUID, charts: tuple[Chart, ...], period: Period, end: date
) -> list[ChartView]:
    start = start_of(period, db, user_id, end)
    headlines = [chart.headline for chart in charts if chart.headline]
    values = daily_series(db, user_id, start, end, headlines)
    span = f"start={start}&end={end}"
    views = []
    for chart in charts:
        metrics = [DAILY_METRICS[key] for key in chart.metrics]
        names = ",".join(chart.metrics + (chart.band or ()))
        figure = None
        if chart.headline:
            measured = [value for value in values[chart.headline] if value is not None]
            latest = measured[-1] if measured else None
            figure = latest if chart.latest else mean(values[chart.headline])
        missing = ""
        weekly = period.weekly
        if chart.kind == "nights":
            src = None if period.weekly else f"/api/v1/nights?{span}"
            missing = "Shown for periods up to 3 months."
        elif chart.kind == "volume":
            src, weekly = f"/api/v1/activity-weeks?{span}", True
        elif period.weekly:
            src = f"/api/v1/weekly?{span}&metrics={names}"
        else:
            rolling = f"&rolling={ROLLING_DAYS}" if chart.kind == "trend" else ""
            src = f"/api/v1/daily?{span}&metrics={names}{rolling}"
        if chart.headline and figure is None:
            src, missing = None, "No data in this period."
        unit_of = chart.headline or next(iter(chart.metrics), None)
        views.append(
            ChartView(
                chart,
                src,
                ",".join(metric.label for metric in metrics),
                DAILY_METRICS[unit_of].unit if unit_of else "h",
                figure,
                missing,
                weekly,
            )
        )
    return views


def page(
    request: Request,
    db: Session,
    user: User,
    title: str,
    charts: tuple[Chart, ...],
    key: str,
    template: str = "dashboard.html",
    **more: object,
) -> Response:
    key = key if key in PERIODS else DEFAULT_PERIOD
    period = PERIODS[key]
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "title": title,
            "periods": PERIODS,
            "active": key,
            "period": period,
            "charts": chart_views(db, user.id, charts, period, today()),
            **more,
        },
    )


PeriodKey = Annotated[str, Query(alias="period")]


@router.get("/recovery")
def recovery(
    request: Request, db: Db, user: CurrentUser, key: PeriodKey = DEFAULT_PERIOD
) -> Response:
    return page(request, db, user, "Recovery", RECOVERY, key)


@router.get("/sleep")
def sleep(request: Request, db: Db, user: CurrentUser, key: PeriodKey = DEFAULT_PERIOD) -> Response:
    return page(request, db, user, "Sleep", SLEEP, key)


# The days the calendar of activities goes back.
CALENDAR_DAYS = 365


@router.get("/training")
def training_page(
    request: Request, db: Db, user: CurrentUser, key: PeriodKey = DEFAULT_PERIOD
) -> Response:
    end = today()
    period = PERIODS[key if key in PERIODS else DEFAULT_PERIOD]
    return page(
        request,
        db,
        user,
        "Training",
        TRAINING,
        key,
        "training.html",
        predictions=training.predictions(db, user.id, start_of(period, db, user.id, end), end),
        readiness=training.latest_readiness(db, user.id),
        day_label=day_label,
        phrase=phrase,
        today=end,
        calendar_src=(
            f"/api/v1/activity-days?start={end - timedelta(days=CALENDAR_DAYS - 1)}&end={end}"
        ),
    )


# The charts of the day view. One request holds the metrics that share a bucket;
# steps come per quarter of an hour, so finer buckets would stay empty.
DAY_METRICS = ("heart_rate", "stress", "body_battery", "respiration", "hrv")
DAY_CHARTS = (
    ("heart_rate", "line"),
    ("stress", "line"),
    ("body_battery", "line"),
    ("steps", "bar"),
    ("respiration", "line"),
    ("hrv", "line"),
)
DAY_SOURCES = {
    "line": f"/api/v1/intraday?metrics={','.join(DAY_METRICS)}&bucket=300",
    "bar": "/api/v1/intraday?metrics=steps&bucket=900",
}


def figures_of(db: Session, user_id: uuid.UUID, day: date) -> list[tuple[str, str]]:
    """What Garmin summed up for the day, as a label and a text each."""
    keys = [
        "steps",
        "resting_hr",
        "avg_stress",
        "body_battery_low",
        "body_battery_high",
        "sleep_duration",
        "sleep_score",
    ]
    steps, resting, stress, low, high, slept, score = (
        values[0] for values in daily_series(db, user_id, day, day, keys).values()
    )
    figures = []
    if steps is not None:
        figures.append(("Steps", number(steps)))
    if resting is not None:
        figures.append(("Resting heart rate", f"{number(resting)} bpm"))
    if stress is not None:
        figures.append(("Stress", number(stress)))
    if low is not None and high is not None:
        figures.append(("Body battery", f"{number(low)} to {number(high)}"))
    if slept is not None:
        scored = f", score {number(score)}" if score is not None else ""
        figures.append(("Sleep", f"{number(slept, 'h')} h{scored}"))
    return figures


@router.get("/day")
def day(
    request: Request, db: Db, user: CurrentUser, asked: Annotated[str, Query(alias="date")] = ""
) -> Response:
    """One day in detail. Which hours belong to it is for the browser to say: it knows the zone."""
    latest = today()
    try:
        shown = min(date.fromisoformat(asked), latest)
    except ValueError:
        shown = latest
    return templates.TemplateResponse(
        request,
        "day.html",
        {
            "user": user,
            "day": shown,
            "label": f"{shown:%A} {shown.day} {shown:%B %Y}",
            "previous": shown - timedelta(days=1),
            "next": shown + timedelta(days=1) if shown < latest else None,
            "figures": figures_of(db, user.id, shown),
            "charts": [
                (INTRADAY_METRICS[key], key, style, DAY_SOURCES[style]) for key, style in DAY_CHARTS
            ],
        },
    )
