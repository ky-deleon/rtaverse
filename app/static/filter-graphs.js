// ==========================================
// === GLOBAL STATE & CONFIG
// ==========================================
let currentFilters = {
  location: "",
  gender: "",
  dayOfWeek: [],
  alcohol: [],
  offenseType: [],
  hourFrom: 0,
  hourTo: 23,
  ageFrom: 0,
  ageTo: 100,
};
let isForecastMode = false;

let selectedLocations = [];

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

  // Read selected locations from the data attributes of the pills
  const locations = Array.from(document.querySelectorAll(".location-pill")).map(
    (pill) => pill.dataset.location
  );

  return {
    location: locations, // This is now an array
    gender: genderValue.toLowerCase(),
    dayOfWeek: getCheckedValues("dowGroup"),
    alcohol: getCheckedValues("alcoholGroup"),
    offenseType: getCheckedValues("offenseGroup"),
    hourFrom: +document.getElementById("hourFromBox").value,
    hourTo: +document.getElementById("hourToBox").value,
    ageFrom: +document.getElementById("ageFromBox").value,
    ageTo: +document.getElementById("ageToBox").value,
  };
}

function getCheckedValues(containerId) {
  return [...document.querySelectorAll(`#${containerId} input:checked`)].map(
    (cb) => cb.value
  );
}
function buildQueryString(filters) {
  const params = new URLSearchParams();
  if (filters.location?.length)
    params.set("location", filters.location.join(",")); // Join array with commas
  if (filters.gender) params.set("gender", filters.gender);
  if (filters.dayOfWeek?.length)
    params.set("day_of_week", filters.dayOfWeek.join(","));
  if (filters.alcohol?.length) params.set("alcohol", filters.alcohol.join(","));
  if (filters.offenseType?.length)
    params.set("offense_type", filters.offenseType.join(","));
  if (Number.isFinite(filters.hourFrom))
    params.set("hour_from", String(filters.hourFrom));
  if (Number.isFinite(filters.hourTo))
    params.set("hour_to", String(filters.hourTo));
  if (Number.isFinite(filters.ageFrom))
    params.set("age_from", String(filters.ageFrom));
  if (Number.isFinite(filters.ageTo))
    params.set("age_to", String(filters.ageTo));
  return params.toString();
}
// REPLACE your old applyFilters function with this
function applyFilters() {
  setTimeout(() => {
    currentFilters = getFilterState();

    // --- NEW SPINNER LOGIC START ---
    const spinner = document.getElementById("forecastSpinner");
    const grid = document.querySelector(".vis-grid");

    if (isForecastMode && spinner && grid) {
      // If forecast mode is on, show spinner and hide charts
      spinner.classList.remove("hidden");
      grid.classList.add("hidden");
    } else if (grid) {
      // If not in forecast mode, hide spinner and show charts
      grid.classList.remove("hidden");
      if (spinner) spinner.classList.add("hidden");
    }
    // --- NEW SPINNER LOGIC END ---

    // Call the new async loader function to load all data
    loadAllVisualizations(currentFilters);

    closeFilterModal();
  }, 0);
}
function applyFiltersWithValidation() {
  const ageFrom = +document.getElementById("ageFromBox").value;
  const ageTo = +document.getElementById("ageToBox").value;
  const hourFrom = +document.getElementById("hourFromBox").value;
  const hourTo = +document.getElementById("hourToBox").value;
  if (ageFrom > ageTo) return alert("Age 'From' cannot be greater than 'To'.");
  if (hourFrom > hourTo)
    return alert("Hour 'From' cannot be greater than 'To'.");
  applyFilters();
}
// ADD THIS NEW FUNCTION right after applyFilters
async function loadAllVisualizations(filters) {
  const spinner = document.getElementById("forecastSpinner");
  const grid = document.querySelector(".vis-grid");

  try {
    // Load KPIs first
    const kpiPromises = [loadKpiCards(filters), loadGenderKpiCards(filters)];
    await Promise.all(kpiPromises);

    // Load all charts in parallel
    const chartPromises = [
      loadHourlyChart(filters),
      loadDayOfWeekChart(filters),
      loadTopBarangaysChart(filters),
      loadAlcoholByHourChart(filters),
      loadVictimsByAgeChart(filters),
      loadOffenseTypeChart(filters),
    ];
    // Wait for all charts to finish loading
    await Promise.all(chartPromises);
  } catch (error) {
    console.error("Error loading visualizations:", error);
  } finally {
    // ALWAYS hide spinner and show the grid when done
    if (spinner) spinner.classList.add("hidden");
    if (grid) grid.classList.remove("hidden");
  }
}
function clearFilters() {
  // --- START FIX ---
  // 1. Reset the underlying state for the location filter
  selectedLocations = [];
  // --- END FIX ---

  document.getElementById("locationFilter").value = "";
  document.getElementById("locationPillsContainer").innerHTML = ""; // Clear pills
  document.getElementById("genderFilter").value = "";
  document
    .querySelectorAll(
      "#dowGroup input:checked, #alcoholGroup input:checked, #offenseGroup input:checked"
    )
    .forEach((cb) => (cb.checked = false));
  document.getElementById("hourFromBox").value = 0;
  document.getElementById("hourToBox").value = 23;
  document.getElementById("ageFromBox").value = 0;
  document.getElementById("ageToBox").value = 100;
  document.getElementById("hourFrom").value = 0;
  document.getElementById("hourTo").value = 23;
  document.getElementById("ageFrom").value = 0;
  document.getElementById("ageTo").value = 100;
  document.getElementById("hourFrom").dispatchEvent(new Event("input"));
  document.getElementById("ageFrom").dispatchEvent(new Event("input"));
  applyFilters();
}

