// ==========================================
// === GLOBAL STATE & CONFIG
// ==========================================
let currentFilters = {
  location: "",
  gender: "",
  dayOfWeek: [],
  alcohol: [],
  offenseType: [],
  hourFrom: null,
  hourTo: null,
  ageFrom: 0,
  ageTo: 100,
  start: "",
  end: "",
};
let isForecastMode = false;
let selectedLocations = [];
let timeFromPicker = null;
let timeToPicker = null;

// ==========================================
// === CORE UI & GENERAL PAGE FUNCTIONS
// ==========================================
function toggleSidebar() {
  const sidebar = document.querySelector(".sidebar");
  if (sidebar) sidebar.classList.toggle("collapsed");
}
function openLogoutModal(event) {
  event.preventDefault();
  document.getElementById("logoutModal")?.classList.remove("hidden");
}
function closeLogoutModal() {
  document.getElementById("logoutModal")?.classList.add("hidden");
}
function confirmLogout() {
  window.location.href = "/logout";
}

// ==========================================
// === FILTERING LOGIC
// ==========================================
function getFilterState() {
  let genderValue = document.getElementById("genderFilter").value || "";
  if (genderValue.toLowerCase() === "all genders") {
    genderValue = "";
  }
  const locations = Array.from(document.querySelectorAll(".location-pill")).map(
    (pill) => pill.dataset.location
  );
  const timeFromVal = document.getElementById("timeFrom").value;
  const timeToVal = document.getElementById("timeTo").value;
  return {
    location: locations,
    gender: genderValue.toLowerCase(),
    dayOfWeek: getCheckedValues("dowGroup"),
    alcohol: getCheckedValues("alcoholGroup"),
    offenseType: getCheckedValues("offenseGroup"),
    season: getCheckedValues("seasonGroup"),
    hourFrom: timeFromVal ? timeFromVal.split(":")[0] : null,
    hourTo: timeToVal ? timeToVal.split(":")[0] : null,
    ageFrom: +document.getElementById("ageFromBox").value,
    ageTo: +document.getElementById("ageToBox").value,
    start: document.getElementById("monthFrom").value,
    end: document.getElementById("monthTo").value,
  };
}

function getCheckedValues(containerId) {
  return [...document.querySelectorAll(`#${containerId} input:checked`)].map(
    (cb) => cb.value
  );
}

function buildQueryString(filters) {
  const params = new URLSearchParams();
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  if (filters.location?.length)
    params.set("location", filters.location.join(","));
  if (filters.gender) params.set("gender", filters.gender);
  if (filters.dayOfWeek?.length)
    params.set("day_of_week", filters.dayOfWeek.join(","));
  if (filters.alcohol?.length) params.set("alcohol", filters.alcohol.join(","));
  if (filters.offenseType?.length)
    params.set("offense_type", filters.offenseType.join(","));
  if (filters.season?.length) params.set("season", filters.season.join(","));
  if (filters.hourFrom !== null)
    params.set("hour_from", String(filters.hourFrom));
  if (filters.hourTo !== null) params.set("hour_to", String(filters.hourTo));
  if (Number.isFinite(filters.ageFrom))
    params.set("age_from", String(filters.ageFrom));
  if (Number.isFinite(filters.ageTo))
    params.set("age_to", String(filters.ageTo));
  return params.toString();
}

function applyFilters() {
  setTimeout(() => {
    currentFilters = getFilterState();
    const spinner = document.getElementById("forecastSpinner");
    const grid = document.querySelector(".vis-grid");
    if (isForecastMode && spinner && grid) {
      spinner.classList.remove("hidden");
      grid.classList.add("hidden");
    } else if (grid) {
      grid.classList.remove("hidden");
      if (spinner) spinner.classList.add("hidden");
    }
    loadAllVisualizations(currentFilters);
    closeFilterModal();
  }, 0);
}

// --- START OF FIX #1: This entire function is replaced ---
function applyFiltersWithValidation() {
  const ageFrom = +document.getElementById("ageFromBox").value;
  const ageTo = +document.getElementById("ageToBox").value;
  const monthFrom = document.getElementById("monthFrom").value;
  const monthTo = document.getElementById("monthTo").value;

  if (ageFrom > ageTo) {
    return alert("Age 'From' cannot be greater than 'To'.");
  }

  // New validation for the month inputs.
  if (monthFrom && monthTo && monthFrom > monthTo) {
    return alert("The 'From' date cannot be after the 'To' date.");
  }

  // Validation passed, so apply filters. The old hour slider validation is removed.
  applyFilters();
}
// --- END OF FIX #1 ---

async function loadAllVisualizations(filters) {
  const spinner = document.getElementById("forecastSpinner");
  const grid = document.querySelector(".vis-grid");
  try {
    const kpiPromises = [loadKpiCards(filters), loadGenderKpiCards(filters)];
    await Promise.all(kpiPromises);
    const chartPromises = [
      loadOverallTrendChart(filters),
      loadHourlyChart(filters),
      loadDayOfWeekChart(filters),
      loadTopBarangaysChart(filters),
      loadAlcoholByHourChart(filters),
      loadVictimsByAgeChart(filters),
      loadOffenseTypeChart(filters),
      loadSeasonChart(filters),
    ];
    await Promise.all(chartPromises);
  } catch (error) {
    console.error("Error loading visualizations:", error);
  } finally {
    if (spinner) spinner.classList.add("hidden");
    if (grid) grid.classList.remove("hidden");
    setTimeout(() => {
      const allCharts = document.querySelectorAll(".vis-grid .card > div[id]");
      allCharts.forEach((chartEl) => {
        if (chartEl.data) {
          Plotly.Plots.resize(chartEl);
        }
      });
    }, 50);
  }
}

// --- START OF FIX #2: This entire function is replaced ---
function clearFilters() {
  selectedLocations = [];
  document.getElementById("locationFilter").value = "";
  document.getElementById("locationPillsContainer").innerHTML = "";
  document.getElementById("genderFilter").value = "";
  document
    .querySelectorAll(
      "#dowGroup input:checked, #alcoholGroup input:checked, #offenseGroup input:checked, #seasonGroup input:checked"
    )
    .forEach((cb) => (cb.checked = false));

  document.getElementById("monthFrom").value = "";
  document.getElementById("monthTo").value = "";
  if (timeFromPicker) timeFromPicker.clear();
  if (timeToPicker) timeToPicker.clear();

  document.getElementById("ageFromBox").value = 0;
  document.getElementById("ageToBox").value = 100;

  // Correctly reset the age slider's visual state by dispatching events to both thumbs
  const ageFromSlider = document.getElementById("ageFrom");
  const ageToSlider = document.getElementById("ageTo");
  if (ageFromSlider && ageToSlider) {
    ageFromSlider.value = 0;
    ageToSlider.value = 100;
    ageFromSlider.dispatchEvent(new Event("input"));
    ageToSlider.dispatchEvent(new Event("input"));
  }

  applyFilters();
}
// --- END OF FIX #2 ---

