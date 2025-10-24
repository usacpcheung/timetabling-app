// Enhance attendance tables with pagination and search

document.addEventListener("DOMContentLoaded", () => {
  const table1 = document.getElementById("active-table");
  if (table1 && window.simpleDatatables) {
    new simpleDatatables.DataTable(table1, {
      searchable: true,
      perPage: 10,
      perPageSelect: [5, 10, 15, 20]
    });
  }

  const table2 = document.getElementById("inactive-table");
  if (table2 && window.simpleDatatables) {
    new simpleDatatables.DataTable(table2, {
      searchable: true,
      perPage: 10,
      perPageSelect: [5, 10, 15, 20]
    });
  }

  const table3 = document.getElementById("deleted-table");
  if (table3 && window.simpleDatatables) {
    new simpleDatatables.DataTable(table3, {
      searchable: true,
      perPage: 10,
      perPageSelect: [5, 10, 15, 20]
    });
  }
});