document.addEventListener("DOMContentLoaded", () => {
  const refreshBtn = document.getElementById("refresh-btn");
  const addSelectedBtn = document.getElementById("add-selected-btn");
  const grid = document.querySelector(".inventory-grid");

  refreshBtn.addEventListener("click", async () => {
    refreshBtn.disabled = true;
    const game = new URLSearchParams(location.search).get("game");
    await fetch(`api/v1/inventory/refresh?game=${game}`, {method: "PUT"});
    location.reload();
  });

  grid.addEventListener("change", () => {
    const anyChecked = grid.querySelectorAll('input[name="asset_ids"]:checked').length > 0;
    addSelectedBtn.disabled = !anyChecked;
  });

  addSelectedBtn.addEventListener("click", async () => {
    const checked = Array.from(grid.querySelectorAll('input[name="asset_ids"]:checked'));
    const asset_ids = checked.map(cb => cb.value);

    const resp = await fetch("/api/v1/pool/add-multiple", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({asset_ids})
    });

    if (resp.ok) {
      window.location.href = "/pool";
    } else {
      const err = await resp.text();
      alert("Failed to add items: " + err);
    }
  });
});