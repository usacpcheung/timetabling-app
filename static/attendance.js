// Enhance attendance tables with pagination and search

const TABLE_OPTIONS = {
  searchable: true,
  perPage: 10,
  perPageSelect: [5, 10, 15, 20]
};

const TABLE_IDS = ["active-table", "deleted-table"];

function resolveDataTable() {
  if (window.simpleDatatables && typeof window.simpleDatatables.DataTable === "function") {
    return window.simpleDatatables.DataTable;
  }
  if (typeof window.DataTable === "function") {
    return window.DataTable;
  }
  return null;
}

function initialiseTables() {
  const Ctor = resolveDataTable();
  if (!Ctor) {
    window.setTimeout(initialiseTables, 50);
    return;
  }

  TABLE_IDS.forEach(id => {
    const table = document.getElementById(id);
    if (!table || table.dataset.datatableInitialised === "true") {
      return;
    }
    new Ctor(table, TABLE_OPTIONS);
    table.dataset.datatableInitialised = "true";
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialiseTables);
} else {
  initialiseTables();
}