function openFilterModal() {
  document.getElementById("filterModal").classList.remove("hidden");
}
function closeFilterModal() {
  document.getElementById("filterModal").classList.add("hidden");
}

function formatFiltersForPDF() {
  const filters = getFilterState();
  const parts = [];
  if (filters.location) parts.push(`Location: ${filters.location}`);
  if (filters.gender) parts.push(`Gender: ${filters.gender}`);
  if (filters.dayOfWeek.length > 0)
    parts.push(`Days: ${filters.dayOfWeek.join(", ")}`);
  if (filters.alcohol.length > 0)
    parts.push(`Alcohol: ${filters.alcohol.join(", ")}`);
  if (filters.offenseType.length > 0)
    parts.push(`Offense Types: ${filters.offenseType.join(", ")}`);
  if (filters.hourFrom !== 0 || filters.hourTo !== 23) {
    parts.push(`Hour: ${filters.hourFrom} to ${filters.hourTo}`);
  }
  if (filters.ageFrom !== 0 || filters.ageTo !== 100) {
    parts.push(`Age: ${filters.ageFrom} to ${filters.ageTo}`);
  }
  if (parts.length === 0) return "None";
  return parts.join("; ");
}

// ==========================================
// === CHART LOADING & RENDERING (REVISED)
// ==========================================

function showNoData(elId, msg) {
  const host = document.getElementById(elId);
  if (!host) return;
  try {
    Plotly.purge(host);
  } catch (e) {}

  let displayMessage = msg || "No data available.";
  if (typeof msg === "string" && msg.includes("NO_TABLE")) {
    displayMessage =
      "No data found to display graphs. Please upload a dataset to begin.";
  }

  host.innerHTML = `
    <div class="no-data-message">
      <svg xmlns="http://www.w3.org/2000/svg" width="60" height="60" fill="#4D8DFF" viewBox="0 0 24 24">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>
      </svg>
      <p>${displayMessage}</p>
    </div>`;
}
function capFirst(s) {
  return s;
}

function formatModelName(modelName) {
  if (!modelName) return "";
  return modelName
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

async function loadOverallTrendChart(filters = currentFilters) {
  const chartId = "overallTimeSeriesChart";
  const chartCard = document.getElementById(chartId)?.parentElement;
  if (!chartCard) return;

  const titleEl = chartCard.querySelector(".card-value");
  document.getElementById(chartId).innerHTML = "";

  try {
    let endpoint = "/api/overall_timeseries";
    const params = new URLSearchParams(buildQueryString(filters));

    if (isForecastMode) {
      endpoint = "/api/forecast/overall_timeseries";
      params.set("model", document.getElementById("forecastModelSelect").value);
      params.set(
        "horizon",
        document.getElementById("forecastHorizonInput").value
      );
    }

    // --- START OF FIX ---
    // Add cache: 'no-cache' to ensure fresh data is always fetched
    const res = await fetch(`${endpoint}?${params.toString()}`, {
      cache: "no-cache",
    });
    // --- END OF FIX ---

    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(errorText || `Request failed with status ${res.status}`);
    }

    const j = await res.json();

    if (!j.success) {
      showNoData(chartId, j.message || "The request was not successful.");
      if (titleEl) titleEl.textContent = "Overall Accident Trend — Error";
      return;
    }

    plotOverallTimeSeries(chartId, j.data, isForecastMode);
  } catch (error) {
    console.error(`Error loading ${chartId}:`, error);
    showNoData(chartId, error.message);
    if (titleEl) titleEl.textContent = "Overall Accident Trend — Error";
  }
}

