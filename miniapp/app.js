const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const statusEl = document.getElementById("status");
const basesEl = document.getElementById("bases");
const basesSection = document.getElementById("bases-section");
const ownerSection = document.getElementById("owner-section");

function initData() {
  return tg?.initData || "";
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
    throw new Error(data.detail || res.statusText || "API error");
  }
  return data;
}

async function loadBases() {
  const data = await api("/bases");
  basesEl.innerHTML = "";
  for (const b of data.items) {
    const li = document.createElement("li");
    li.textContent = `${b.name} (#${b.id})${b.is_owner ? " — owner" : " — shared"}`;
    basesEl.appendChild(li);
  }
  basesSection.hidden = false;
  ownerSection.hidden = false;
}

document.getElementById("base-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  statusEl.textContent = "Проверка OData…";
  try {
    await api("/bases", {
      method: "POST",
      body: JSON.stringify({
        name: fd.get("name"),
        odata_url: fd.get("odata_url"),
        login: fd.get("login"),
        password: fd.get("password"),
      }),
    });
    e.target.reset();
    statusEl.textContent = "База сохранена";
    await loadBases();
  } catch (err) {
    statusEl.innerHTML = `<span class="err">${err.message}</span>`;
  }
});

document.getElementById("acl-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  statusEl.textContent = "Добавление доступа…";
  try {
    const baseId = fd.get("base_id");
    await api(`/bases/${baseId}/access`, {
      method: "POST",
      body: JSON.stringify({ phone: fd.get("phone") }),
    });
    statusEl.textContent = "Телефон добавлен в ACL";
  } catch (err) {
    statusEl.innerHTML = `<span class="err">${err.message}</span>`;
  }
});

(async () => {
  try {
    if (!initData()) {
      statusEl.innerHTML =
        '<span class="err">Откройте из Telegram-бота (нужен initData)</span>';
      return;
    }
    const me = await api("/me");
    statusEl.textContent = `Телефон: ${me.phone}`;
    await loadBases();
  } catch (err) {
    statusEl.innerHTML = `<span class="err">${err.message}</span>`;
  }
})();
