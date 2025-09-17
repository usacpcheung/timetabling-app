// Enhance attendance tables with pagination and search

const TABLE_OPTIONS = {
  searchable: true,
  perPage: 10,
  perPageSelect: [5, 10, 15, 20]
};

function resolveConstructor() {
  if (window.simpleDatatables && window.simpleDatatables.DataTable) {
    return window.simpleDatatables.DataTable;
  }
  if (typeof window.DataTable === "function") {
    return window.DataTable;
  }
  return null;
}

function enhanceTable(table) {
  if (!table || table.dataset.datatableInitialised === "true") {
    return true;
  }
  const Ctor = resolveConstructor();
  if (!Ctor) {
    return false;
  }
  new Ctor(table, TABLE_OPTIONS);
  table.dataset.datatableInitialised = "true";
  return true;
}

function initialiseTables() {
  const tables = [
    document.getElementById("active-table"),
    document.getElementById("deleted-table")
  ];
  const allReady = tables.every(enhanceTable);
  if (!allReady) {
    window.setTimeout(initialiseTables, 50);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialiseTables);
} else {
  initialiseTables();
}