async function loadHourlyChart(filters = currentFilters) {
  const chartId = "hourlyBar";
  const chartElement = document.getElementById(chartId);
  const titleEl = chartElement?.parentElement.querySelector(".card-value");

  if (titleEl) {
    titleEl.classList.add("clickable-title");
  }

  try {
    let endpoint = "/api/accidents_by_hour";
    const params = new URLSearchParams(buildQueryString(filters));

    if (isForecastMode) {
      endpoint = "/api/forecast/hourly";
      params.set("model", document.getElementById("forecastModelSelect").value);
      params.set(
        "horizon",
        document.getElementById("forecastHorizonInput").value
      );
    }

    const res = await fetch(`${endpoint}?${params.toString()}`, {
      cache: "no-cache",
    });
    const j = await res.json();

    if (!j.success) {
      showNoData(
        chartId,
        j.message || "An error occurred while loading hourly data."
      );
      if (titleEl) titleEl.textContent = "Accidents by Hour — Error";
      return;
    }

    const hasData = isForecastMode
      ? j.data?.labels?.length
      : j.data?.hours?.length;
    if (!hasData) {
      showNoData(chartId, "No data available for the selected filters.");
      return;
    }

    if (isForecastMode) {
      const forecastTitle = `Hourly Forecast (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;

      if (titleEl) {
        titleEl.textContent = forecastTitle;
        titleEl.dataset.chartTitle = forecastTitle;
      }

      renderForecastGroupedBarChart(
        chartId,
        j.data,
        "Hour of Day",
        "Total Accidents"
      );
    } else {
      if (titleEl) {
        const defaultTitle = "Accidents by Hour of Day";
        titleEl.dataset.chartTitle = titleEl.dataset.chartTitle || defaultTitle;
        titleEl.textContent = titleEl.dataset.chartTitle;
      }
      renderHistoricalBarChart(chartId, j.data);
    }
  } catch (e) {
    console.error("Hourly Chart Fetch Error:", e);
    showNoData(
      chartId,
      "A critical error occurred while trying to fetch data."
    );
  }
}

function renderHistoricalBarChart(chartId, data) {
  const { hours, counts } = data;
  const hasData = Array.isArray(counts) && counts.some((v) => v > 0);
  if (!hours?.length || !hasData) {
    showNoData(chartId, "No accidents for selected filters.");
    return;
  }
  const trace = {
    x: hours.map(String),
    y: counts,
    type: "bar",
    text: counts.map(String),
    textposition: "outside",
    marker: { color: "#4D8DFF" },
  };

  const maxValue = Math.max(...counts);
  const yAxisRange = [0, maxValue * 1.15];

  const layout = {
    hovermode: "closest",
    font: { family: "Chillax, sans-serif" },
    margin: { l: 60, r: 10, t: 20, b: 40 },
    xaxis: { title: "Hour of Day (0–23)" },
    yaxis: {
      title: "Count of Accidents",
      range: yAxisRange,
    },
  };

  Plotly.newPlot(chartId, [trace], layout, {
    displayModeBar: false,
    responsive: true,
  });
}

function renderForecastGroupedBarChart(elementId, data, xTitle, yTitle) {
  const { labels, historical, forecast, horizon } = data;

  const traceHist = {
    x: labels,
    y: historical,
    type: "bar",
    name: "Historical",
    marker: { color: "grey" },
  };
  const traceFcst = {
    x: labels,
    y: forecast,
    type: "bar",
    name: "Forecast",
    marker: { color: "#4D8DFF" },
  };

  const layout = {
    hovermode: "closest",
    font: { family: "Chillax, sans-serif" },
    barmode: "group",
    margin: { l: 60, r: 10, t: 40, b: 40 },
    xaxis: { title: xTitle },
    yaxis: { title: yTitle, gridcolor: "rgba(0,0,0,0.1)" },
    legend: {
      orientation: "h",
      x: 0,
      y: 1.15,
      font: {
        weight: "normal",
      },
      hovermode: false,
    },
  };

  Plotly.newPlot(elementId, [traceHist, traceFcst], layout, {
    displayModeBar: false,
    responsive: true,
  });
}

function plotOverallTimeSeries(chartId, data, isForecast) {
  const chartEl = document.getElementById(chartId);
  const titleEl = chartEl?.parentElement.querySelector(".card-value");

  if (!chartEl) return;

  Plotly.purge(chartEl);

  let traces = [];
  let title = "Overall Accident Trend";

  const layout = {
    hovermode: "closest",
    font: { family: "Chillax, sans-serif" },
    margin: { l: 60, r: 20, t: 40, b: 40 },
    xaxis: { title: "Month" },
    yaxis: { title: "Number of Accidents", gridcolor: "rgba(0,0,0,0.1)" },
    legend: {
      orientation: "h",
      x: 0,
      y: 1.15,
      font: { weight: "normal" },
    },
    title: { text: "" },
  };
  const config = { displayModeBar: false, responsive: true };

  if (isForecast) {
    const { historical, forecast, model_used, horizon } = data;
    traces = [
      {
        x: historical.dates,
        y: historical.counts,
        mode: "lines+markers",
        name: "Historical",
        line: { color: "#4D8DFF", width: 3 },
        marker: { size: 6 },
      },
      {
        x: forecast.dates,
        y: forecast.counts,
        mode: "lines+markers",
        name: "Forecast",
        line: { color: "#ff7f0e", dash: "dot", width: 3 },
        marker: { size: 6 },
      },
    ];

    const modelDisplayName = formatModelName(model_used);
    title = `Overall Trend (${modelDisplayName}, ${horizon} mo)`;
    layout.showlegend = true;
  } else {
    const { dates, counts } = data;
    if (!dates || !counts || dates.length === 0) {
      showNoData(chartId, "No data available for the selected trend.");
      if (titleEl) titleEl.textContent = title;
      return;
    }
    traces = [
      {
        x: dates,
        y: counts,
        mode: "lines",
        name: "Accidents",
        line: { color: "#4D8DFF", width: 3 },
      },
    ];
    layout.showlegend = false;
  }

  if (titleEl) {
    titleEl.textContent = title;
    titleEl.dataset.chartTitle = title;
  }

  Plotly.newPlot(chartId, traces, layout, config);
}

async function loadDayOfWeekChart(filters = currentFilters) {
  const chartId = "dayOfWeekCombo";
  const chartElement = document.getElementById(chartId);
  const titleEl = chartElement?.parentElement.querySelector(".card-value");
  if (titleEl) {
    titleEl.classList.add("clickable-title");
    titleEl.dataset.chartTitle = "Accidents and Severity by Day of Week";
    if (!isForecastMode) {
      titleEl.textContent = titleEl.dataset.chartTitle;
    }
  }

  try {
    let endpoint = "/api/accidents_by_day";
    const params = new URLSearchParams(buildQueryString(filters));

    if (isForecastMode) {
      endpoint = "/api/forecast/day_of_week";
      params.set("model", document.getElementById("forecastModelSelect").value);
      params.set(
        "horizon",
        document.getElementById("forecastHorizonInput").value
      );
    }

    const res = await fetch(`${endpoint}?${params.toString()}`, {
      cache: "no-cache",
    });
    const j = await res.json();

    if (!j.success) {
      showNoData(chartId, j.message || "Error loading day of week data.");
      if (titleEl) titleEl.textContent = "Accidents by Day of Week — Error";
      return;
    }

    const hasData = isForecastMode
      ? j.data?.labels?.length
      : j.data?.days?.length && j.data?.counts?.some((c) => c > 0);
    if (!hasData) {
      showNoData(chartId, "No data available for the selected filters.");
      return;
    }

    if (isForecastMode) {
      const forecastTitle = `Severity & Count Forecast (${capFirst(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;
      if (titleEl) {
        titleEl.textContent = forecastTitle;
        titleEl.dataset.chartTitle = forecastTitle;
      }
      const {
        labels,
        historical_counts,
        forecast_counts,
        historical_avg_victims,
        forecast_avg_victims,
      } = j.data;

      const traceHistCount = {
        x: labels,
        y: historical_counts,
        type: "bar",
        name: "Acc (Hist)",
        marker: { color: "grey" },
      };
      const traceFcstCount = {
        x: labels,
        y: forecast_counts,
        type: "bar",
        name: "Acc (Fcst)",
        marker: { color: "#4D8DFF" },
      };
      const traceHistAvg = {
        x: labels,
        y: historical_avg_victims,
        name: "Vic (Hist)",
        type: "scatter",
        mode: "lines+markers",
        yaxis: "y2",
        line: { color: "#ff6700", dash: "dot" },
      };
      const traceFcstAvg = {
        x: labels,
        y: forecast_avg_victims,
        name: "Vic (Fcst)",
        type: "scatter",
        mode: "lines+markers",
        yaxis: "y2",
        line: { color: "#ff6700" },
      };

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" },
        barmode: "group",
        margin: { l: 60, r: 80, t: 40, b: 80 },
        yaxis: {
          title: "Total Accidents",
          gridcolor: "rgba(0,0,0,0.1)",
          automargin: true,
        },

        yaxis2: {
          overlaying: "y",
          side: "right",
          title: "Avg Victims/Accident",
          rangemode: "tozero",
          automargin: true,
        },
        legend: {
          orientation: "h",
          x: 0,
          y: 1.15,
          font: {
            weight: "normal",
          },
          hovermode: false,
        },
      };
      Plotly.newPlot(
        chartId,
        [traceHistCount, traceFcstCount, traceHistAvg, traceFcstAvg],
        layout,
        { displayModeBar: false, responsive: true }
      );
    } else {
      if (titleEl) {
        titleEl.classList.add("clickable-title");
      }
      const { days, counts, avg_victims } = j.data;

      const trace1 = {
        x: days,
        y: counts,
        name: "Accidents",
        type: "bar",
        marker: { color: "#4D8DFF" },
      };
      const trace2 = {
        x: days,
        y: avg_victims,
        name: "Victims",
        type: "scatter",
        mode: "lines+markers",
        yaxis: "y2",
        line: { color: "#ff7f0e" },
      };

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" },
        margin: { l: 60, r: 80, t: 40, b: 80 },
        yaxis: {
          title: "Count of Accidents",
          gridcolor: "rgba(0,0,0,0.1)",
          automargin: true,
        },
        yaxis2: {
          overlaying: "y",

          side: "right",
          title: "Avg Victims/Accident",
          automargin: true,
        },
        legend: {
          orientation: "h",
          x: 0,
          y: 1.15,
          font: {
            weight: "normal",
          },
          hovermode: false,
        },
      };
      Plotly.newPlot(chartId, [trace1, trace2], layout, {
        displayModeBar: false,
        responsive: true,
      });
    }
  } catch (e) {
    console.error("Day of Week Chart Error:", e);
    showNoData(chartId, "A critical error occurred while fetching data.");
  }
}

async function loadTopBarangaysChart(filters = currentFilters) {
  const chartId = "topBarangays";
  const chartElement = document.getElementById(chartId);
  const titleEl = chartElement?.parentElement.querySelector(".card-value");
  if (titleEl) {
    titleEl.classList.add("clickable-title");
    titleEl.dataset.chartTitle = "Top 10 Barangays by Accident Count";
    if (!isForecastMode) {
      titleEl.textContent = titleEl.dataset.chartTitle;
    }
  }

  try {
    let endpoint = "/api/top_barangays";
    const params = new URLSearchParams(buildQueryString(filters));

    if (isForecastMode) {
      endpoint = "/api/forecast/top_barangays";
      params.set("model", document.getElementById("forecastModelSelect").value);
      params.set(
        "horizon",
        document.getElementById("forecastHorizonInput").value
      );
    }

    const res = await fetch(`${endpoint}?${params.toString()}`, {
      cache: "no-cache",
    });
    const j = await res.json();

    if (!j.success) {
      showNoData(chartId, j.message || "Error loading top barangays data.");
      if (titleEl) titleEl.textContent = "Top 10 Barangays — Error";
      return;
    }

    const hasData = isForecastMode
      ? j.data?.labels?.length
      : j.data?.names?.length;
    if (!hasData) {
      showNoData(chartId, "No data available for the selected filters.");
      return;
    }

    if (isForecastMode) {
      const forecastTitle = `Top 10 Barangays Forecast (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;

      if (titleEl) {
        titleEl.textContent = forecastTitle;
        titleEl.dataset.chartTitle = forecastTitle;
      }

      let forecastData = j.data.labels.map((label, index) => ({
        label: label,
        historical: j.data.historical[index],
        forecast: j.data.forecast[index],
      }));

      forecastData.sort((a, b) => a.historical - b.historical);

      const sortedLabels = forecastData.map((d) => d.label);
      const sortedHistorical = forecastData.map((d) => d.historical);
      const sortedForecast = forecastData.map((d) => d.forecast);

      const traceHist = {
        y: sortedLabels,
        x: sortedHistorical,
        type: "bar",
        name: "Historical",
        orientation: "h",
        marker: { color: "grey" },
      };
      const traceFcst = {
        y: sortedLabels,
        x: sortedForecast,
        type: "bar",
        name: "Forecast",
        orientation: "h",
        marker: { color: "#4D8DFF" },
      };

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" },
        barmode: "group",
        margin: { l: 140, r: 40, t: 10, b: 40 },
        yaxis: { title: "" },
        xaxis: { title: "Total Accident Count", gridcolor: "rgba(0,0,0,0.1)" },
        legend: {
          orientation: "h",
          x: 0,
          y: 1.15,
          font: {
            weight: "normal",
          },
          hovermode: false,
        },
      };
      Plotly.newPlot(chartId, [traceHist, traceFcst], layout, {
        displayModeBar: false,
        responsive: true,
      });
    } else {
      if (titleEl) {
        titleEl.classList.add("clickable-title");
      }

      const { names, counts } = j.data;
      const trace = {
        x: counts.slice().reverse(),
        y: names.slice().reverse(),
        type: "bar",
        orientation: "h",
        text: counts.slice().reverse().map(String),
        textposition: "outside",
        marker: { color: "#4D8DFF" },
      };
      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" },
        margin: { l: 140, r: 40, t: 10, b: 40 },
        xaxis: { title: "Count of Accidents", gridcolor: "rgba(0,0,0,0.1)" },
      };
      Plotly.newPlot(chartId, [trace], layout, {
        displayModeBar: false,
        responsive: true,
      });
    }
  } catch (e) {
    console.error("Top Barangays Chart Error:", e);
    showNoData(chartId, "A critical error occurred while fetching data.");
  }
}

async function loadAlcoholByHourChart(filters = currentFilters) {
  const chartId = "alcoholByHour";
  const chartElement = document.getElementById(chartId);
  const titleEl = chartElement?.parentElement.querySelector(".card-value");
  if (titleEl) {
    titleEl.classList.add("clickable-title");
    titleEl.dataset.chartTitle = "Proportion of Alcohol Involvement by Hour";
    if (!isForecastMode) {
      titleEl.textContent = titleEl.dataset.chartTitle;
    }
  }

  try {
    let endpoint = "/api/alcohol_by_hour";
    const params = new URLSearchParams(buildQueryString(filters));

    if (isForecastMode) {
      endpoint = "/api/forecast/alcohol_by_hour";
      params.set("model", document.getElementById("forecastModelSelect").value);
      params.set(
        "horizon",
        document.getElementById("forecastHorizonInput").value
      );
    }

    const res = await fetch(`${endpoint}?${params.toString()}`, {
      cache: "no-cache",
    });
    const j = await res.json();

    if (!j.success) {
      showNoData(
        chartId,
        j.message || "Error loading alcohol involvement data."
      );
      if (titleEl)
        titleEl.textContent = "Proportion of Alcohol Involvement — Error";
      return;
    }

    const hasData = j.data?.hours?.length;
    if (!hasData) {
      showNoData(chartId, "No data available for the selected filters.");
      return;
    }

    if (isForecastMode) {
      const forecastTitle = `Forecasted Alcohol Involvement (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;

      if (titleEl) {
        titleEl.textContent = forecastTitle;
        titleEl.dataset.chartTitle = forecastTitle;
      }

      const { hours, forecast_yes_pct, forecast_no_pct, forecast_unknown_pct } =
        j.data;
      const x = hours.map(String);

      const traceYes = {
        x,
        y: forecast_yes_pct,
        name: "Yes",
        type: "bar",
        marker: { color: "#4D8DFF" },
      };
      const traceNo = {
        x,
        y: forecast_no_pct,
        name: "No",
        type: "bar",
        marker: { color: "#ff6700" },
      };
      const traceUnknown = {
        x,
        y: forecast_unknown_pct,
        name: "Unknown",
        type: "bar",
        marker: { color: "#A9A9A9" },
      };

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" },
        barmode: "stack",
        margin: { l: 60, r: 10, t: 40, b: 40 },
        xaxis: { title: "Hour of Day" },
        yaxis: {
          title: "Percentage (%)",
          ticksuffix: "%",
          gridcolor: "rgba(0,0,0,0.1)",
        },
        legend: {
          orientation: "h",
          x: 0,
          y: 1.15,
          font: {
            weight: "normal",
          },
          hovermode: false,
        },
      };
      Plotly.newPlot(chartId, [traceYes, traceNo, traceUnknown], layout, {
        displayModeBar: false,
        responsive: true,
      });
    } else {
      if (titleEl) {
        titleEl.classList.add("clickable-title");
      }
      const { hours, yes_pct, no_pct, unknown_pct } = j.data;
      const x = hours.map(String);
      const traceYes = {
        x,
        y: yes_pct,
        name: "Yes",
        type: "bar",
        marker: { color: "#4D8DFF" },
      };
      const traceNo = {
        x,
        y: no_pct,
        name: "No",
        type: "bar",
        marker: { color: "#ff6700" },
      };
      const traceUnknown = {
        x,
        y: unknown_pct,
        name: "Unknown",
        type: "bar",
        marker: { color: "#A9A9A9" },
      };
      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" },
        barmode: "stack",
        margin: { l: 60, r: 10, t: 40, b: 40 },
        xaxis: { title: "Hour of Day" },
        yaxis: {
          title: "Percentage (%)",
          ticksuffix: "%",
          gridcolor: "rgba(0,0,0,0.1)",
        },

        legend: {
          orientation: "h",
          x: 0,
          y: 1.15,
          font: {
            weight: "normal",
          },
          hovermode: false,
        },
      };
      Plotly.newPlot(chartId, [traceYes, traceNo, traceUnknown], layout, {
        displayModeBar: false,
        responsive: true,
      });
    }
  } catch (e) {
    console.error("Alcohol By Hour Chart Error:", e);
    showNoData(chartId, "A critical error occurred while fetching data.");
  }
}