function openFilterModal() {
  document.getElementById("filterModal").classList.remove("hidden");
}
function closeFilterModal() {
  document.getElementById("filterModal").classList.add("hidden");
}

// In filter-graphs.js, add this new helper function.

function formatFiltersForPDF() {
  const filters = getFilterState(); // Use existing function to get current filters
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

// Find this function (around line 348)
function showNoData(elId, msg) {
  const host = document.getElementById(elId);
  if (!host) return;
  // Clear any existing Plotly charts to prevent conflicts
  try {
    Plotly.purge(host);
  } catch (e) {
    // Ignore if no chart exists
  }

  // --- START OF CHANGES ---

  let displayMessage = msg || "No data available.";
  if (typeof msg === "string" && msg.includes("NO_TABLE")) {
    // 1. This text is now updated
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

  // --- END OF CHANGES ---
}
function capFirst(s) {
  return s;
}

function formatModelName(modelName) {
  if (!modelName) return "";
  // 1. Replace underscores with spaces
  // 2. Split into words
  // 3. Capitalize the first letter of each word
  // 4. Join them back together
  return modelName
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

async function loadHourlyChart(filters = currentFilters) {
  const chartId = "hourlyBar";
  const chartElement = document.getElementById(chartId);
  const titleEl = chartElement?.parentElement.querySelector(".card-value");

  if (titleEl) {
    titleEl.classList.add("clickable-title");
    // We will set the title *after* the data fetch,
    // so we can clear the old one or show a default.
    // This logic is moved down.
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

    const res = await fetch(`${endpoint}?${params.toString()}`);
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
      // --- START OF CHANGE ---
      const forecastTitle = `Hourly Forecast (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;
      // --- END OF CHANGE ---

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
      // --- RECOMMENDED FIX FOR HISTORICAL ---
      if (titleEl) {
        // 1. Define the default title
        const defaultTitle = "Accidents by Hour of Day";

        // 2. Set the data attribute (if it's missing, use the default)
        titleEl.dataset.chartTitle = titleEl.dataset.chartTitle || defaultTitle;

        // 3. Set the visible text *from* the data attribute
        titleEl.textContent = titleEl.dataset.chartTitle;
      }
      // --- END RECOMMENDATION ---

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
    font: { family: "Chillax, sans-serif" }, // <-- Add this line
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

  // --- START OF FINAL FIX ---
  // Use shorter, cleaner names for the legend.
  const traceHist = {
    x: labels,
    y: historical,
    type: "bar",
    name: "Historical", // CHANGED from "Historical Total"
    marker: { color: "grey" },
  };
  const traceFcst = {
    x: labels,
    y: forecast,
    type: "bar",
    name: "Forecast", // CHANGED from `Forecast (${horizon} mo)`
    marker: { color: "#4D8DFF" },
  };

  // Revert to the original, simpler layout.
  const layout = {
    hovermode: "closest",
    font: { family: "Chillax, sans-serif" }, // <-- Add this line
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
  // --- END OF FINAL FIX ---

  Plotly.newPlot(elementId, [traceHist, traceFcst], layout, {
    displayModeBar: false,
    responsive: true,
  });
}

async function loadDayOfWeekChart(filters = currentFilters) {
  const chartId = "dayOfWeekCombo";
  const chartElement = document.getElementById(chartId);
  const titleEl = chartElement?.parentElement.querySelector(".card-value");
  if (titleEl) {
    titleEl.classList.add("clickable-title");
    // Reset to default title, will be updated based on mode
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

    const res = await fetch(`${endpoint}?${params.toString()}`);
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
        // --- START OF CHANGE ---
        // Also update the dataset property for the enlarged view
        titleEl.dataset.chartTitle = forecastTitle;
        // --- END OF CHANGE ---
      }
      const {
        labels,
        historical_counts,
        forecast_counts,
        historical_avg_victims,
        forecast_avg_victims,
      } = j.data;

      // --- START OF LEGEND TEXT FIX ---
      const traceHistCount = {
        x: labels,
        y: historical_counts,
        type: "bar",
        name: "Acc (Hist)", // Shortened Label
        marker: { color: "grey" },
      };
      const traceFcstCount = {
        x: labels,
        y: forecast_counts,
        type: "bar",
        name: "Acc (Fcst)", // Shortened Label
        marker: { color: "#4D8DFF" },
      };
      const traceHistAvg = {
        x: labels,
        y: historical_avg_victims,
        name: "Vic (Hist)", // Shortened Label
        type: "scatter",
        mode: "lines+markers",
        yaxis: "y2",
        line: { color: "#ff6700", dash: "dot" },
      };
      const traceFcstAvg = {
        x: labels,
        y: forecast_avg_victims,
        name: "Vic (Fcst)", // Shortened Label
        type: "scatter",
        mode: "lines+markers",
        yaxis: "y2",
        line: { color: "#ff6700" },
      };
      // --- END OF LEGEND TEXT FIX ---

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" }, // <-- Add this line
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
        font: { family: "Chillax, sans-serif" }, // <-- Add this line
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
    // Set a default title, which will be updated based on the mode
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

    const res = await fetch(`${endpoint}?${params.toString()}`);
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
      // --- START OF CHANGE ---
      const forecastTitle = `Top 10 Barangays Forecast (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;
      // --- END OF CHANGE ---

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

      // --- START OF LEGEND TEXT FIX ---
      const traceHist = {
        y: sortedLabels,
        x: sortedHistorical,
        type: "bar",
        name: "Historical", // Shortened Label
        orientation: "h",
        marker: { color: "grey" },
      };
      const traceFcst = {
        y: sortedLabels,
        x: sortedForecast,
        type: "bar",
        name: "Forecast", // Shortened Label
        orientation: "h",
        marker: { color: "#4D8DFF" },
      };
      // --- END OF LEGEND TEXT FIX ---

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" }, // <-- Add this line
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
        font: { family: "Chillax, sans-serif" }, // <-- Add this line
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
    // Set the default title for non-forecast mode
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

    const res = await fetch(`${endpoint}?${params.toString()}`);
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
      // --- START OF CHANGE ---
      const forecastTitle = `Forecasted Alcohol Involvement (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;
      // --- END OF CHANGE ---

      if (titleEl) {
        titleEl.textContent = forecastTitle;
        titleEl.dataset.chartTitle = forecastTitle;
      }

      const { hours, forecast_yes_pct, forecast_no_pct, forecast_unknown_pct } =
        j.data;
      const x = hours.map(String);

      // --- START OF LEGEND TEXT FIX ---
      const traceYes = {
        x,
        y: forecast_yes_pct,
        name: "Yes", // Removed "(Forecast)"
        type: "bar",
        marker: { color: "#4D8DFF" },
      };
      const traceNo = {
        x,
        y: forecast_no_pct,
        name: "No", // Removed "(Forecast)"
        type: "bar",
        marker: { color: "#ff6700" },
      };
      const traceUnknown = {
        x,
        y: forecast_unknown_pct,
        name: "Unknown", // Removed "(Forecast)"
        type: "bar",
        marker: { color: "#A9A9A9" },
      };
      // --- END OF LEGEND TEXT FIX ---

      const layout = {
        hovermode: "closest",
        font: { family: "Chillax, sans-serif" }, // <-- Add this line
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
        font: { family: "Chillax, sans-serif" }, // <-- Add this line
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
    // Set the default title for both the card and the enlarged view
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

    const res = await fetch(`${endpoint}?${params.toString()}`);
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
      // --- START OF CHANGES ---

      // 1. Create a formatted title using the helper function.
      const forecastTitle = `Victims by Age Forecast (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;

      if (titleEl) {
        // 2. Update the visible title on the card.
        titleEl.textContent = forecastTitle;
        // 3. Update the dataset title for the enlarged view to ensure consistency.
        titleEl.dataset.chartTitle = forecastTitle;
      }

      // --- END OF CHANGES ---

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
    // Set the default title for both the card and the enlarged view
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

    const res = await fetch(`${endpoint}?${params.toString()}`);
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
      // --- START OF CHANGES ---

      // 1. Define the specific forecast title as requested: "Offense Type Forecast".
      //    Use the formatModelName helper for a clean model display (e.g., "Random Forest").
      const forecastTitle = `Offense Type Forecast (${formatModelName(
        j.data.model_used
      )}, ${j.data.horizon} mo)`;

      if (titleEl) {
        // 2. Update the visible title on the dashboard card.
        titleEl.textContent = forecastTitle;

        // 3. Update the dataset attribute to ensure the enlarged view has the same, correct title.
        titleEl.dataset.chartTitle = forecastTitle;
      }

      // --- END OF CHANGES ---

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

async function loadGenderKpiCards(filters = currentFilters) {
  try {
    const paramsStr = buildQueryString(filters);
    const res = await fetch(`/api/gender_kpis?${paramsStr}`);
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
    const res = await fetch(`/api/kpis?${paramsStr}`);
    const j = await res.json();

    if (!j.success || !j.data) {
      throw new Error(j.message || "Failed to load KPIs");
    }

    const {
      total_accidents,
      total_victims,
      avg_victims_per_accident,
      alcohol_involvement_rate,
    } = j.data;
    document.getElementById("kpiAccidents").textContent =
      total_accidents.toLocaleString();
    document.getElementById("kpiVictims").textContent =
      total_victims.toLocaleString();
    document.getElementById("kpiAvgVictims").textContent = (
      avg_victims_per_accident || 0
    ).toFixed(2);
    document.getElementById("kpiAlcoholPct").textContent = `${(
      (alcohol_involvement_rate || 0) * 100
    ).toFixed(1)}%`;
  } catch (e) {
    console.error("KPI Error:", e);
    kpiIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.textContent = "—";
    });
  }
}

// In filter-graphs.js, replace the entire old function with this new one.

async function downloadDashboardAsPDF() {
  const downloadBtn = document.getElementById("downloadPdfBtn");
  if (!downloadBtn) return;

  const originalBtnText = downloadBtn.textContent;
  downloadBtn.textContent = "Generating PDF...";
  downloadBtn.disabled = true;

  try {
    // 1. Initialize jsPDF for a portrait A4 document
    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF({
      orientation: "p", // portrait
      unit: "mm", // millimeters
      format: "a4",
    });

    const MARGIN = 15;
    const PAGE_WIDTH = pdf.internal.pageSize.getWidth();
    const CONTENT_WIDTH = PAGE_WIDTH - MARGIN * 2;
    let yPos = MARGIN;

    // --- SECTION 1: REPORT HEADER ---
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

    // --- SECTION 2: ACTIVE FILTERS ---
    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(12);
    pdf.text("Active Filters:", MARGIN, yPos);
    yPos += 6;
    pdf.setFont("helvetica", "normal");
    const filterText = formatFiltersForPDF();
    // Use splitTextToSize to handle wrapping long filter lists
    const splitFilters = pdf.splitTextToSize(filterText, CONTENT_WIDTH);
    pdf.text(splitFilters, MARGIN, yPos);
    yPos += splitFilters.length * 5 + 5; // Adjust spacing based on lines

    // --- SECTION 3: KPI CARDS (UPDATED) ---
    pdf.line(MARGIN, yPos, PAGE_WIDTH - MARGIN, yPos); // Separator line
    yPos += 10;
    pdf.setFont("helvetica", "bold");
    pdf.setFontSize(12);
    pdf.text("Key Performance Indicators", MARGIN, yPos);
    yPos += 8;

    pdf.setFont("helvetica", "normal");

    // --- START OF UPDATE ---
    // Read all seven KPI values from the DOM
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

    // Arrange all KPIs in a clean, multi-row layout
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
    yPos += 10; // Add final spacing before the separator line
    // --- END OF UPDATE ---

    pdf.line(MARGIN, yPos, PAGE_WIDTH - MARGIN, yPos); // Separator line

    // --- SECTION 4: CHARTS ---
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
    ];

    pdf.addPage();
    yPos = MARGIN;

    // Use a for...of loop to handle async/await correctly
    for (const chartInfo of chartsToInclude) {
      const chartEl = document.getElementById(chartInfo.id);
      // Check if chart has been rendered and has data
      if (chartEl && chartEl.data) {
        // --- START OF PDF PAGE BREAK FIX ---

        // 1. Define heights for the title and image
        const TITLE_PLUS_SPACING = 10; // Space for the title text
        const CHART_SPACING_AFTER = 15; // Space after the chart
        const imgHeight = (450 / 800) * CONTENT_WIDTH; //
        const totalBlockHeight =
          TITLE_PLUS_SPACING + imgHeight + CHART_SPACING_AFTER;

        // 2. Check if the ENTIRE block (title + chart) fits on the current page
        if (
          yPos + totalBlockHeight >
          pdf.internal.pageSize.getHeight() - MARGIN
        ) {
          pdf.addPage(); //
          yPos = MARGIN; //
        }

        // 3. Now that we know there's space, add the title
        pdf.setFont("helvetica", "bold");
        pdf.setFontSize(14); //
        pdf.text(chartInfo.title, PAGE_WIDTH / 2, yPos, { align: "center" });
        yPos += TITLE_PLUS_SPACING; // Move yPos down past the title

        // 4. Convert and add the chart image
        const imgData = await Plotly.toImage(chartEl, {
          //
          format: "png",
          width: 800,
          height: 450,
        });

        pdf.addImage(imgData, "PNG", MARGIN, yPos, CONTENT_WIDTH, imgHeight);
        yPos += imgHeight + CHART_SPACING_AFTER; // Add spacing after the chart

        // --- END OF PDF PAGE BREAK FIX ---
      }
    }

    // --- FINAL: SAVE THE DOCUMENT ---
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
  console.log(
    `%c ZOOM: zoomChart() called for chart ID: ${chartId}`,
    "color: #fff; background-color: #0437f2; padding: 4px; border-radius: 4px;"
  );
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
  } catch (e) {
    // Ignore
  }
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
      const { success, barangays } = await (
        await fetch("/api/barangays")
      ).json();
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
  initDualRange(
    0,
    23,
    "hourFrom",
    "hourTo",
    "hourFill",
    "hourFromBox",
    "hourToBox"
  );
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
}

// In filter-graphs.js, update the initializeGenderFilter function
function initializeGenderFilter() {
  const genderInput = document.getElementById("genderFilter");
  const dropdownList = document.getElementById("genderDropdownList");
  // --- START: ADD "Unknown" TO THE LIST ---
  const allGenders = ["All Genders", "Male", "Female", "Unknown"];
  // --- END: ADD "Unknown" TO THE LIST ---

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
      console.log("PROBE 1: Grid was clicked. Element:", event.target);

      const titleElement = event.target.closest(".card-value");

      if (titleElement) {
        console.log(
          "PROBE 2: Found a title element. Now checking its data attributes..."
        );
        console.log("--> data-chart-id is:", titleElement.dataset.chartId);
        console.log(
          "--> data-chart-title is:",
          titleElement.dataset.chartTitle
        );

        if (titleElement.dataset.chartId && titleElement.dataset.chartTitle) {
          console.log(
            "%c SUCCESS: Attributes found! Calling zoomChart.",
            "color: #00ff00; font-weight: bold;"
          );
          zoomChart(
            titleElement.dataset.chartId,
            titleElement.dataset.chartTitle
          );
        } else {
          console.error(
            "ERROR: The clicked title element is MISSING the required 'data-chart-id' or 'data-chart-title' attributes. This is likely a browser caching issue."
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
