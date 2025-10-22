// ==========================================
// === MODAL & FILTER FUNCTIONS
// ==========================================

let selectedLocations = [];

function openFilterModal() {
  document.getElementById("filterModal").classList.remove("hidden");
}

function closeFilterModal() {
  document.getElementById("filterModal").classList.add("hidden");
}

// REVISED: Multi-select location filter logic
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

  container.addEventListener("click", (e) => {
    // Only focus the input if the click wasn't on a remove button
    if (!e.target.classList.contains("pill-remove")) {
      locationInput.focus();
    }
  });

  fetchLocations();
}

function initializeMonthRange() {
  const from = document.getElementById("monthFrom");
  const to = document.getElementById("monthTo");
  const err = document.getElementById("dateError");

  function enforceMinMax(el) {
    if (!el.value) return;
    const min = el.getAttribute("min");
    const max = el.getAttribute("max");
    if (min && el.value < min) el.value = min;
    if (max && el.value > max) el.value = max;
  }

  [from, to].forEach((el) => {
    el?.addEventListener("change", () => {
      enforceMinMax(el);

      // --- MODIFICATION: Clear all related error states on change ---
      if (err) err.classList.add("hidden");
      from.classList.remove("error");
      to.classList.remove("error");
      // --- END MODIFICATION ---
    });
  });
}

