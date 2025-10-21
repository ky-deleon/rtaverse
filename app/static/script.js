// Search box
function toggleSearchIcon(input) {
  const box = input.parentElement;
  const icon = box.querySelector(".search-icon");

  if (input.value.length > 0) {
    icon.style.opacity = "0";
    box.classList.add("input-active");
  } else {
    icon.style.opacity = "1";
    box.classList.remove("input-active");
  }
}

// Sidebar toggle
function toggleSidebar() {
  const sidebar = document.querySelector(".sidebar");
  const icon = document.getElementById("toggle-icon");
  sidebar.classList.toggle("collapsed");

  if (sidebar.classList.contains("collapsed")) {
    icon.innerHTML =
      '<path d="M497-595v230q0 21 19.5 29.5T551-342l93-93q19-19 19-45t-19-45l-93-93q-15-15-34.5-6.5T497-595ZM212-86q-53 0-89.5-36.5T86-212v-536q0-53 36.5-89.5T212-874h536q53 0 89.5 36.5T874-748v536q0 53-36.5 89.5T748-86H212Zm226-126h310v-536H438v536Z"/>';
  } else {
    icon.innerHTML =
      '<path d="M689-365v-230q0-21-19.5-29.5T635-618l-93 93q-19 19-19 45t19 45l93 93q15 15 34.5 6.5T689-365ZM212-86q-53 0-89.5-36.5T86-212v-536q0-53 36.5-89.5T212-874h536q53 0 89.5 36.5T874-748v536q0 53-36.5 89.5T748-86H212Zm226-126h310v-536H438v536Z"/>';
  }
}

// Log Out Modal
function openLogoutModal(event) {
  event.preventDefault();
  document.getElementById("logoutModal").classList.remove("hidden");
}

function closeLogoutModal() {
  document.getElementById("logoutModal").classList.add("hidden");
}

function confirmLogout() {
  window.location.href = "/logout"; // Adjust your logout route
}

// ===== Live clock for Date/Time cards (Asia/Manila) =====
function startLiveClock() {
  const dateEl = document.getElementById("cardDate");
  const timeEl = document.getElementById("cardTime");
  if (!dateEl && !timeEl) return;

  function update() {
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

    if (dateEl && dateEl.dataset.live === "true") {
      dateEl.textContent = dateFmt.format(now);
    }
    if (timeEl && timeEl.dataset.live === "true") {
      timeEl.textContent = timeFmt.format(now).toLowerCase(); // "pm" not "PM"
    }
  }

  // First paint, then align to next minute boundary
  update();
  const msToNextMinute = 60000 - (Date.now() % 60000);
  setTimeout(() => {
    update();
    setInterval(update, 60000);
  }, msToNextMinute);
}

document.addEventListener("DOMContentLoaded", startLiveClock);