async function loadVictimsByAgeChart(filters = currentFilters) {
  const chartId = "victimsByAge";
  const chartElement = document.getElementById(chartId);
  const titleEl = chartElement?.parentElement.querySelector(".card-value");
  if (titleEl) {
    titleEl.classList.add("clickable-title");
    titleEl.dataset.chartTitle = "Total Victims by Age";
    if (!isForecastMode) {
      titleEl.textContent = titleEl.dataset.chartTitle;
    }
  }

  try {
    let endpoint = "/api/victims_by_age";
    const params = new URLSearchParams(buildQueryString(filters));

    if (isForecastMode) {
      endpoint = "/api/forecast/victims_by_age";
      params.set("model", document.getElementById("forecastModelSelect").value);
      params.set(
        "horizon",
        document.getElementById("forecastHorizonInput").value
      );
    }

    const res = await fetch(`${endpoint}?${params.toString()}`, {
      cache: "no-cache",
    });
    const j = await res.json();

    if (!j.success) {
      showNoData(chartId, j.message || "Error loading victims by age data.");
      if (titleEl) titleEl.textContent = "Total Victims by Age — Error";
      return;
    }

    const hasData = j.data?.labels?.length;
    if (!hasData) {
      showNoData(chartId, "No data available for the selected filters.");
      return;
    }

    if (isForecastMode) {
      const forecastTitle = `Victims by Age Forecast (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;

      if (titleEl) {
        titleEl.textContent = forecastTitle;
        titleEl.dataset.chartTitle = forecastTitle;
      }

      renderForecastGroupedBarChart(
        chartId,
        j.data,
        "Age Group",
        "Total Victims"
      );
    } else {
      if (titleEl) {
        titleEl.classList.add("clickable-title");
      }

      const { labels, values } = j.data;
      const trace = {
        x: labels,
        y: values,
        type: "bar",
        text: values.map(String),
        textposition: "outside",
        marker: { color: "#4D8DFF" },
      };

      const maxValue = Math.max(...values);
      const yAxisRange = [0, maxValue * 1.15];

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" },
        margin: { l: 60, r: 10, t: 20, b: 60 },
        xaxis: { title: "Age Group" },
        yaxis: {
          title: "Total Victims",
          gridcolor: "rgba(0,0,0,0.1)",
          range: yAxisRange,
        },
      };

      Plotly.newPlot(chartId, [trace], layout, {
        displayModeBar: false,
        responsive: true,
      });
    }
  } catch (e) {
    console.error("Victims by Age Chart Error:", e);
    showNoData(chartId, "A critical error occurred while fetching data.");
  }
}

async function loadOffenseTypeChart(filters = currentFilters) {
  const chartId = "offenseTypeChart";
  const chartElement = document.getElementById(chartId);
  const titleEl = chartElement?.parentElement.querySelector(".card-value");

  if (titleEl) {
    titleEl.classList.add("clickable-title");
    titleEl.dataset.chartTitle = "Accidents by Offense Type";
    if (!isForecastMode) {
      titleEl.textContent = titleEl.dataset.chartTitle;
    }
  }

  try {
    let endpoint = "/api/offense_types";
    const params = new URLSearchParams(buildQueryString(filters));

    if (isForecastMode) {
      endpoint = "/api/forecast/offense_types";
      params.set("model", document.getElementById("forecastModelSelect").value);
      params.set(
        "horizon",
        document.getElementById("forecastHorizonInput").value
      );
    }

    const res = await fetch(`${endpoint}?${params.toString()}`, {
      cache: "no-cache",
    });
    const j = await res.json();

    if (!j.success) {
      showNoData(chartId, j.message || "Error loading offense type data.");
      if (titleEl) titleEl.textContent = "Accidents by Offense Type — Error";
      return;
    }

    const hasData = j.data?.labels?.length;
    if (!hasData) {
      showNoData(chartId, "No data available for the selected filters.");
      return;
    }

    if (isForecastMode) {
      const forecastTitle = `Offense Type Forecast (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;

      if (titleEl) {
        titleEl.textContent = forecastTitle;
        titleEl.dataset.chartTitle = forecastTitle;
      }

      renderForecastGroupedBarChart(
        chartId,
        j.data,
        "Offense Type",
        "Total Accidents"
      );
    } else {
      if (titleEl) {
        titleEl.classList.add("clickable-title");
      }

      const { labels, values } = j.data;
      const totalAccidents = values.reduce((sum, current) => sum + current, 0);

      const cleanedLabels = labels.map((l) => {
        const cleaned = l.replace(/_/g, " ").replace(" Only", "");
        if (cleaned === "Property and Person") {
          return "Both";
        }
        return cleaned;
      });

      const trace = {
        labels: cleanedLabels,
        values: values,
        type: "pie",
        hole: 0.4,
        textinfo: "percent",
        textposition: "inside",
        hoverinfo: "label+percent+value",
        marker: {
          colors: ["#4D8DFF", "#ff6700", "#FFB200"],
        },
      };

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" },
        showlegend: true,
        legend: {
          orientation: "h",
          y: -0.1,
          yanchor: "top",
          font: {
            weight: "normal",
          },
          hovermode: false,
        },
        margin: { t: 20, b: 50, l: 20, r: 20 },
        annotations: [
          {
            font: { size: 20, family: "Chillax, sans-serif" },
            showarrow: false,
            text: `<b>${totalAccidents.toLocaleString()}</b><br>Total`,
            x: 0.5,
            y: 0.5,
          },
        ],
      };

      Plotly.newPlot(chartId, [trace], layout, {
        displayModeBar: false,
        responsive: true,
      });
    }
  } catch (e) {
    console.error("Offense Type Chart Error:", e);
    showNoData(chartId, "A critical error occurred while fetching data.");
  }
}