// REVISED: applyFilters to handle multiple locations
// REVISED: applyFilters to handle multiple locations
function applyFilters() {
  // Read selected locations from the data attributes of the pills
  const locations = Array.from(document.querySelectorAll(".location-pill")).map(
    (pill) => pill.dataset.location
  );

  // --- MODIFICATION: Get elements, not just values ---
  const monthFromEl = document.getElementById("monthFrom");
  const monthToEl = document.getElementById("monthTo");
  const dateError = document.getElementById("dateError");
  const timeFrom = document.getElementById("timeFrom").value;
  const timeTo = document.getElementById("timeTo").value;

  const monthFrom = monthFromEl.value;
  const monthTo = monthToEl.value;
  // --- END MODIFICATION ---

  function validBounds(ym) {
    if (!ym) return true;
    const [y, m] = ym.split("-").map(Number);
    return y >= 2015 && y <= 2025 && m >= 1 && m <= 12;
  }

  // --- MODIFICATION: Add error class logic ---
  // Reset error states first
  if (dateError) dateError.classList.add("hidden");
  monthFromEl.classList.remove("error");
  monthToEl.classList.remove("error");

  // ... inside applyFilters ...

  const isInvalidRange = monthFrom && monthTo && monthFrom > monthTo;
  const isInvalidBounds = !validBounds(monthFrom) || !validBounds(monthTo);

  if (isInvalidBounds || isInvalidRange) {
    if (dateError) {
      // --- START: Set specific error message ---
      if (isInvalidRange) {
        // This is the error in your image
        dateError.textContent =
          "The 'From' date cannot be after the 'To' date.";
      } else {
        // This is the other error (e.g., year 2014)
        dateError.textContent =
          "Please choose months between Jan 2015 and Dec 2025.";
      }
      dateError.classList.remove("hidden");
      // --- END: Set specific error message ---
    }

    // Apply error class to inputs
    if (isInvalidRange) {
      // This is the check you asked for
      monthFromEl.classList.add("error");
      monthToEl.classList.add("error");
    } else {
      // This handles the min/max bounds check
      if (!validBounds(monthFrom)) monthFromEl.classList.add("error");
      if (!validBounds(monthTo)) monthToEl.classList.add("error");
    }
    return;
  }
  // --- END MODIFICATION ---

  const dateEl = document.getElementById("cardDate");
  const timeEl = document.getElementById("cardTime");

  function fmtMonth(ym) {
    const d = new Date(ym + "-01T00:00:00");
    return d.toLocaleDateString("en-PH", { month: "short", year: "numeric" });
  }

  if (dateEl) {
    if (monthFrom && monthTo)
      dateEl.textContent = `${fmtMonth(monthFrom)} – ${fmtMonth(monthTo)}`;
    else if (monthFrom) dateEl.textContent = `from ${fmtMonth(monthFrom)}`;
    else if (monthTo) dateEl.textContent = `until ${fmtMonth(monthTo)}`;
    else dateEl.textContent = "—";
    dateEl.removeAttribute("data-live");
  }

  const fmtTime = (t) => {
    if (!t) return "";
    const [h, m] = t.split(":").map(Number);
    const d = new Date();
    d.setHours(h, m, 0, 0);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  if (timeEl) {
    let timeLabel = "—";
    if (timeFrom && timeTo)
      timeLabel = `${fmtTime(timeFrom)} – ${fmtTime(timeTo)}`;
    else if (timeFrom) timeLabel = `from ${fmtTime(timeFrom)}`;
    else if (timeTo) timeLabel = `until ${fmtTime(timeTo)}`;
    timeEl.textContent = timeLabel;
    timeEl.removeAttribute("data-live");
  }

  const params = new URLSearchParams();
  if (monthFrom) params.set("start", monthFrom);
  if (monthTo) params.set("end", monthTo);
  if (timeFrom) params.set("time_from", timeFrom);
  if (timeTo) params.set("time_to", timeTo);
  // Join the array of locations into a comma-separated string for the URL
  if (locations.length > 0) params.set("barangay", locations.join(","));
  const baseUrl = document.getElementById("map-endpoint")?.dataset.url;
  const iframe = document.querySelector(".map-frame");
  if (baseUrl && iframe) {
    iframe.src = `${baseUrl}?${params.toString()}`;
  }

  closeFilterModal();
}

// REVISED: clearFilters to clear the pills
function clearFilters() {
  // --- START FIX ---
  // 1. Reset the underlying state for the location filter
  selectedLocations = [];
  document.getElementById("locationPillsContainer").innerHTML = ""; // Clear visual pills
  // --- END FIX ---

  const locationEl = document.getElementById("locationFilter");
  const monthFromEl = document.getElementById("monthFrom");
  const monthToEl = document.getElementById("monthTo");
  const timeFromEl = document.getElementById("timeFrom");
  const timeToEl = document.getElementById("timeTo");
  const dateError = document.getElementById("dateError");

  if (locationEl) locationEl.value = "";

  // --- MODIFICATION: Clear error class on reset ---
  if (monthFromEl) {
    monthFromEl.value = "";
    monthFromEl.classList.remove("error");
  }
  if (monthToEl) {
    monthToEl.value = "";
    monthToEl.classList.remove("error");
  }
  // --- END MODIFICATION ---

  if (timeFromEl) timeFromEl.value = "";
  if (timeToEl) timeToEl.value = "";
  if (dateError) dateError.classList.add("hidden");

  const dateEl = document.getElementById("cardDate");
  const timeEl = document.getElementById("cardTime");
  if (dateEl && timeEl) {
    dateEl.setAttribute("data-live", "true");
    timeEl.setAttribute("data-live", "true");
    const now = new Date();
    const dateFmt = new Intl.DateTimeFormat("en-PH", {
      month: "long",
      day: "2-digit",
      year: "numeric",
      timeZone: "Asia/Manila",
    });
    const timeFmt = new Intl.DateTimeFormat("en-PH", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
      timeZone: "Asia/Manila",
    });
    dateEl.textContent = dateFmt.format(now);
    timeEl.textContent = timeFmt.format(now).toLowerCase();
  }

  const baseUrl = document.getElementById("map-endpoint")?.dataset?.url;
  const iframe = document.querySelector(".map-frame");
  if (baseUrl && iframe) iframe.src = baseUrl;
}

// ==========================================
// === INITIALIZATION
// ==========================================

document.addEventListener("DOMContentLoaded", function () {
  // Initialize the interactive filter components
  initializeLocationFilter();
  initializeMonthRange();

  // Add listeners to close the modal
  const modal = document.getElementById("filterModal");
  if (modal) {
    document.addEventListener("click", function (event) {
      if (event.target === modal) {
        closeFilterModal();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeFilterModal();
      }
    });
  }
});
