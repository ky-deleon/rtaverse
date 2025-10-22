let dataTable = null;

// Global flag: friendly (true) vs raw (false)
let FRIENDLY_VIEW = true;

let fileToAppend = null;

// Check if table exists and add Actions column if missing
if ($("#uploadedTable").length > 0) {
  let hasActionsHeader =
    $("#uploadedTable thead th").filter(function () {
      return $(this).text().trim().toLowerCase() === "actions";
    }).length > 0;

  if (!hasActionsHeader) {
    // Add Actions header
    $("#uploadedTable thead tr").append("<th>Actions</th>");

    // Add empty Actions cell for each row
    $("#uploadedTable tbody tr").each(function () {
      $(this).append("<td></td>");
    });
  }
}

const DISPLAY_RENDER_MAP = {
  // One-hot → labels
  GENDER_Male: (v) => (v === "1" || v === 1 ? "Male" : ""),
  GENDER_Unknown: (v) => (v === "1" || v === 1 ? "Unknown" : ""),

  ALCOHOL_USED_Yes: (v) => (v === "1" || v === 1 ? "Yes" : ""),
  ALCOHOL_USED_Unknown: (v) => (v === "1" || v === 1 ? "Unknown" : ""),

  TIME_CLUSTER_Morning: (v) => (v === "1" || v === 1 ? "Morning" : ""),
  TIME_CLUSTER_Midday: (v) => (v === "1" || v === 1 ? "Midday" : ""),
  TIME_CLUSTER_Midnight: (v) => (v === "1" || v === 1 ? "Midnight" : ""),
  // If you also have Evening later: "TIME_CLUSTER_Evening": (v)=> v==="1"||v===1? "Evening":"",

  // Hour → “HH:00” (display-only)
  HOUR_COMMITTED: (v) => {
    const n = Number(v);
    if (Number.isFinite(n) && n >= 0 && n <= 23) {
      return String(n).padStart(2, "0") + ":00";
    }
    return v ?? "";
  },

  // ACCIDENT_HOTSPOT (DBSCAN cluster) → readable (just an example)
  // -1 is “noise” in DBSCAN; everything else is a cluster id.
  ACCIDENT_HOTSPOT: (v) => {
    if (v === null || v === undefined || v === "") return "";
    const n = Number(v);
    if (Number.isNaN(n)) return String(v);
    return n === -1 ? "No cluster" : `Hotspot #${n}`;
  },

  // OFFENSE bucketed categories → nicer spacing
  OFFENSE: (v) => {
    if (!v) return "";
    // Map exact strings if needed
    const map = {
      Property_and_Person: "Property + Person",
      Person_Injury_Only: "Person Injury Only",
      Property_Damage_Only: "Property Damage Only",
      Other: "Other",
    };
    return map[v] || v;
  },

  "VEHICLE KIND": (v) =>
    !v || String(v).toLowerCase() === "nan" ? "Unknown" : v,

  // Example: AGE / VICTIM COUNT → show raw (but still allow formatting)
  AGE: (v) => v,
  "VICTIM COUNT": (v) => v,

  // If you want to hide the raw sin/cos by default, you can show a badge or blank:
  // Comment these out if you prefer to show the raw numbers.
  MONTH_SIN: (v) => v, // or: ()=>"—"
  MONTH_COS: (v) => v,
  DAYOWEEK_SIN: (v) => v,
  DAYOWEEK_COS: (v) => v,
};

// Utility: find column index by visible header text
function getColumnIndexByName(colName) {
  return $("#uploadedTable thead th")
    .toArray()
    .findIndex((th) => $(th).text().trim() === colName);
}

// Build columnDefs renderers from DISPLAY_RENDER_MAP dynamically
function buildDisplayRenderers() {
  const defs = [];
  Object.keys(DISPLAY_RENDER_MAP).forEach((colName) => {
    const idx = getColumnIndexByName(colName);
    if (idx > -1) {
      defs.push({
        targets: idx,
        render: function (data, type, row, meta) {
          // Only transform for display/filter; keep raw for sort/type = 'sort'/'type'
          if (!FRIENDLY_VIEW) return data; // raw mode
          if (type === "display" || type === "filter") {
            try {
              return DISPLAY_RENDER_MAP[colName](data);
            } catch {
              return data ?? "";
            }
          }
          return data;
        },
      });
    }
  });
  return defs;
}

if ($("#uploadedTable thead th:first").text().trim() !== "Select") {
  $("#uploadedTable thead tr").prepend(
    '<th><input type="checkbox" id="select-all"></th>'
  );
  $("#uploadedTable tbody tr").each(function () {
    $(this).prepend("<td></td>"); // placeholder for DataTables render
  });
}

// Select/Deselect all rows
$(document).on("change", "#select-all", function () {
  $(".row-select").prop("checked", this.checked);
});

