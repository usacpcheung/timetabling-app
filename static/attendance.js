// Enhance attendance tables with pagination and search

const TABLE_OPTIONS = {
  searchable: true,
  perPage: 10,
  perPageSelect: [5, 10, 15, 20]
};

function cloneOptions() {
  return {
    searchable: TABLE_OPTIONS.searchable,
    perPage: TABLE_OPTIONS.perPage,
    perPageSelect: Array.isArray(TABLE_OPTIONS.perPageSelect)
      ? [...TABLE_OPTIONS.perPageSelect]
      : TABLE_OPTIONS.perPageSelect
  };
}

function extractHeadings(table) {
  const head = table.tHead;
  if (!head || !head.rows.length) {
    return [];
  }
  return Array.from(head.rows[0].cells, cell => cell.innerHTML.trim());
}

function extractRows(table) {
  if (!table.tBodies || !table.tBodies.length) {
    return [];
  }
  const rows = [];
  Array.from(table.tBodies).forEach(tbody => {
    Array.from(tbody.rows).forEach(row => {
      const cells = Array.from(row.cells, cell => cell.innerHTML.trim());
      if (cells.length) {
        rows.push(cells);
      }
    });
  });
  return rows;
}

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
  const options = cloneOptions();
  const dataRows = extractRows(table);
  if (dataRows.length) {
    options.data = {
      headings: extractHeadings(table),
      data: dataRows
    };
  }
  new Ctor(table, options);
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
