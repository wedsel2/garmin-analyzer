// Draws a chart in every element that has data-chart, from the JSON API named in
// its data-src, and shows times in the zone of the device. No build step: this
// file is served as it is, next to echarts.min.js (ADR 7).
(() => {
  "use strict";

  const dark = matchMedia("(prefers-color-scheme: dark)");
  // Fixed colours instead of the stylesheet's: ECharts cannot read oklch().
  const colours = () =>
    dark.matches
      ? { line: "#8a8a85", accent: "#3987e5", guide: "#55554f", tip: "#383835", text: "#ffffff" }
      : { line: "#9a9993", accent: "#2a78d6", guide: "#c9c8c2", tip: "#ffffff", text: "#0b0b0b" };

  const dayFormat = new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
  const timeFormat = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

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

  const builders = {
    // A trend line without axes: the days in grey, the latest value as a dot,
    // and the average it is compared with as a dashed line.
    sparkline(element, data, colour) {
      const values = data.series[element.dataset.metric];
      const unit = element.dataset.unit ? ` ${element.dataset.unit}` : "";
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
          // Plain text: the page's content security policy refuses inline styles.
          formatter: ([point]) => {
            if (!point) return "";
            const value = values[point.dataIndex];
            const day = dayFormat.format(new Date(point.name));
            return value === null
              ? `${day}: no data`
              : `${day}: ${value.toLocaleString()}${unit}`;
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
  };

  const charts = new Map();

  async function draw(element) {
    const data = await load(element.dataset.src);
    const chart = charts.get(element) ?? echarts.init(element);
    charts.set(element, chart);
    chart.setOption(builders[element.dataset.chart](element, data, colours()), true);
  }

  function drawAll() {
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
  }
})();
