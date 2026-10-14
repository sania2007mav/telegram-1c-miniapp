const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const statusEl = document.getElementById("status");
const basesEl = document.getElementById("bases");
const basesSection = document.getElementById("bases-section");
const moneySection = document.getElementById("money-section");
const moneyTitle = document.getElementById("money-title");
const freeTotalEl = document.getElementById("free-total");
const allocatedTotalEl = document.getElementById("allocated-total");
const unallocatedEl = document.getElementById("unallocated");
const moneyNoteEl = document.getElementById("money-note");
const accountsEl = document.getElementById("accounts");
const fundsEl = document.getElementById("funds");
const presetsEl = document.getElementById("presets");

let selectedBaseId = null;
let presets = [];

function initData() {
  return tg?.initData || "";
}

function money(n) {
  const v = Number(n) || 0;
  return v.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": initData(),
    ...(options.headers || {}),
  };
  const res = await fetch(`/api${path}`, { ...options, headers });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail = data.detail;
    const msg = typeof detail === "string" ? detail : JSON.stringify(detail || data);
    throw new Error(msg || res.statusText || "API error");
  }
  return data;
}

function setStatus(text, isError = false) {
  statusEl.innerHTML = isError ? `<span class="err">${text}</span>` : text;
}

async function loadPresets() {
  const data = await api("/fund-presets");
  presets = data.items || [];
  presetsEl.innerHTML = "";
  for (const p of presets) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.textContent = p.name;
    btn.title = p.hint || "";
    btn.addEventListener("click", () => {
      document.getElementById("fund-name").value = p.name;
      document.getElementById("fund-note").value = p.hint || "";
    });
    presetsEl.appendChild(btn);
  }
}

async function loadBases() {
  const data = await api("/bases");
  basesEl.innerHTML = "";
  for (const b of data.items) {
    const row = document.createElement("div");
    row.className = "item" + (selectedBaseId === b.id ? " active" : "");
    row.innerHTML = `<div><strong>${b.name}</strong><div class="muted small">#${b.id}${b.is_owner ? " · owner" : " · shared"}</div></div>`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Открыть";
    btn.addEventListener("click", () => openBase(b.id, b.name));
    row.appendChild(btn);
    basesEl.appendChild(row);
  }
  basesSection.hidden = false;
  if (!selectedBaseId && data.items.length === 1) {
    await openBase(data.items[0].id, data.items[0].name);
  }
}

async function openBase(baseId, name) {
  selectedBaseId = baseId;
  moneyTitle.textContent = name || `База #${baseId}`;
  moneySection.hidden = false;
  setStatus("Загрузка денег из 1С…");
  await loadMoney();
  await loadBases();
}

async function loadMoney() {
  if (!selectedBaseId) return;
  const data = await api(`/bases/${selectedBaseId}/money`);
  freeTotalEl.textContent = money(data.free_total);
  allocatedTotalEl.textContent = money(data.allocated_total);
  unallocatedEl.textContent = money(data.unallocated);
  moneyNoteEl.textContent = data.currency_note || "";

  accountsEl.innerHTML = "";
  for (const a of [...(data.cash || []), ...(data.bank || [])]) {
    const row = document.createElement("div");
    row.className = "item";
    const kind = a.kind === "cash" ? "Касса" : "Счёт";
    row.innerHTML = `<div><strong>${a.name}</strong><div class="muted small">${kind}</div></div><div><strong>${money(a.amount)}</strong></div>`;
    accountsEl.appendChild(row);
  }

  fundsEl.innerHTML = "";
  if (!(data.funds || []).length) {
    fundsEl.innerHTML = `<div class="muted small">Фондов пока нет — создайте из подсказок ниже.</div>`;
  }
  for (const f of data.funds || []) {
    const row = document.createElement("div");
    row.className = "item";
    row.innerHTML = `<div><strong>${f.name}</strong><div class="muted small">${f.note || ""}</div></div>`;
    const right = document.createElement("div");
    right.style.textAlign = "right";
    right.innerHTML = `<div><strong>${money(f.amount)}</strong></div>`;
    const del = document.createElement("button");
    del.type = "button";
    del.className = "ghost";
    del.textContent = "Удалить";
    del.addEventListener("click", async () => {
      if (!confirm(`Удалить фонд «${f.name}»?`)) return;
      try {
        await api(`/bases/${selectedBaseId}/funds/${f.id}`, { method: "DELETE" });
        await loadMoney();
        setStatus("Фонд удалён");
      } catch (err) {
        setStatus(err.message, true);
      }
    });
    right.appendChild(del);
    row.appendChild(right);
    fundsEl.appendChild(row);
  }
  setStatus(`База #${selectedBaseId}`);
}

document.getElementById("btn-refresh").addEventListener("click", async () => {
  try {
    setStatus("Обновление…");
    await loadMoney();
  } catch (err) {
    setStatus(err.message, true);
  }
});

document.getElementById("base-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  setStatus("Проверка OData…");
  try {
    const name = String(fd.get("name") || "");
    const created = await api("/bases", {
      method: "POST",
      body: JSON.stringify({
        name,
        odata_url: fd.get("odata_url"),
        login: fd.get("login"),
        password: fd.get("password"),
      }),
    });
    e.target.reset();
    setStatus("База сохранена");
    await loadBases();
    await openBase(created.id, name);
  } catch (err) {
    setStatus(err.message, true);
  }
});

document.getElementById("acl-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  setStatus("Добавление доступа…");
  try {
    const baseId = fd.get("base_id");
    await api(`/bases/${baseId}/access`, {
      method: "POST",
      body: JSON.stringify({ phone: fd.get("phone") }),
    });
    setStatus("Телефон добавлен в ACL");
  } catch (err) {
    setStatus(err.message, true);
  }
});

document.getElementById("fund-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!selectedBaseId) {
    setStatus("Сначала откройте базу", true);
    return;
  }
  const fd = new FormData(e.target);
  setStatus("Создание фонда…");
  try {
    await api(`/bases/${selectedBaseId}/funds`, {
      method: "POST",
      body: JSON.stringify({
        name: fd.get("name"),
        amount: Number(fd.get("amount") || 0),
        note: fd.get("note") || "",
      }),
    });
    e.target.reset();
    await loadMoney();
    setStatus("Фонд создан");
  } catch (err) {
    setStatus(err.message, true);
  }
});

(async () => {
  try {
    if (!initData()) {
      setStatus("Откройте из Telegram-бота (нужен initData)", true);
      return;
    }
    const me = await api("/me");
    setStatus(`Телефон: ${me.phone}`);
    await loadPresets();
    await loadBases();
  } catch (err) {
    setStatus(err.message, true);
  }
})();
