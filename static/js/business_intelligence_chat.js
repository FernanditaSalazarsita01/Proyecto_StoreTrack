(() => {
  "use strict";

  const form = document.getElementById("bi-chat-form");
  const input = document.getElementById("bi-question");
  const messages = document.getElementById("bi-chat-messages");
  const submitButton = document.getElementById("bi-chat-submit");
  if (!form || !input || !messages || !submitButton) return;

  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

  const money = value => Number(value || 0).toLocaleString("es-MX", {style: "currency", currency: "MXN"});

  function addMessage(role, text) {
    const wrapper = document.createElement("div");
    wrapper.className = `bi-message bi-message-${role}`;
    wrapper.innerHTML = `<div class="bi-message-bubble" style="white-space:pre-line">${escapeHtml(text)}</div>`;
    messages.appendChild(wrapper);
    messages.scrollTop = messages.scrollHeight;
  }

  function detail(row, type) {
    if (type === "customers") return `${row.purchases ?? 0} compras · ${money(row.total_spent)}`;
    if (type === "inactive_customers") return `${row.days_since_last_purchase ?? 0} días sin comprar · ${money(row.total_spent)}`;
    if (type === "preferred_products") return `Prefiere: ${row.preferred_product || "Sin información"}`;
    if (type === "credits") return `${row.max_days_overdue ?? 0} días · ${money(row.balance)}`;
    if (type === "slow_products") return `${row.days_without_sale ?? "Nunca vendido"} días · ${money(row.inventory_value)}`;
    if (type === "overstock") return `Stock ${row.stock ?? 0} · ${money(row.inventory_value)}`;
    if (type === "trends") return `${row.previous_units ?? 0} → ${row.current_units ?? 0} uds. (${row.change_percent ?? 0}%)`;
    if (type === "profile") return `${row.units ?? 0} unidades`;
    if (type === "sale") return money(row.total ?? row.revenue);
    if (row.coverage_days !== undefined) return `Stock ${row.stock ?? 0} · ${row.coverage_days ?? "sin consumo"} días`;
    if (row.units_sold !== undefined) return `${row.units_sold} unidades · ${money(row.revenue)}`;
    return row.stock !== undefined ? `Stock: ${row.stock}` : "";
  }

  function renderRows(result) {
    const rows = Array.isArray(result.rows) ? result.rows : [];
    if (!rows.length) return;
    const card = document.createElement("div");
    card.className = "bi-result-card";
    card.innerHTML = rows.slice(0, 10).map(row => `
      <div class="bi-result-row">
        <strong>${escapeHtml(row.name || row.customer_name || row.date || "Resultado")}</strong>
        <span>${escapeHtml(detail(row, result.data_type))}</span>
      </div>`).join("");
    messages.appendChild(card);
    messages.scrollTop = messages.scrollHeight;
  }

  async function ask(question) {
    const clean = String(question || "").trim();
    if (!clean) return;
    addMessage("user", clean);
    input.value = "";
    submitButton.disabled = true;
    submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Consultando';
    try {
      const response = await fetch(form.dataset.endpoint, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question: clean})
      });
      const result = await response.json();
      addMessage("assistant", result.answer || "No fue posible generar una respuesta.");
      if (result.ok) renderRows(result);
    } catch (_) {
      addMessage("assistant", "No pude conectar con el asistente. Revisa el servidor e inténtalo nuevamente.");
    } finally {
      submitButton.disabled = false;
      submitButton.innerHTML = '<i class="bi bi-send-fill me-1"></i>Enviar';
      input.focus();
    }
  }

  form.addEventListener("submit", event => { event.preventDefault(); ask(input.value); });
  document.querySelectorAll("[data-bi-question]").forEach(button => {
    button.addEventListener("click", () => ask(button.dataset.biQuestion));
  });
})();