$(document).ready(function () {
  console.log("Document ready, looking for table...");

  if ($(".file-selection-container").length > 0) {
    $(".breadcrumbs").show();
    $(".header").show();
  }

  // Check if the uploaded table exists
  if ($("#uploadedTable").length > 0) {
    // In database.js, inside $(document).ready() and the if ($("#uploadedTable").length > 0) block
    // START: New Export Functionality

    // --- Helper function to get currently displayed data from the table ---
    function getCurrentTableDataForExport() {
      if (!dataTable) return null;

      const headers = [];
      const columnsToSkip = []; // Store indices of columns to skip (checkbox, actions)

      // Identify headers and determine which column indices to skip
      $("#uploadedTable thead th:visible").each(function (index) {
        const headerText = $(this).text().trim().toLowerCase();
        // Skip the checkbox column (which has no text) and the "Actions" column
        if (headerText === "" || headerText === "actions") {
          columnsToSkip.push(index);
        } else {
          headers.push($(this).text().trim());
        }
      });

      const dataAsArrays = [];
      // Get data from visible rows that match the current search filter
      dataTable
        .rows({ search: "applied" })
        .nodes()
        .each(function (tr) {
          const row = [];
          $(tr)
            .find("td:visible")
            .each(function (index) {
              // Only include data from columns that are not marked to be skipped
              if (!columnsToSkip.includes(index)) {
                row.push($(this).text().trim());
              }
            });
          dataAsArrays.push(row);
        });

      // Create an array of objects, which is needed for the Excel export
      const dataAsObjects = dataAsArrays.map((rowArray) => {
        const rowObject = {};
        headers.forEach((header, index) => {
          rowObject[header] = rowArray[index];
        });
        return rowObject;
      });

      return { headers, dataAsArrays, dataAsObjects };
    }

    // --- Logic to show/hide the export dropdown menu ---
    $("#exportBtn").on("click", function (event) {
      event.stopPropagation(); // Prevents the window click event from closing the menu immediately
      $("#exportMenu").toggleClass("show");
    });

    // Close the dropdown if the user clicks anywhere else on the page
    $(window).on("click", function (event) {
      if (!$(event.target).closest(".dropdown-container").length) {
        if ($("#exportMenu").hasClass("show")) {
          $("#exportMenu").removeClass("show");
        }
      }
    });

    // --- Event listener for CSV Export ---
    // --- Event listener for CSV Export ---
    $("#exportCsvBtn").on("click", function (e) {
      e.preventDefault();
      const exportData = getCurrentTableDataForExport();
      if (!exportData || exportData.dataAsArrays.length === 0) {
        alert("No data to export.");
        return;
      }

      // --- FIX: Build CSV data separately ---
      let csvRows = [];

      // Add headers
      csvRows.push(exportData.headers.join(","));

      // Add data rows
      exportData.dataAsArrays.forEach(function (rowArray) {
        // Handle commas/quotes within data by wrapping fields in double quotes
        let row = rowArray
          .map((item) => `"${String(item).replace(/"/g, '""')}"`)
          .join(",");
        csvRows.push(row);
      });

      // Join all rows with newline characters
      let csvString = csvRows.join("\r\n");

      // Use encodeURIComponent on the data ONLY, then add the prefix
      const encodedUri =
        "data:text/csv;charset=utf-8," + encodeURIComponent(csvString);
      // --- END FIX ---

      const link = document.createElement("a");
      link.setAttribute("href", encodedUri);
      const tableName =
        new URLSearchParams(window.location.search).get("table") || "data";
      link.setAttribute("download", `${tableName}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      $("#exportMenu").removeClass("show");
    });

    // --- Event listener for Excel Export ---
    $("#exportXlsxBtn").on("click", function (e) {
      e.preventDefault();
      const exportData = getCurrentTableDataForExport();
      if (!exportData || exportData.dataAsObjects.length === 0) {
        alert("No data to export.");
        return;
      }

      // Create a worksheet from the array of objects
      const worksheet = XLSX.utils.json_to_sheet(exportData.dataAsObjects);
      const workbook = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(workbook, worksheet, "Sheet1");

      // Trigger the file download
      const tableName =
        new URLSearchParams(window.location.search).get("table") || "data";
      XLSX.writeFile(workbook, `${tableName}.xlsx`);
      $("#exportMenu").removeClass("show");
    });

    // --- Event listener for PDF Export ---
    $("#exportPdfBtn").on("click", function (e) {
      e.preventDefault();
      const exportData = getCurrentTableDataForExport();
      if (!exportData || exportData.dataAsArrays.length === 0) {
        alert("No data to export.");
        return;
      }

      const { jsPDF } = window.jspdf;
      const doc = new jsPDF({ orientation: "landscape" });

      // START: PDF Formatting Fix
      // 1. Find the index of the problematic column to target it specifically.
      const vehicleKindIndex = exportData.headers.findIndex(
        (h) => h.trim().toUpperCase() === "VEHICLE KIND"
      );

      // 2. Define a custom style to give that column more space.
      const columnStyles = {};
      if (vehicleKindIndex !== -1) {
        columnStyles[vehicleKindIndex] = {
          cellWidth: 35, // Assign a specific width (in document units)
        };
      }
      // END: PDF Formatting Fix

      doc.autoTable({
        head: [exportData.headers],
        body: exportData.dataAsArrays,
        startY: 10,
        theme: "grid",
        // MODIFIED: Slightly smaller font size improves overall fit
        styles: { fontSize: 7, cellPadding: 2 },
        headStyles: { fillColor: [4, 55, 242] },
        // MODIFIED: Apply the custom style for the 'VEHICLE KIND' column
        columnStyles: columnStyles,
      });

      const tableName =
        new URLSearchParams(window.location.search).get("table") || "data";
      doc.save(`${tableName}.pdf`);
      $("#exportMenu").removeClass("show");
    });
    // END: New Export Functionality

    console.log("Table found, initializing DataTable...");

    const staticColumnDefs = [
      {
        targets: 0,
        orderable: false,
        className: "select-checkbox",
        render: function () {
          return '<input type="checkbox" class="row-select">';
        },
      },
      {
        targets: -1,
        data: null,
        defaultContent: `<button class="delete-btn">Delete</button>`,
      },
    ];

    const displayRenderers = buildDisplayRenderers();

    // Initialize DataTable without default pagination
    dataTable = $("#uploadedTable").DataTable({
      paging: false,
      lengthChange: false,
      ordering: true,
      searching: true,
      dom: "rtip",
      language: {
        emptyTable: "No data uploaded yet.",
        zeroRecords: "No matching records found.",
        info: "Showing _TOTAL_ entries",
        infoEmpty: "No entries",
        infoFiltered: "(filtered from _MAX_ total entries)",
      },
      columnDefs: staticColumnDefs.concat(displayRenderers),
      order: [], // we'll set it dynamically in initComplete
      initComplete: function () {
        // Hide loader and show the table/controls
        $("#tableLoader").hide();
        $("#tableViewWrapper").removeClass("hidden");
        $(".breadcrumbs").show();
        $(".header").show();
        $(".upload-header").show();

        const api = this.api();

        // MODIFICATION: Find and hide the 'id' column after initialization
        const idColumnIndex = getColumnIndex(api, "id");
        if (idColumnIndex > -1) {
          api.column(idColumnIndex).visible(false);
        }

        // Move info text to custom container
        let info = $(this.api().table().container()).find(".dataTables_info");
        if ($("#customInfo").length === 0) {
          $(
            '<div id="customInfo" class="dataTables_info_container" style="margin-top:10px;"></div>'
          ).insertAfter(".table-container");
        }
        $("#customInfo").append(info);

        // Then force order by the DATE_COMMITTED column if present:
        const dateIdx = getDateColumnIndex(api);
        // you already have this helper
        if (dateIdx !== -1) {
          api.order([dateIdx, "asc"]).draw();
        }

        // Create year buttons after info text
        createYearButtons(this.api());
        filterEarliestOnLoad(this.api());
      },
    });

    // Add Edit and Save buttons outside table
    if ($("#editTableBtn").length === 0) {
      $(".main-content").append(`
        <div style="text-align: right; margin-top: 15px;">
            <button id="editTableBtn" class="edit-table-btn">Edit Table</button>
            <button id="saveTableBtn" class="save-btn" style="display:none;">Save Table</button>
        </div>
    `);
    }

    // Enable editing mode
    let isEditing = false;
    let undoStack = [];
    let redoStack = [];
    let hasUnsavedChanges = false;
    let originalDataCopy = [];

    function recordEdit(rowIdx, colIdx, oldValue, newValue) {
      undoStack.push({ rowIdx, colIdx, oldValue, newValue });
      redoStack = [];
      hasUnsavedChanges = true;
    }

    // --- UNDO / REDO implementation (paste inside $(document).ready, after recordEdit) ---
    function updateUndoRedoButtons() {
      $("#undoBtn").prop("disabled", undoStack.length === 0);
      $("#redoBtn").prop("disabled", redoStack.length === 0);
    }

    // apply an edit object to the table (use oldValue when isUndo true, otherwise newValue)
    function applyEdit(edit, isUndo) {
      try {
        let valueToApply = isUndo ? edit.oldValue : edit.newValue;
        // Ensure the cell still exists
        if (typeof dataTable.cell === "function") {
          dataTable
            .cell(edit.rowIdx, edit.colIdx)
            .data(valueToApply)
            .draw(false);
        }
      } catch (err) {
        console.warn("applyEdit failed (row may have changed):", err);
      }
    }

    // Undo
    $("#undoBtn").on("click", function () {
      if (undoStack.length === 0) return;
      let edit = undoStack.pop();
      applyEdit(edit, true); // apply oldValue
      redoStack.push(edit); // allow redo to re-apply newValue
      hasUnsavedChanges = true;
      updateUndoRedoButtons();
    });

    // Redo
    $("#redoBtn").on("click", function () {
      if (redoStack.length === 0) return;
      let edit = redoStack.pop();
      applyEdit(edit, false); // apply newValue
      undoStack.push(edit); // re-add to undo stack
      hasUnsavedChanges = true;
      updateUndoRedoButtons();
    });

    // Keyboard shortcuts: Ctrl+Z / Ctrl+Y (Cmd on Mac via metaKey)
    $(document).on("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        $("#undoBtn").click();
      }
      if (
        (e.ctrlKey || e.metaKey) &&
        (e.key.toLowerCase() === "y" ||
          (e.shiftKey && e.key.toLowerCase() === "z"))
      ) {
        e.preventDefault();
        $("#redoBtn").click();
      }
    });

    // When we record a new edit, enable/disable buttons
    // (make sure your existing recordEdit still pushes to undoStack and clears redoStack)
    let originalRecordEdit = recordEdit;
    recordEdit = function (rowIdx, colIdx, oldValue, newValue) {
      originalRecordEdit(rowIdx, colIdx, oldValue, newValue);
      updateUndoRedoButtons();
    };

    // In database.js, REPLACE your existing $('#saveTableBtn').on('click', ...) with this:
    $("#saveTableBtn").on("click", function () {
      console.log("=== SAVE BUTTON CLICKED ===");

      if (!dataTable) {
        alert("DataTable not initialized");
        return;
      }

      // If no changes were made, there's nothing to save.
      if (undoStack.length === 0) {
        alert("No changes to save.");
        // Hide the edit buttons and revert to view mode
        isEditing = false;
        hasUnsavedChanges = false;
        $("#saveTableBtn, #cancelEditBtn, #undoBtn, #redoBtn").hide();
        $("#editTableBtn, #deleteSelectedBtn").show();
        $("#uploadedTable").off("click.editMode");
        return;
      }

      // --- NEW LOGIC: Prepare only the changes for the backend ---

      // 1. Get the index of the 'id' column. It's crucial for targeting rows.
      const idColumnIndex = getColumnIndex(dataTable, "id");
      if (idColumnIndex === -1) {
        alert(
          "Critical Error: The 'id' column could not be found. Cannot save changes."
        );
        return;
      }

      // 2. Process the undoStack to get the final state of each edited cell.
      // This handles cases where the same cell is edited multiple times.
      const finalChanges = {};
      undoStack.forEach((edit) => {
        const rowData = dataTable.row(edit.rowIdx).data();
        const rowId = rowData[idColumnIndex];
        const columnHeader = dataTable
          .column(edit.colIdx)
          .header()
          .textContent.trim();

        // Create a unique key for each cell (e.g., "123-AGE")
        const cellKey = `${rowId}-${columnHeader}`;

        // Store the latest value for this cell
        finalChanges[cellKey] = {
          id: rowId,
          column: columnHeader,
          new_value: edit.newValue,
        };
      });

      // Convert the finalChanges object into an array.
      const changesToSave = Object.values(finalChanges);

      if (changesToSave.length === 0) {
        alert("No valid changes to save.");
        return;
      }

      console.log(
        `✅ Validation passed - Saving ${changesToSave.length} changes.`
      );
      console.log("Changes to send:", changesToSave);

      // 3. Update UI to show loading state
      $("#saveTableBtn").prop("disabled", true).text("Saving...");

      // 4. Send the small payload of changes to the new backend endpoint
      const currentTable = new URLSearchParams(window.location.search).get(
        "table"
      );
      fetch("/api/update_rows", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          table: currentTable,
          changes: changesToSave,
        }),
      })
        .then((response) => {
          if (!response.ok) {
            // Try to get error message from backend
            return response.json().then((err) => {
              throw new Error(
                err.message || `HTTP error! status: ${response.status}`
              );
            });
          }
          return response.json();
        })
        .then((data) => {
          if (data.success) {
            alert(data.message || "Table saved successfully!");
            // Reset stacks and flags on successful save
            undoStack = [];
            redoStack = [];
            hasUnsavedChanges = false;
            updateUndoRedoButtons();
            // Exit editing mode
            isEditing = false;
            $("#saveTableBtn, #cancelEditBtn, #undoBtn, #redoBtn").hide();
            $("#editTableBtn, #deleteSelectedBtn, .dropdown-container").show();
            $("#uploadedTable").off("click.editMode");
          } else {
            alert("Error: " + data.message);
          }
        })
        .catch((err) => {
          console.error("Save error:", err);
          alert("Error saving table: " + err.message);
        })
        .finally(() => {
          // Reset button state regardless of outcome
          $("#saveTableBtn").prop("disabled", false).text("Save Table");
        });
    });

    $("#cancelEditBtn").on("click", function () {
      // If cancel restores originalDataCopy, also clear stacks
      undoStack = [];
      redoStack = [];
      updateUndoRedoButtons();
    });

    // Initialize button states at load
    updateUndoRedoButtons();

    // Helper: restore table to original data
    function restoreOriginalData() {
      dataTable.clear();
      dataTable.rows.add(originalDataCopy);
      dataTable.draw();
    }

    // In database.js, replace the existing $("#editTableBtn").on("click",...) function

    // In database.js, REPLACE your existing $("#editTableBtn").on("click",...) function

    // In database.js, REPLACE the existing $("#editTableBtn").on("click",...) function
    $("#editTableBtn").on("click", function () {
      isEditing = true;
      hasUnsavedChanges = false;
      undoStack = [];
      redoStack = [];

      originalDataCopy = JSON.parse(
        JSON.stringify(dataTable.rows().data().toArray())
      );

      $("#editTableBtn, #deleteSelectedBtn, .dropdown-container").hide();
      $("#saveTableBtn, #cancelEditBtn, #undoBtn, #redoBtn").show();

      // Define which of the VISIBLE columns are derived and should not be editable
      const nonEditableColumns = [
        "MONTH",
        "DAY_OF_WEEK",
        "TIME_CLUSTER",
        "YEAR",
        "DAY",
        "WEEKDAY",
        "ACCIDENT_HOTSPOT",
        "GENDER_CLUSTER",
        "ALCOHOL_USED_CLUSTER",
      ];

      // --- NEW: Add a visual indicator for non-editable columns ---
      dataTable.columns().every(function () {
        const headerText = $(this.header()).text().trim();
        if (nonEditableColumns.includes(headerText)) {
          // Add the 'is-readonly' class to all cells in this column
          $(this.nodes()).addClass("is-readonly");
        }
      });

      $("#uploadedTable").on(
        "click.editMode",
        "td:not(:last-child)",
        function () {
          if (!isEditing) return;

          const columnHeader = dataTable
            .column(this)
            .header()
            .textContent.trim();

          // This check now functionally prevents the edit
          if (nonEditableColumns.includes(columnHeader)) {
            return;
          }

          let cell = dataTable.cell(this);
          let originalValue = cell.data();
          let rowIdx = cell.index().row;
          let colIdx = cell.index().column;

          if ($(this).find("input").length > 0) return;

          let input = $('<input type="text">').val(originalValue);
          $(this).html(input);

          input
            .on("blur keyup", function (e) {
              if (e.type === "blur" || e.keyCode === 13) {
                let newValue = $(this).val();
                if (newValue !== originalValue) {
                  recordEdit(rowIdx, colIdx, originalValue, newValue);
                }
                cell.data(newValue).draw(false);
              }
            })
            .focus();
        }
      );
    });

    // In database.js, REPLACE the existing $("#cancelEditBtn").on("click",...) function
    $("#cancelEditBtn").on("click", function () {
      if (hasUnsavedChanges) {
        let confirmExit = confirm(
          "You have unsaved changes. If you cancel, they will be lost. Continue?"
        );
        if (!confirmExit) return;
      }

      restoreOriginalData();

      isEditing = false;
      $("#saveTableBtn, #cancelEditBtn, #undoBtn, #redoBtn").hide();
      $("#editTableBtn, #deleteSelectedBtn, .dropdown-container").show();
      $("#uploadedTable").off("click.editMode");

      // --- NEW: Clean up the visual indicators ---
      $("#uploadedTable td").removeClass("is-readonly");

      undoStack = [];
      redoStack = [];
      hasUnsavedChanges = false;
    });
    $("#cancelEditBtn").on("click", function () {
      if (hasUnsavedChanges) {
        let confirmExit = confirm(
          "You have unsaved changes. If you cancel, they will be lost. Continue?"
        );
        if (!confirmExit) return;
      }

      // Restore original data so nothing changes
      restoreOriginalData();

      isEditing = false;
      $("#saveTableBtn, #cancelEditBtn, #undoBtn, #redoBtn").hide();
      $("#editTableBtn, #deleteSelectedBtn, #mergeFileBtn, #uploadForm").show();
      $("#uploadedTable").off("click.editMode");

      undoStack = [];
      redoStack = [];
      hasUnsavedChanges = false;
    });

    // Bind custom search input with debouncing
    let searchTimeout;
    $("#customSearch").on("input", function () {
      const searchValue = this.value;
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(function () {
        if (dataTable) {
          dataTable.search(searchValue).draw();
        }
      }, 300);
    });

    // Clear search with ESC key
    $("#customSearch").on("keyup", function (e) {
      if (e.keyCode === 27) {
        // ESC
        this.value = "";
        if (dataTable) {
          dataTable.search("").draw();
        }
      }
    });
  } else {
    console.log('No table found with ID "uploadedTable"');
  }
});

// MODIFICATION: Helper to find a column's index by its header text
function getColumnIndex(dt, columnName) {
  let index = -1;
  dt.columns().every(function (i) {
    if (this.header().textContent.trim() === columnName) {
      index = i;
    }
  });
  return index;
}

function getDateColumnIndex(api) {
  return api
    .columns()
    .header()
    .toArray()
    .findIndex(
      (header) => $(header).text().trim().toUpperCase() === "DATE_COMMITTED"
    );
}

function createYearButtons(api) {
  let years = [];
  let dateColumnIndex = getDateColumnIndex(api);
  if (dateColumnIndex === -1) {
    console.warn("DATE_COMMITTED column not found!");
    return;
  }

  // Extract unique years
  api
    .column(dateColumnIndex, { search: "applied" }) // Use applied search to get all data
    .data()
    .unique()
    .sort()
    .each(function (value) {
      let year = new Date(value).getFullYear();
      if (!isNaN(year) && !years.includes(year)) {
        years.push(year);
      }
    });
  years.sort((a, b) => a - b);

  let container = $(
    '<div class="year-buttons-container" style="display:flex;justify-content:space-between;align-items:center;width:100%;"></div>'
  ).insertAfter(".dataTables_info_container");
  let infoContainer = $("#customInfo").css({ margin: 0 });
  let yearNav = $(
    '<div class="year-buttons" style="display:flex;align-items:center;"></div>'
  );
  let visibleStart = 0;
  const maxVisible = 5;
  let selectedYear = null;

  function renderYears() {
    yearNav.empty();

    // "All Years" button to clear the filter
    let allBtn = $('<button class="year-btn">All Years</button>')
      .appendTo(yearNav)
      .on("click", function () {
        selectedYear = null;
        // 🎯 FIX: Clear the search on the specific date column
        api.column(dateColumnIndex).search("").draw();
        $(".year-btn").removeClass("active");
        $(this).addClass("active");
        $("#currentYearDisplay").text("All Years");
      });

    // Set initial active state for "All Years"
    if (selectedYear === null) {
      allBtn.addClass("active");
    }

    // Left navigation arrow
    $('<button class="year-nav-btn">&lt;</button>')
      .prop("disabled", visibleStart === 0)
      .on("click", function () {
        if (visibleStart > 0) {
          visibleStart -= maxVisible;
          if (visibleStart < 0) visibleStart = 0;
          renderYears();
        }
      })
      .appendTo(yearNav);

    // Year buttons
    years
      .slice(visibleStart, visibleStart + maxVisible)
      .forEach(function (year) {
        let btn = $('<button class="year-btn">' + year + "</button>")
          .appendTo(yearNav)
          .on("click", function () {
            selectedYear = year;
            // 🎯 FIX: Apply search to the specific date column, not globally
            api.column(dateColumnIndex).search(year).draw();
            $(".year-btn").removeClass("active");
            $(this).addClass("active");
            $("#currentYearDisplay").text(year);
          });

        if (selectedYear === year) {
          btn.addClass("active");
        }
      });

    // Right navigation arrow
    $('<button class="year-nav-btn">&gt;</button>')
      .prop("disabled", visibleStart + maxVisible >= years.length)
      .on("click", function () {
        if (visibleStart + maxVisible < years.length) {
          visibleStart += maxVisible;
          renderYears();
        }
      })
      .appendTo(yearNav);
  }

  container.append(infoContainer).append(yearNav);
  renderYears();
  // Set default state on load
  filterEarliestOnLoad(api);
}

function filterEarliestOnLoad(api) {
  let years = [];
  let dateColumnIndex = getDateColumnIndex(api);
  if (dateColumnIndex === -1) {
    console.warn("DATE_COMMITTED column not found for initial filter!");
    return;
  }

  api
    .column(dateColumnIndex)
    .data()
    .each(function (value) {
      let year = new Date(value).getFullYear();
      if (!isNaN(year)) years.push(year);
    });

  if (years.length > 0) {
    years = [...new Set(years)]; // get unique years
    let earliestYear = Math.min(...years);
    let targetYear = years.includes(2015) ? 2015 : earliestYear;

    // 🎯 FIX: Apply search to the specific date column
    api.column(dateColumnIndex).search(targetYear).draw();

    $(".year-btn").removeClass("active");
    $(".year-btn")
      .filter(function () {
        return $(this).text() == targetYear;
      })
      .addClass("active");
    $("#currentYearDisplay").text(targetYear);
  }
}

// Function to reinitialize DataTable after new data is uploaded
function reinitializeTable() {
  console.log("Reinitializing table...");

  if (dataTable) {
    dataTable.destroy();
    dataTable = null;
  }

  setTimeout(function () {
    $(document).ready();
  }, 100);
}

// Logout modal functions
function openLogoutModal(event) {
  event.preventDefault();
  document.getElementById("logoutModal").classList.remove("hidden");
}

function closeLogoutModal() {
  document.getElementById("logoutModal").classList.add("hidden");
}

function confirmLogout() {
  window.location.href = "/logout";
}

function checkIfTableEmpty() {
  if (dataTable && dataTable.rows().count() === 0) {
    // Destroy DataTable
    dataTable.destroy();
    dataTable = null;

    // Clear the table container
    $("#tableView").empty();

    // Remove custom info and pagination if any
    $("#customInfo").remove();
    $(".year-buttons-container").remove();

    // Show "no data" state
    $(".file-selection-container").show();
  }
}

function removeTableCompletely() {
  if (dataTable) {
    dataTable.destroy(); // kill DataTable instance
    dataTable = null;
  }

  // Clear the table container
  $("#tableView").empty();

  // Remove info/pagination/year buttons
  $("#customInfo").remove();
  $(".year-buttons-container").remove();

  // Clear year title
  $("#currentYearDisplay").text("");

  // Show the "no data" file selection UI again
  $(".file-selection-container").show();
}

// NEW FUNCTION TO HANDLE UI STATE AFTER DELETION
function handlePostDelete() {
  // After a delete operation, we check the state of the table.

  // First, check if the entire underlying dataset is empty.
  if (dataTable.rows().count() === 0) {
    // If so, completely remove the table UI and show the file selection view.
    removeTableCompletely();
    return;
  }

  // If the table is not empty overall, check if the *currently filtered view* is empty.
  // This happens if the user deletes all rows for a selected year.
  if (dataTable.rows({ search: "applied" }).count() === 0) {
    // The cleanest way to update the UI (especially the year buttons)
    // is to reload the page. This ensures the deleted year no longer appears as an option.
    alert(
      "All entries for the current view have been deleted. The page will now refresh to update the view."
    );
    location.reload();
  }
}

// --- REPLACEMENT: Single row delete with backend call ---
$("#uploadedTable").on("click", ".delete-btn", function () {
  const row = dataTable.row($(this).parents("tr"));
  const rowData = row.data();
  const idColumnIndex = getColumnIndex(dataTable, "id");

  if (idColumnIndex === -1) {
    alert(
      "Error: Cannot delete row because the 'id' column is missing from the data."
    );
    return;
  }

  const rowId = parseInt(rowData[idColumnIndex]);
  if (!rowId) {
    alert("Error: Could not determine the ID for this row.");
    return;
  }

  if (confirm("Are you sure you want to delete this row from the database?")) {
    const currentTable = new URLSearchParams(window.location.search).get(
      "table"
    );
    if (!currentTable) {
      alert("Error: Could not determine the current table name.");
      return;
    }

    fetch("/api/delete_rows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ table: currentTable, row_ids: [rowId] }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          row.remove().draw(); // Remove from UI on success
          alert(data.message);
          handlePostDelete(); // Check if the table/view is now empty
        } else {
          alert("Backend Error: " + data.message);
        }
      })
      .catch((error) => {
        console.error("Fetch Error:", error);
        alert("An unexpected network error occurred. Could not delete row.");
      });
  }
});

// --- REPLACEMENT: Delete selected rows with backend call ---
$("#deleteSelectedBtn").on("click", function () {
  const selectedRows = dataTable.rows(".row-selected");
  if (selectedRows.count() === 0) {
    alert("No rows selected.");
    return;
  }

  const idColumnIndex = getColumnIndex(dataTable, "id");
  if (idColumnIndex === -1) {
    alert(
      "Error: Cannot delete rows because the 'id' column is missing from the data."
    );
    return;
  }

  // Get all the unique IDs from the selected rows
  const idsToDelete = selectedRows
    .data()
    .toArray()
    .map((rowData) => parseInt(rowData[idColumnIndex]))
    .filter((id) => !isNaN(id));

  if (idsToDelete.length === 0) {
    alert("Could not find valid IDs for the selected rows.");
    return;
  }

  if (
    confirm(
      `Are you sure you want to delete ${idsToDelete.length} selected row(s) from the database?`
    )
  ) {
    const currentTable = new URLSearchParams(window.location.search).get(
      "table"
    );
    if (!currentTable) {
      alert("Error: Could not determine the current table name.");
      return;
    }

    fetch("/api/delete_rows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ table: currentTable, row_ids: idsToDelete }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          selectedRows.remove().draw(); // Remove from UI on success
          alert(data.message);
          // Uncheck the "select all" box
          $("#select-all").prop("checked", false);
          handlePostDelete(); // Check if the table/view is now empty
        } else {
          alert("Backend Error: " + data.message);
        }
      })
      .catch((error) => {
        console.error("Fetch Error:", error);
        alert("An unexpected network error occurred. Could not delete rows.");
      });
  }
});

// Auto open file picker and submit
$("#triggerFileUpload").on("click", function (e) {
  e.preventDefault();
  openUploadModal(); // just open modal
});

$("#hiddenFileInput").on("change", function () {
  if (this.files.length > 0) {
    $(this).closest("form").submit();
  }
});

// Highlight selected rows
$(document).on("change", ".row-select", function () {
  $(this).closest("tr").toggleClass("row-selected", this.checked);
});

// Select/Deselect all rows
$(document).on("change", "#select-all", function () {
  const isChecked = this.checked;
  // Find all checkboxes in the current view and check/uncheck them
  $(".row-select", dataTable.rows({ page: "current" }).nodes())
    .prop("checked", isChecked)
    .trigger("change");
});

$("#mergeFileBtn").on("click", function () {
  alert("Merge file feature coming soon!");
});

$("#retrainBtn").on("click", function () {
  if (
    confirm(
      "Are you sure you want to retrain the model with the current uploaded data?"
    )
  ) {
    fetch("/api/retrain_model", { method: "POST" })
      .then((res) => res.json())
      .then((data) => {
        alert(data.message || "Model retraining started successfully!");
      })
      .catch((err) => {
        console.error(err);
        alert("Error retraining model.");
      });
  }
});

// In database.js

function selectFile(tableName) {
  window.location.href = `/database?table=${tableName}`;
}

let currentFile = null;

document.addEventListener("contextmenu", function (e) {
  // Check if right click happened on a file card
  let card = e.target.closest(".file-card-big");
  if (card) {
    e.preventDefault(); // Stop default right-click menu

    currentFile = card.querySelector("p").innerText; // store file name

    let menu = document.getElementById("fileContextMenu");
    menu.classList.remove("hidden");

    // Position the menu where the mouse is
    menu.style.top = `${e.pageY}px`;
    menu.style.left = `${e.pageX}px`;
  } else {
    document.getElementById("fileContextMenu").classList.add("hidden");
  }
});

// Hide menu when clicking elsewhere
document.addEventListener("click", function () {
  document.getElementById("fileContextMenu").classList.add("hidden");
});

// Functions for menu options
function editFile() {
  if (currentFile) {
    // ✅ Redirect straight to your Flask endpoint
    window.location.href = `/database?table=${currentFile}`;
  }
}

let fileToDelete = null;

function deleteFile() {
  if (currentFile) {
    fileToDelete = currentFile; // store filename
    document.getElementById(
      "deleteFileMessage"
    ).innerText = `Are you sure you want to delete "${fileToDelete}"?`;
    document.getElementById("deleteFileModal").classList.remove("hidden");
  }
}

// In database.js, replace the appendFile() function

function appendFile() {
  if (currentFile) {
    fileToAppend = currentFile;
    document.getElementById("sourceFileName").innerText = fileToAppend;

    // --- START OF NEW LOGIC ---
    const targetInput = document.getElementById("appendTargetTable");
    const dropdownList = document.getElementById("appendDropdownList");

    // Get all available tables from the file cards, excluding the source file
    const allTables = Array.from(document.querySelectorAll(".file-card-big p"))
      .map((p) => p.innerText)
      .filter((table) => table !== fileToAppend);

    if (allTables.length === 0) {
      alert("No other tables available to append to.");
      return;
    }

    function showAppendDropdown(list) {
      dropdownList.innerHTML = list.length
        ? list.map((opt) => `<div class="dropdown-item">${opt}</div>`).join("")
        : `<div class="dropdown-item no-results">No tables found</div>`;
      dropdownList.style.display = "block";
    }

    // Show all options on focus
    targetInput.addEventListener("focus", () => showAppendDropdown(allTables));

    // Filter options on input
    targetInput.addEventListener("input", function () {
      const searchTerm = this.value.toLowerCase();
      const filtered = allTables.filter((table) =>
        table.toLowerCase().includes(searchTerm)
      );
      showAppendDropdown(filtered);
    });

    // Handle selection from dropdown
    dropdownList.addEventListener("click", function (e) {
      if (
        e.target.classList.contains("dropdown-item") &&
        !e.target.classList.contains("no-results")
      ) {
        targetInput.value = e.target.textContent;
        dropdownList.style.display = "none";
      }
    });
    // --- END OF NEW LOGIC ---

    // Open the modal
    document.getElementById("appendFileModal").classList.remove("hidden");
  }
}

function closeAppendFileModal() {
  document.getElementById("appendFileModal").classList.add("hidden");
  fileToAppend = null;
}

function confirmAppendFile() {
  if (!fileToAppend) return;

  // Read value from the text input instead of the select
  const targetTable = document.getElementById("appendTargetTable").value;
  const deleteSource = document.getElementById(
    "deleteSourceAfterAppend"
  ).checked;

  if (!targetTable) {
    alert("Please select a target table.");
    return;
  }

  if (targetTable === fileToAppend) {
    alert("Source and target tables cannot be the same.");
    return;
  }

  fetch("/api/append_table", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_table: fileToAppend,
      target_table: targetTable,
      delete_source: deleteSource,
    }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        alert(data.message);
        location.reload();
      } else {
        alert("Error: " + data.message);
      }
    })
    .catch((err) => {
      console.error("Append error:", err);
      alert("An error occurred while appending the file.");
    })
    .finally(() => {
      closeAppendFileModal();
    });
}

// Pick this file (DB table) for the dashboard map forecasting model
async function useForForecast() {
  if (!currentFile) return;

  try {
    const res = await fetch("/api/set_forecast_source", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ table: currentFile }),
    });

    const payload = await res.json();
    if (!res.ok || payload.success === false) {
      throw new Error(payload.message || "Failed to set forecast source.");
    }

    alert(
      `✓ "${currentFile}" will be used by the Dashboard map forecasting model.`
    );
    // Optional: jump straight to the Dashboard so they see it
    if (confirm("Open Dashboard now to view the forecast?")) {
      window.location.href = "/dashboard";
    }
  } catch (err) {
    console.error(err);
    alert("Error: " + err.message);
  } finally {
    document.getElementById("fileContextMenu").classList.add("hidden");
  }
}

function closeDeleteFileModal() {
  document.getElementById("deleteFileModal").classList.add("hidden");
  fileToDelete = null;
}

function confirmDeleteFile() {
  if (!fileToDelete) return;

  fetch("/api/delete_file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ table: fileToDelete }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.success) {
        alert(data.message);
        location.reload();
      } else {
        alert("Error: " + data.message);
      }
    })
    .catch((err) => {
      console.error("Delete error:", err);
      alert("Error deleting file.");
    })
    .finally(() => {
      closeDeleteFileModal();
    });
}

function openUploadModal() {
  document.getElementById("uploadModal").classList.remove("hidden");
}

function closeUploadModal() {
  document.getElementById("uploadModal").classList.add("hidden");
}

function triggerHiddenInput(num) {
  document.getElementById(`fileInput${num}`).click();
}

// Show the selected file name without expanding slot size
["fileInput1", "fileInput2"].forEach((id) => {
  const input = document.getElementById(id);
  input.addEventListener("change", function () {
    const slot = this.closest(".upload-slot");
    const plusIcon = slot.querySelector(".plus-icon");
    const placeholder = slot.querySelector(".file-placeholder");
    const fileIcon = slot.querySelector(".file-icon");
    const fileNameEl = slot.querySelector(".file-name");

    if (this.files.length > 0) {
      plusIcon.style.display = "none";
      placeholder.style.display = "none";
      fileIcon.style.display = "block";
      fileNameEl.textContent = this.files[0].name;
      fileNameEl.style.display = "block";
    } else {
      plusIcon.style.display = "block";
      placeholder.style.display = "block";
      fileIcon.style.display = "none";
      fileNameEl.style.display = "none";
    }
  });
});

// Show/hide target selector
document.addEventListener("click", (e) => {
  if (e.target?.id === "appendToggle") {
    const wrap = document.getElementById("appendTargetWrap");
    const fileNameField = document.getElementById("fileNameInput");
    const fileNameLabel = document.querySelector("label[for='fileNameInput']");

    if (wrap) {
      // Show if checked, hide if not checked
      wrap.classList.toggle("hidden", !e.target.checked);
    }

    if (e.target.checked) {
      initializeAppendTargetDropdown();
    }

    if (fileNameField && fileNameLabel) {
      if (e.target.checked) {
        fileNameField.style.display = "none";
        fileNameLabel.style.display = "none";
      } else {
        fileNameField.style.display = "block";
        fileNameLabel.style.display = "block";
      }
    }
  }
});

const REQUIRED_FILE1_COLUMNS = [
  "STATION",
  "BARANGAY",
  "DATE COMMITTED",
  "TIME COMMITTED",
  "OFFENSE",
  "LATITUDE",
  "LONGITUDE",
  "VICTIM COUNT",
  "SUSPECT COUNT",
  "VEHICLE KIND",
];

const REQUIRED_FILE2_VARIANTS = [
  [
    "Date Committed",
    "Station",
    "Barangay",
    "Offense",
    "Age",
    "Gender",
    "Alcohol_Used",
  ],
  [
    "DATE COMMITTED",
    "STATION",
    "BARANGAY",
    "OFFENSE",
    "AGE",
    "GENDER",
    "ALCOHOL_USED",
  ],
];

// NEW function to initialize the searchable dropdown inside the upload modal
function initializeAppendTargetDropdown() {
  const targetInput = document.getElementById("appendTarget");
  const dropdownList = document.getElementById("appendUploadDropdownList");

  // Get all available tables from the file cards on the main page
  const allTables = Array.from(
    document.querySelectorAll(".file-card-big p")
  ).map((p) => p.innerText);

  function showAppendUploadDropdown(list) {
    dropdownList.innerHTML = list.length
      ? list.map((opt) => `<div class="dropdown-item">${opt}</div>`).join("")
      : `<div class="dropdown-item no-results">No tables found</div>`;
    dropdownList.style.display = "block";
  }

  targetInput.addEventListener("focus", () =>
    showAppendUploadDropdown(allTables)
  );

  targetInput.addEventListener("input", function () {
    const searchTerm = this.value.toLowerCase();
    const filtered = allTables.filter((table) =>
      table.toLowerCase().includes(searchTerm)
    );
    showAppendUploadDropdown(filtered);
  });

  dropdownList.addEventListener("click", function (e) {
    if (
      e.target.classList.contains("dropdown-item") &&
      !e.target.classList.contains("no-results")
    ) {
      targetInput.value = e.target.textContent;
      dropdownList.style.display = "none";
    }
  });

  // Hide dropdown when clicking outside of it
  document.addEventListener("click", (e) => {
    if (!targetInput.parentElement.contains(e.target)) {
      dropdownList.style.display = "none";
    }
  });
}

// --- REPLACE the entire submitUpload() in database.js with this ---
async function submitUpload() {
  const fileName = document.getElementById("fileNameInput").value?.trim();
  const file1 = document.getElementById("fileInput1").files[0] || null;
  const file2 = document.getElementById("fileInput2").files[0] || null;

  if (!file1 || !file2) {
    alert("Please choose two files.");
    return;
  }

  // 🚨 Duplicate file check
  if (file1.name === file2.name) {
    alert(
      "Error: You uploaded the same Excel file twice. Please choose different files."
    );
    return;
  }

  try {
    const [cols1, cols2] = await Promise.all([
      getFileHeaders(file1),
      getFileHeaders(file2),
    ]);

    // File1 check
    const missingInFile1 = REQUIRED_FILE1_COLUMNS.filter(
      (col) => !cols1.includes(col)
    );
    if (missingInFile1.length > 0) {
      alert(
        `Error: The first Excel file is missing required columns: ${missingInFile1.join(
          ", "
        )}`
      );
      return;
    }

    // File2 check → must match at least one variant fully
    const file2Valid = REQUIRED_FILE2_VARIANTS.some((variant) =>
      variant.every((col) => cols2.includes(col))
    );

    if (!file2Valid) {
      alert(
        "Error: The second Excel file does not match the required schema. It must have either:\n" +
          "• Date Committed, Station, Barangay, Offense, Age, Gender, Alcohol_Used\n" +
          "or\n" +
          "• DATE COMMITTED, STATION, BARANGAY, OFFENSE, AGE, GENDER, ALCOHOL_USED"
      );
      return;
    }
  } catch (err) {
    console.error("Excel header validation failed:", err);
    alert("Error reading Excel headers. Please check your files.");
    return;
  }

  const fd = new FormData();
  fd.append("file_name", fileName || "accidents");
  fd.append("file1", file1);
  fd.append("file2", file2);

  const appendMode = !!document.getElementById("appendToggle")?.checked;
  const appendTarget = document.getElementById("appendTarget")?.value || "";
  fd.append("append_mode", appendMode ? "1" : "0");
  if (appendMode && appendTarget) fd.append("append_target", appendTarget);

  const btn = document.querySelector(".done-btn");
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Processing…";

  openProgressModal();
  setStep("merge"); // Start at 25%

  try {
    // wait a little so the merge step animates
    await new Promise((r) => setTimeout(r, 1000));

    const res = await fetch("/api/upload_files", { method: "POST", body: fd });
    const out = await res.json();

    if (!res.ok || !out.success) {
      throw new Error(out.message || "Upload failed.");
    }

    // show preprocessing stage
    setStep("preprocess");
    await new Promise((r) => setTimeout(r, 1000));

    // show complete stage
    setStep("complete");

    // wait until the bar visually hits 100% before alert
    await new Promise((r) => setTimeout(r, 600));

    alert(out.message);

    // refresh list / redirect
    window.location.reload();
  } catch (err) {
    console.error(err);
    alert(`Error: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

function getFileHeaders(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = function (e) {
      try {
        const data = new Uint8Array(e.target.result);
        const workbook = XLSX.read(data, { type: "array" });

        // read the first sheet
        const firstSheet = workbook.Sheets[workbook.SheetNames[0]];

        // convert to JSON with header mapping
        const headers = [];
        const range = XLSX.utils.decode_range(firstSheet["!ref"]);
        const firstRow = range.s.r; // first row index

        for (let c = range.s.c; c <= range.e.c; ++c) {
          const cell = firstSheet[XLSX.utils.encode_cell({ r: firstRow, c })];
          let header = cell ? cell.v : `Column${c + 1}`;
          headers.push(String(header).trim());
        }

        resolve(headers);
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = reject;
    reader.readAsArrayBuffer(file); // important for Excel
  });
}

// Override old upload click
document
  .getElementById("triggerFileUpload")
  .addEventListener("click", function (e) {
    e.preventDefault();
    openUploadModal();
  });

// --- Modal open/close
function openProgressModal() {
  resetProgressUI();
  document.getElementById("progressModal").classList.remove("hidden");
}
function closeProgressModal() {
  document.getElementById("progressModal").classList.add("hidden");
}

// --- Progress UI control
function setPercent(pct) {
  const fill = document.getElementById("pbFill");
  const badge = document.getElementById("pbBadge");
  fill.style.width = `${pct}%`;
  badge.textContent = `${Math.round(pct)}%`;
}

function setStep(state) {
  // state: "merge" | "preprocess" | "complete"
  const map = {
    merge: { pct: 25, active: "dot-merge", done: [] },
    preprocess: { pct: 65, active: "dot-preprocess", done: ["dot-merge"] },
    complete: {
      pct: 100,
      active: "dot-complete",
      done: ["dot-merge", "dot-preprocess"],
    },
  };
  const conf = map[state];
  if (!conf) return;

  // percent bar
  setPercent(conf.pct);

  // step states
  ["dot-merge", "dot-preprocess", "dot-complete"].forEach((id) => {
    const el = document.getElementById(id);
    el.classList.remove("active", "done");
  });
  conf.done.forEach((id) => document.getElementById(id).classList.add("done"));
  document.getElementById(conf.active).classList.add("active");

  // button state
  const btn = document.getElementById("pbActionBtn");
  if (state === "complete") {
    btn.disabled = false;
    btn.textContent = "Finish";
  } else {
    btn.disabled = true;
    btn.textContent = "Save Progress";
  }
}

function resetProgressUI() {
  setPercent(0);
  ["dot-merge", "dot-preprocess", "dot-complete"].forEach((id) => {
    const el = document.getElementById(id);
    el.classList.remove("active", "done");
  });
  setStep("merge");
  document.getElementById("pbNote").textContent =
    "Please keep this window open.";
}

document.getElementById("pbActionBtn")?.addEventListener("click", () => {
  // what happens after finish (close + refresh)
  closeProgressModal();
  window.location.reload();
});
