document.addEventListener("DOMContentLoaded", () => {
  const table1 = document.getElementById("active-table");
  if (table1 && window.simpleDatatables) {
    new simpleDatatables.DataTable(table1, {
      searchable: true,
      perPage: 15,
      perPageSelect: [20, 25, 30]
    });
  }

  const table2 = document.getElementById("deleted-table");
  if (table2 && window.simpleDatatables) {
    new simpleDatatables.DataTable(table2, {   // ← use table2, not table1
      searchable: true,
      perPage: 15,
      perPageSelect: [20, 25, 30]
    });
  }
});