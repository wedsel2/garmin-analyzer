// Draws a chart in every element that has data-chart, from the JSON API named in
// its data-src, and shows times in the zone of the device. No build step: this
// file is served as it is, next to echarts.min.js (ADR 7).
(() => {
  "use strict";

  const dark = matchMedia("(prefers-color-scheme: dark)");
  // Fixed colours instead of the stylesheet's: ECharts cannot read oklch().
  // `series` is a fixed order that stays apart for colour-blind readers.
  const colours = () =>
    dark.matches
      ? {
          line: "#8a8a85",
          accent: "#3987e5",
          guide: "#55554f",
          grid: "#2f353d",
          surface: "#1d232a",
          tip: "#383835",
          text: "#ffffff",
          label: "#c3c2b7",
          series: ["#3987e5", "#d95926", "#199e70", "#c98500"],
        }
      : {
          line: "#9a9993",
          accent: "#2a78d6",
          guide: "#c9c8c2",
          grid: "#e8e7e3",
          surface: "#ffffff",
          tip: "#ffffff",
          text: "#0b0b0b",
          label: "#52514e",
          series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
        };

  const format = (options) => new Intl.DateTimeFormat(undefined, options);
  // Days come from the API as dates without a zone; read and write them as UTC.
  const dayFormat = format({ weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  const tickFormat = format({ day: "numeric", month: "short", timeZone: "UTC" });
  const longTickFormat = format({ month: "short", year: "2-digit", timeZone: "UTC" });
  const timeFormat = format({ dateStyle: "medium", timeStyle: "short" });
  const clockFormat = format({ hour: "2-digit", minute: "2-digit" });

  const amount = (value, unit) =>
    value === null || value === undefined
      ? "no data"
      : `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}${unit ? ` ${unit}` : ""}`;

  // One request per address, however many charts read from it.
  const requests = new Map();
  const load = (src) => {
    if (!requests.has(src)) {
      requests.set(
        src,
        fetch(src, { headers: { Accept: "application/json" } }).then((response) => {
          if (!response.ok) throw new Error(`${src} answered ${response.status}`);
          return response.json();
        }),
      );
    }
    return requests.get(src);
  };

  // What the charts with axes share. `rows` gives the lines of the tooltip for
  // a day: plain text, as the content security policy refuses inline styles.
  const frame = (element, data, colour, rows, bars) => {
    const weekly = element.dataset.per === "week";
    const tick = data.dates.length > 300 || weekly ? longTickFormat : tickFormat;
    return {
      animation: false,
      grid: { left: 4, right: 12, top: 32, bottom: 4, containLabel: true },
      legend: {
        top: 0,
        left: 0,
        selectedMode: false,
        itemWidth: 14,
        itemHeight: 8,
        textStyle: { color: colour.label, fontSize: 12 },
      },
      xAxis: {
        type: "category",
        data: data.dates,
        boundaryGap: bars,
        axisLine: { lineStyle: { color: colour.grid } },
        axisTick: { show: false },
        axisLabel: {
          color: colour.label,
          hideOverlap: true,
          formatter: (day) => tick.format(new Date(day)),
        },
      },
      yAxis: {
        type: "value",
        scale: !bars,
        splitNumber: 3,
        axisLabel: { color: colour.label },
        splitLine: { lineStyle: { color: colour.grid } },
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        padding: [4, 8],
        backgroundColor: colour.tip,
        borderColor: colour.guide,
        textStyle: { color: colour.text, fontSize: 12 },
        axisPointer: { type: bars ? "shadow" : "line", lineStyle: { color: colour.guide } },
        formatter: ([point]) => {
          if (!point) return "";
          const day = dayFormat.format(new Date(point.name));
          return [weekly ? `Week of ${day}` : day, ...rows(point.dataIndex)].join("<br>");
        },
      },
    };
  };

  // Bars that float between a low and a high value, one per day.
  const spans = (points, colour) => ({
    type: "custom",
    data: points,
    encode: { x: 0, y: [1, 2] },
    renderItem: (_params, api) => {
      const [x, low] = api.coord([api.value(0), api.value(1)]);
      const high = api.coord([api.value(0), api.value(2)])[1];
      const width = Math.max(2, Math.min(16, api.size([1, 0])[0] * 0.6));
      return {
        type: "rect",
        shape: {
          x: x - width / 2,
          y: Math.min(low, high),
          width,
          height: Math.max(2, Math.abs(low - high)),
          r: Math.min(3, width / 2),
        },
        style: { fill: colour },
      };
    },
  });

  const builders = {
    // A trend line without axes: the days in grey, the latest value as a dot,
    // and the average it is compared with as a dashed line.
    sparkline(element, data, colour) {
      const values = data.series[element.dataset.metric];
      const last = values.findLastIndex((value) => value !== null);
      const average = element.dataset.average;
      return {
        animation: false,
        grid: { left: 6, right: 6, top: 6, bottom: 6 },
        xAxis: { type: "category", data: data.dates, show: false, boundaryGap: false },
        yAxis: { type: "value", scale: true, show: false },
        tooltip: {
          trigger: "axis",
          // Above the line instead of over it, and not past the sides of the tile.
          position: ([x], _params, _box, _rect, size) => [
            Math.max(0, Math.min(x - size.contentSize[0] / 2, size.viewSize[0] - size.contentSize[0])),
            -size.contentSize[1] - 4,
          ],
          padding: [4, 8],
          backgroundColor: colour.tip,
          borderColor: colour.guide,
          textStyle: { color: colour.text, fontSize: 12 },
          formatter: ([point]) => {
            if (!point) return "";
            const day = dayFormat.format(new Date(point.name));
            return `${day}: ${amount(values[point.dataIndex], element.dataset.unit)}`;
          },
          axisPointer: { lineStyle: { color: colour.guide } },
        },
        series: [
          {
            type: "line",
            data: values,
            // As wide as the line, so a day between two days without a value still shows.
            symbol: "circle",
            symbolSize: 2,
            showAllSymbol: true,
            lineStyle: { width: 2, color: colour.line },
            itemStyle: { color: colour.line },
            markLine: average && {
              silent: true,
              symbol: "none",
              label: { show: false },
              lineStyle: { type: "dashed", width: 1, color: colour.guide },
              data: [{ yAxis: Number(average) }],
            },
          },
          {
            type: "scatter",
            data: last < 0 ? [] : [[data.dates[last], values[last]]],
            symbolSize: 8,
            itemStyle: { color: colour.accent },
            silent: true,
            tooltip: { show: false },
          },
        ],
      };
    },

    // One metric over time. Per day: the values as dots and their rolling
    // average as the line. Per week: the weekly averages as the line. A second
    // and third metric are the low and high of a band behind it.
    trend(element, data, colour) {
      const [metric, bandLow, bandHigh] = element.dataset.metrics.split(",");
      const unit = element.dataset.unit;
      const values = data.series[metric];
      const rolling = data.rolling?.[metric];
      const low = data.series[bandLow];
      const high = data.series[bandHigh];
      const option = frame(element, data, colour, (index) => [
        ...(rolling ? [`7-day average: ${amount(rolling[index], unit)}`] : []),
        `${rolling ? "This day" : "Average"}: ${amount(values[index], unit)}`,
        ...(low && low[index] !== null && high[index] !== null
          ? [`Balanced: ${Math.round(low[index])} to ${Math.round(high[index])} ${unit}`]
          : []),
      ]);
      const line = {
        type: "line",
        symbol: "circle",
        lineStyle: { width: 2, color: colour.accent },
        itemStyle: { color: colour.accent },
      };
      option.series = rolling
        ? [
            { ...line, name: "7-day average", data: rolling, symbolSize: 2, showAllSymbol: true },
            {
              type: "scatter",
              name: "Per day",
              data: values,
              symbolSize: 5,
              itemStyle: { color: colour.line },
            },
          ]
        : [{ ...line, name: "Weekly average", data: values, symbolSize: 4, showAllSymbol: true }];
      if (low && high) {
        const band = { type: "line", stack: "band", symbol: "none", silent: true };
        option.series.push(
          { ...band, data: low, lineStyle: { opacity: 0 } },
          {
            ...band,
            name: "Balanced range",
            data: high.map((value, index) =>
              value === null || low[index] === null ? null : value - low[index],
            ),
            lineStyle: { opacity: 0 },
            itemStyle: { color: colour.accent, opacity: 0.25 },
            areaStyle: { color: colour.accent, opacity: 0.12 },
          },
        );
      }
      option.legend.data = option.series.filter((series) => series.name).map((series) => series.name);
      return option;
    },

    // Several metrics stacked into one bar per day or week.
    stack(element, data, colour) {
      const metrics = element.dataset.metrics.split(",");
      const labels = element.dataset.labels.split(",");
      const unit = element.dataset.unit;
      const option = frame(
        element,
        data,
        colour,
        (index) => labels.map((label, at) => `${label}: ${amount(data.series[metrics[at]][index], unit)}`),
        true,
      );
      option.series = metrics.map((metric, at) => ({
        type: "bar",
        name: labels[at],
        stack: "total",
        data: data.series[metric],
        barMaxWidth: 16,
        // A gap in the colour of the card keeps the parts apart, where the
        // bars are wide enough to spare it.
        itemStyle: {
          color: colour.series[at],
          borderColor: colour.surface,
          borderWidth: data.dates.length > 31 ? 0 : 1,
        },
      }));
      return option;
    },

    // A low and a high per day, as a floating bar.
    span(element, data, colour) {
      const [lowMetric, highMetric] = element.dataset.metrics.split(",");
      const low = data.series[lowMetric];
      const high = data.series[highMetric];
      const option = frame(
        element,
        data,
        colour,
        (index) =>
          low[index] === null || high[index] === null
            ? ["no data"]
            : [`${low[index]} to ${high[index]}`],
        true,
      );
      // To the ten above the highest value, so a scale of 0 to 100 does not run to 120.
      option.yAxis.max = ({ max }) => Math.ceil(max / 10) * 10;
      option.yAxis.splitNumber = 5;
      option.legend.show = false;
      option.grid.top = 12;
      const points = data.dates
        .map((_day, index) => [index, low[index], high[index]])
        .filter(([, from, to]) => from !== null && to !== null);
      option.series = [spans(points, colour.accent)];
      return option;
    },

    // From bed time to wake time per night, in hours from the midnight of the
    // day of waking, in the zone of this device. Evening is at the top.
    nights(element, data, colour) {
      const nights = data.dates.map((_day, index) => {
        if (!data.start_at[index] || !data.end_at[index]) return null;
        const start = new Date(data.start_at[index]);
        const end = new Date(data.end_at[index]);
        const midnight = new Date(end).setHours(0, 0, 0, 0);
        return { start, end, from: (start - midnight) / 3.6e6, to: (end - midnight) / 3.6e6 };
      });
      const option = frame(
        element,
        data,
        colour,
        (index) =>
          nights[index]
            ? [
                `Asleep: ${clockFormat.format(nights[index].start)}`,
                `Awake: ${clockFormat.format(nights[index].end)}`,
              ]
            : ["no data"],
        true,
      );
      option.legend.show = false;
      option.grid.top = 12;
      Object.assign(option.yAxis, {
        scale: true,
        inverse: true,
        minInterval: 1,
        axisLabel: {
          color: colour.label,
          formatter: (hour) => `${String(((hour % 24) + 24) % 24).padStart(2, "0")}:00`,
        },
      });
      const points = nights
        .map((night, index) => night && [index, night.from, night.to])
        .filter(Boolean);
      option.series = [spans(points, colour.accent)];
      return option;
    },
  };

  const charts = new Map();

  async function draw(element) {
    const data = await load(element.dataset.src);
    if (!element.isConnected) return;
    const chart = charts.get(element) ?? echarts.init(element);
    charts.set(element, chart);
    chart.setOption(builders[element.dataset.chart](element, data, colours()), true);
  }

  function drawAll() {
    // Charts of elements that a swap of the page took away.
    for (const [element, chart] of charts) {
      if (!element.isConnected) {
        chart.dispose();
        charts.delete(element);
      }
    }
    for (const element of document.querySelectorAll("[data-chart]")) {
      draw(element).catch((error) => console.error(error));
    }
  }

  for (const element of document.querySelectorAll("time[data-local]")) {
    element.textContent = timeFormat.format(new Date(element.dateTime));
  }

  if (window.echarts) {
    drawAll();
    dark.addEventListener("change", drawAll);
    addEventListener("resize", () => charts.forEach((chart) => chart.resize()));
    // HTMX has put another period on the page.
    document.addEventListener("htmx:afterSettle", drawAll);
  }
})();