async function loadSeasonChart(filters = currentFilters) {
  const chartId = "seasonChart";
  const chartElement = document.getElementById(chartId);
  const titleEl = chartElement?.parentElement.querySelector(".card-value");

  if (titleEl) {
    titleEl.classList.add("clickable-title");
    titleEl.dataset.chartTitle = "Accidents by Season";
  }

  try {
    // --- START OF FIX ---
    // Dynamically choose the endpoint based on the forecast mode toggle
    const endpoint = isForecastMode
      ? "/api/forecast/by_season"
      : "/api/by_season";
    const params = new URLSearchParams(buildQueryString(filters));

    if (isForecastMode) {
      params.set("model", document.getElementById("forecastModelSelect").value);
      params.set(
        "horizon",
        document.getElementById("forecastHorizonInput").value
      );
    }
    // --- END OF FIX ---

    const res = await fetch(`${endpoint}?${params.toString()}`, {
      cache: "no-cache",
    });
    const j = await res.json();

    if (!j.success) {
      showNoData(chartId, j.message || "Error loading seasonal data.");
      if (titleEl) titleEl.textContent = "Accidents by Season — Error";
      return;
    }

    // Check if the response has any data to plot
    const hasData = isForecastMode
      ? j.data?.labels?.length
      : j.data?.values?.some((v) => v > 0);
    if (!hasData) {
      showNoData(chartId, "No data available for seasonal analysis.");
      return;
    }

    if (isForecastMode) {
      // Logic for when Forecast Mode is ON (remains unchanged)
      const forecastTitle = `Seasonal Forecast (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;
      if (titleEl) {
        titleEl.textContent = forecastTitle;
        titleEl.dataset.chartTitle = forecastTitle;
      }
      renderForecastGroupedBarChart(
        chartId,
        j.data, // This data structure includes 'historical' and 'forecast' keys
        "Season",
        "Total Accidents"
      );
    } else {
      // NEW LOGIC: For when Forecast Mode is OFF
      if (titleEl) {
        titleEl.textContent = "Accidents by Season (Historical)";
        titleEl.dataset.chartTitle = "Accidents by Season (Historical)";
      }

      // Use the simple bar chart renderer for the historical data from our new endpoint
      // This data structure now has 'labels' and 'values'
      const trace = {
        x: j.data.labels,
        y: j.data.values, // Use the new 'values' key
        type: "bar",
        text: j.data.values.map(String),
        textposition: "outside",
        marker: { color: "#4D8DFF" },
      };

      const maxValue = Math.max(...j.data.values);
      const yAxisRange = [0, maxValue * 1.15];

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" },
        margin: { l: 60, r: 10, t: 20, b: 40 },
        xaxis: { title: "Season" },
        yaxis: {
          title: "Total Accidents",
          range: yAxisRange,
        },
        showlegend: false,
      };

      Plotly.newPlot(chartId, [trace], layout, {
        displayModeBar: false,
        responsive: true,
      });
    }
  } catch (e) {
    console.error("Season Chart Error:", e);
    showNoData(
      chartId,
      "A critical error occurred while fetching seasonal data."
    );
  }
}

async function loadGenderKpiCards(filters = currentFilters) {
  try {
    const paramsStr = buildQueryString(filters);
    const res = await fetch(`/api/gender_kpis?${paramsStr}`, {
      cache: "no-cache",
    });
    const j = await res.json();

    if (!j.success || !j.data) {
      throw new Error(j.message || "Failed to load gender KPIs");
    }

    const { male_count, female_count, unknown_count } = j.data;
    document.getElementById("kpiMale").textContent = (
      male_count || 0
    ).toLocaleString();
    document.getElementById("kpiFemale").textContent = (
      female_count || 0
    ).toLocaleString();
    document.getElementById("kpiUnknown").textContent = (
      unknown_count || 0
    ).toLocaleString();
  } catch (e) {
    console.error("Gender KPI Error:", e);
    document.getElementById("kpiMale").textContent = "—";
    document.getElementById("kpiFemale").textContent = "—";
    document.getElementById("kpiUnknown").textContent = "—";
  }
}

async function loadKpiCards(filters = currentFilters) {
  const kpiIds = [
    "kpiAccidents",
    "kpiVictims",
    "kpiAvgVictims",
    "kpiAlcoholPct",
  ];
  try {
    const paramsStr = buildQueryString(filters);
    const res = await fetch(`/api/kpis?${paramsStr}`, { cache: "no-cache" });
    const j = await res.json();

    if (!j.success || !j.data) {
      throw new Error(j.message || "Failed to load KPIs");
    }

    const {
      total_accidents,
      total_victims,
      avg_victims_per_accident,
      alcohol_involvement_rate,
      alcohol_cases, // 1. Add the new variable here
    } = j.data;

    document.getElementById("kpiAccidents").textContent =
      total_accidents.toLocaleString();
    document.getElementById("kpiVictims").textContent =
      total_victims.toLocaleString();
    document.getElementById("kpiAvgVictims").textContent = (
      avg_victims_per_accident || 0
    ).toFixed(2);

    // 2. Update the text content to include both the percentage and the raw number
    document.getElementById("kpiAlcoholPct").textContent = `${(
      (alcohol_involvement_rate || 0) * 100
    ).toFixed(1)}% (${(alcohol_cases || 0).toLocaleString()})`;
  } catch (e) {
    console.error("KPI Error:", e);
    kpiIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.textContent = "—";
    });
  }
}

async function downloadDashboardAsPDF() {
  const downloadBtn = document.getElementById("downloadPdfBtn");
  if (!downloadBtn) return;

  const originalBtnText = downloadBtn.textContent;
  downloadBtn.textContent = "Generating PDF...";
  downloadBtn.disabled = true;

  try {
    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF({
      orientation: "p",
      unit: "mm",
      format: "a4",
    });

    const MARGIN = 15;
    const PAGE_WIDTH = pdf.internal.pageSize.getWidth();
    const CONTENT_WIDTH = PAGE_WIDTH - MARGIN * 2;
    let yPos = MARGIN;

    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(20);
    pdf.text("RTAverse Dashboard Report", PAGE_WIDTH / 2, yPos, {
      align: "center",
    });
    yPos += 10;

    pdf.setFont("helvetica", "normal");
    pdf.setFontSize(11);
    const reportDate = `Generated on: ${new Date().toLocaleString()}`;
    pdf.text(reportDate, PAGE_WIDTH / 2, yPos, { align: "center" });
    yPos += 15;

    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(12);
    pdf.text("Active Filters:", MARGIN, yPos);
    yPos += 6;
    pdf.setFont("helvetica", "normal");
    const filterText = formatFiltersForPDF();
    const splitFilters = pdf.splitTextToSize(filterText, CONTENT_WIDTH);
    pdf.text(splitFilters, MARGIN, yPos);
    yPos += splitFilters.length * 5 + 5;

    pdf.line(MARGIN, yPos, PAGE_WIDTH - MARGIN, yPos);
    yPos += 10;
    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(12);
    pdf.text("Key Performance Indicators", MARGIN, yPos);
    yPos += 8;

    pdf.setFont("helvetica", "normal");

    const kpiAccidents = `Total Accidents: ${
      document.getElementById("kpiAccidents").textContent
    }`;
    const kpiVictims = `Total Victims: ${
      document.getElementById("kpiVictims").textContent
    }`;
    const kpiAvgVictims = `Avg Victims/Accident: ${
      document.getElementById("kpiAvgVictims").textContent
    }`;
    const kpiAlcohol = `Alcohol Involvement: ${
      document.getElementById("kpiAlcoholPct").textContent
    }`;
    const kpiMale = `Male: ${document.getElementById("kpiMale").textContent}`;
    const kpiFemale = `Female: ${
      document.getElementById("kpiFemale").textContent
    }`;
    const kpiUnknown = `Unknown Gender: ${
      document.getElementById("kpiUnknown").textContent
    }`;

    pdf.text(kpiAccidents, MARGIN, yPos);
    pdf.text(kpiAvgVictims, MARGIN + CONTENT_WIDTH / 2, yPos);
    yPos += 7;

    pdf.text(kpiVictims, MARGIN, yPos);
    pdf.text(kpiAlcohol, MARGIN + CONTENT_WIDTH / 2, yPos);
    yPos += 7;

    pdf.text(kpiMale, MARGIN, yPos);
    pdf.text(kpiFemale, MARGIN + CONTENT_WIDTH / 2, yPos);
    yPos += 7;

    pdf.text(kpiUnknown, MARGIN, yPos);
    yPos += 10;

    pdf.line(MARGIN, yPos, PAGE_WIDTH - MARGIN, yPos);

    const chartsToInclude = [
      { id: "hourlyBar", title: "Accidents by Hour of Day" },
      { id: "dayOfWeekCombo", title: "Accidents and Severity by Day of Week" },
      { id: "topBarangays", title: "Top 10 Barangays by Accident Count" },
      {
        id: "alcoholByHour",
        title: "Proportion of Alcohol Involvement by Hour",
      },
      { id: "victimsByAge", title: "Total Victims by Age" },
      { id: "offenseTypeChart", title: "Accidents by Offense Type" },
      { id: "seasonChart", title: "Accidents by Season" },
    ];

    pdf.addPage();
    yPos = MARGIN;

    for (const chartInfo of chartsToInclude) {
      const chartEl = document.getElementById(chartInfo.id);
      if (chartEl && chartEl.data) {
        const TITLE_PLUS_SPACING = 10;
        const CHART_SPACING_AFTER = 15;
        const imgHeight = (450 / 800) * CONTENT_WIDTH;
        const totalBlockHeight =
          TITLE_PLUS_SPACING + imgHeight + CHART_SPACING_AFTER;

        if (
          yPos + totalBlockHeight >
          pdf.internal.pageSize.getHeight() - MARGIN
        ) {
          pdf.addPage();
          yPos = MARGIN;
        }

        pdf.setFont("helvetica", "bold");
        pdf.setFontSize(14);
        pdf.text(chartInfo.title, PAGE_WIDTH / 2, yPos, { align: "center" });
        yPos += TITLE_PLUS_SPACING;

        const imgData = await Plotly.toImage(chartEl, {
          format: "png",
          width: 800,
          height: 450,
        });

        pdf.addImage(imgData, "PNG", MARGIN, yPos, CONTENT_WIDTH, imgHeight);
        yPos += imgHeight + CHART_SPACING_AFTER;
      }
    }

    pdf.save("RTAverse_Dashboard_Report.pdf");
  } catch (error) {
    console.error("Failed to generate PDF:", error);
    alert(
      "Sorry, there was an error creating the PDF. Please check the console for details."
    );
  } finally {
    downloadBtn.textContent = originalBtnText;
    downloadBtn.disabled = false;
  }
}
// ==========================================
// === ZOOM MODAL FUNCTIONALITY ===
// ==========================================

function zoomChart(chartId, chartTitle) {
  const modal = document.getElementById("zoomModal");
  const modalTitle = document.getElementById("zoomModalTitle");
  const zoomDisplay = document.getElementById("zoomChartDisplay");

  modalTitle.textContent = chartTitle;
  modal.classList.add("active");

  const originalChart = document.getElementById(chartId);

  if (!originalChart || !originalChart.data || !originalChart.layout) {
    zoomDisplay.innerHTML =
      '<p style="text-align: center; padding: 50px; color: #999;">No chart data available to zoom.</p>';
    return;
  }

  const data = originalChart.data;
  const layout = { ...originalChart.layout };

  layout.height = null;
  layout.width = null;
  layout.autosize = true;
  layout.margin = { l: 80, r: 80, t: 40, b: 80 };
  layout.font = { family: "Chillax, sans-serif", size: 14 };

  Plotly.newPlot(zoomDisplay, data, layout, {
    displayModeBar: true,
    responsive: true,
    modeBarButtonsToRemove: ["pan2d", "lasso2d", "select2d"],
    displaylogo: false,
  });
}

function closeZoomModal() {
  const modal = document.getElementById("zoomModal");
  modal.classList.remove("active");

  const zoomDisplay = document.getElementById("zoomChartDisplay");
  try {
    Plotly.purge(zoomDisplay);
  } catch (e) {}
}

document.addEventListener("click", (e) => {
  const modal = document.getElementById("zoomModal");
  if (e.target === modal) {
    closeZoomModal();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const modal = document.getElementById("zoomModal");
    if (modal && modal.classList.contains("active")) {
      closeZoomModal();
    }
  }
});

// ==========================================
// === INITIALIZATION
// ==========================================
function initializeLocationFilter() {
  const container = document.getElementById("multiSelectContainer");
  const pillsContainer = document.getElementById("locationPillsContainer");
  const locationInput = document.getElementById("locationFilter");
  const dropdownList = document.getElementById("locationDropdownList");

  let allLocations = [];

  function renderPills() {
    pillsContainer.innerHTML = selectedLocations
      .map(
        (loc) => `
      <div class="location-pill" data-location="${loc}">
        ${loc}
        <span class="pill-remove" data-location="${loc}">×</span>
      </div>
    `
      )
      .join("");
  }

  function showLocationDropdown(list) {
    const availableLocations = list.filter(
      (loc) => !selectedLocations.includes(loc)
    );
    dropdownList.innerHTML = availableLocations.length
      ? availableLocations
          .map((loc) => `<div class="dropdown-item">${loc}</div>`)
          .join("")
      : `<div class="dropdown-item no-results">No locations found</div>`;
    dropdownList.style.display = "block";
  }

  async function fetchLocations() {
    try {
      const res = await fetch("/api/barangays", { cache: "no-cache" });
      const { success, barangays } = await res.json();
      if (success) allLocations = barangays;
    } catch (e) {
      console.error("Failed to fetch locations:", e);
    }
  }

  locationInput.addEventListener("focus", () =>
    showLocationDropdown(allLocations)
  );

  locationInput.addEventListener("input", function () {
    const searchTerm = this.value.toLowerCase();
    const filtered = allLocations.filter((loc) =>
      loc.toLowerCase().includes(searchTerm)
    );
    showLocationDropdown(filtered);
  });

  dropdownList.addEventListener("click", function (e) {
    if (
      e.target.classList.contains("dropdown-item") &&
      !e.target.classList.contains("no-results")
    ) {
      const location = e.target.textContent;
      if (!selectedLocations.includes(location)) {
        selectedLocations.push(location);
        renderPills();
      }
      locationInput.value = "";
      showLocationDropdown(allLocations);
      locationInput.focus();
    }
  });

  pillsContainer.addEventListener("click", function (e) {
    if (e.target.classList.contains("pill-remove")) {
      const locationToRemove = e.target.dataset.location;
      selectedLocations = selectedLocations.filter(
        (loc) => loc !== locationToRemove
      );
      renderPills();
    }
  });

  document.addEventListener("click", (e) => {
    if (!container.contains(e.target) && !dropdownList.contains(e.target)) {
      dropdownList.style.display = "none";
    }
  });

  container.addEventListener("click", () => locationInput.focus());

  fetchLocations();
}

function initializeMonthRange() {
  const from = document.getElementById("monthFrom");
  const to = document.getElementById("monthTo");

  function enforceMinMax(el) {
    if (!el.value) return;
    const min = el.getAttribute("min");
    if (min && el.value < min) el.value = min;
  }
  [from, to].forEach((el) =>
    el?.addEventListener("change", () => enforceMinMax(el))
  );
}

function initializeTimePickers() {
  const config = {
    enableTime: true,
    noCalendar: true,
    minuteIncrement: 60,
    altInput: true,
    altFormat: "h:i K",
    time_24hr: false,
    dateFormat: "H:i",
  };
  timeFromPicker = flatpickr("#timeFrom", config);
  timeToPicker = flatpickr("#timeTo", config);
}

function initializeFilterUI() {
  function initDualRange(min, max, fromId, toId, fillId, boxFromId, boxToId) {
    const fromSlider = document.getElementById(fromId),
      toSlider = document.getElementById(toId);
    const fill = document.getElementById(fillId),
      fromBox = document.getElementById(boxFromId),
      toBox = document.getElementById(boxToId);
    function redraw() {
      const lo = Math.min(+fromSlider.value, +toSlider.value),
        hi = Math.max(+fromSlider.value, +toSlider.value);
      const pctLo = ((lo - min) / (max - min)) * 100,
        pctHi = ((hi - min) / (max - min)) * 100;
      fill.style.left = pctLo + "%";
      fill.style.width = pctHi - pctLo + "%";
      fromBox.value = lo;
      toBox.value = hi;
    }
    fromSlider.addEventListener("input", redraw);
    toSlider.addEventListener("input", redraw);
    fromBox.addEventListener("input", () => {
      fromSlider.value = Math.min(
        Math.max(+fromBox.value, min),
        +toSlider.value
      );
      redraw();
    });
    toBox.addEventListener("input", () => {
      toSlider.value = Math.max(Math.min(+toBox.value, max), +fromSlider.value);
      redraw();
    });
    redraw();
  }

  // REMOVED: initDualRange for hours is no longer needed

  initDualRange(
    0,
    100,
    "ageFrom",
    "ageTo",
    "ageFill",
    "ageFromBox",
    "ageToBox"
  );

  initializeLocationFilter();
  initializeGenderFilter();
  // --- START: ADD CALLS TO NEW INITIALIZERS ---
  initializeMonthRange();
  initializeTimePickers();
  // --- END: ADD CALLS TO NEW INITIALIZERS ---
}

function initializeGenderFilter() {
  const genderInput = document.getElementById("genderFilter");
  const dropdownList = document.getElementById("genderDropdownList");
  const allGenders = ["All Genders", "Male", "Female", "Unknown"];

  function showGenderDropdown(list) {
    dropdownList.innerHTML = list.length
      ? list.map((opt) => `<div class="dropdown-item">${opt}</div>`).join("")
      : `<div class="dropdown-item no-results">No options found</div>`;
    dropdownList.style.display = "block";

    dropdownList
      .querySelectorAll(".dropdown-item:not(.no-results)")
      .forEach((item) => {
        item.addEventListener("click", () => {
          genderInput.value = item.textContent;
          dropdownList.style.display = "none";
        });
      });
  }

  genderInput.addEventListener("focus", () => showGenderDropdown(allGenders));

  genderInput.addEventListener("input", function () {
    const searchTerm = this.value.toLowerCase();
    const filteredGenders = allGenders.filter((gender) =>
      gender.toLowerCase().includes(searchTerm)
    );
    showGenderDropdown(filteredGenders);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initializeFilterUI();

  const visGrid = document.querySelector(".vis-grid");
  if (visGrid) {
    visGrid.addEventListener("click", function (event) {
      const titleElement = event.target.closest(".card-value");
      if (titleElement) {
        if (titleElement.dataset.chartId && titleElement.dataset.chartTitle) {
          zoomChart(
            titleElement.dataset.chartId,
            titleElement.dataset.chartTitle
          );
        }
      }
    });
  }

  const forecastToggle = document.getElementById("forecastModeToggle");
  const forecastOptions = document.getElementById("forecastOptions");
  if (forecastToggle && forecastOptions) {
    forecastToggle.addEventListener("change", function () {
      isForecastMode = this.checked;
      forecastOptions.classList.toggle("hidden", !isForecastMode);
      applyFilters();
    });
  }
  document
    .getElementById("forecastModelSelect")
    ?.addEventListener("change", applyFilters);
  document
    .getElementById("forecastHorizonInput")
    ?.addEventListener("change", applyFilters);
  document
    .querySelector("#filterModal .filter-apply-btn")
    ?.addEventListener("click", applyFiltersWithValidation);
  document
    .querySelector(".filter-clear-btn")
    ?.addEventListener("click", clearFilters);
  document
    .getElementById("downloadPdfBtn")
    ?.addEventListener("click", downloadDashboardAsPDF);

  applyFilters();
});
