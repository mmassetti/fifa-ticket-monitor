// ==UserScript==
// @name         FIFA Resale Network Probe
// @namespace    fifa-ticket-monitor
// @version      0.1.0
// @description  Capture seatmap/network responses in the real resale browser session.
// @match        https://fwc26-resale-usd.tickets.fifa.com/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

(function () {
  "use strict";

  const STORAGE_KEY = "fifa_resale_network_probe_v1";
  const INTERESTING_TOKENS = [
    "/tnwr/",
    "seatmap",
    "availability",
    "config",
    "selection/event/submit",
    "csrf/acquire",
    "shoppingCart",
    "quickbooking",
  ];

  function nowIso() {
    return new Date().toISOString();
  }

  function isInteresting(url) {
    const lowered = String(url || "").toLowerCase();
    return INTERESTING_TOKENS.some((token) => lowered.includes(token.toLowerCase()));
  }

  function loadStore() {
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      return value ? JSON.parse(value) : { entries: [] };
    } catch (_) {
      return { entries: [] };
    }
  }

  function saveStore(store) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  }

  function pushEntry(entry) {
    const store = loadStore();
    store.entries.push(entry);
    store.entries = store.entries.slice(-50);
    saveStore(store);
    window.__fifaResaleProbeStore = store;
    window.dispatchEvent(new CustomEvent("fifa-resale-probe-update"));
  }

  async function captureResponse(meta, response) {
    const headers = {};
    try {
      response.headers.forEach((value, key) => {
        headers[key] = value;
      });
    } catch (_) {}

    let bodyText = "";
    try {
      bodyText = await response.clone().text();
    } catch (_) {
      bodyText = "<unreadable>";
    }

    pushEntry({
      ...meta,
      capturedAt: nowIso(),
      status: response.status,
      ok: response.ok,
      responseHeaders: headers,
      bodyPreview: bodyText.slice(0, 10000),
    });
  }

  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const request = args[0];
    const url = typeof request === "string" ? request : request?.url;
    const method = (args[1] && args[1].method) || request?.method || "GET";
    const body = args[1]?.body || null;
    const response = await originalFetch.apply(this, args);
    if (isInteresting(url)) {
      captureResponse({ kind: "fetch", url, method, requestBody: typeof body === "string" ? body.slice(0, 5000) : null }, response);
    }
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__probeMeta = { method, url };
    return originalOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.send = function (body) {
    const meta = this.__probeMeta || {};
    this.addEventListener("loadend", function () {
      if (!isInteresting(meta.url)) return;
      const headersRaw = this.getAllResponseHeaders() || "";
      const headers = {};
      headersRaw.trim().split(/\r?\n/).forEach((line) => {
        const idx = line.indexOf(":");
        if (idx > -1) headers[line.slice(0, idx).trim().toLowerCase()] = line.slice(idx + 1).trim();
      });
      pushEntry({
        kind: "xhr",
        url: meta.url,
        method: meta.method || "GET",
        requestBody: typeof body === "string" ? body.slice(0, 5000) : null,
        capturedAt: nowIso(),
        status: this.status,
        ok: this.status >= 200 && this.status < 300,
        responseHeaders: headers,
        bodyPreview: String(this.responseText || "").slice(0, 10000),
      });
    });
    return originalSend.call(this, body);
  };

  function installPanel() {
    const existing = document.getElementById("fifa-resale-network-probe");
    if (existing) return existing;

    const panel = document.createElement("div");
    panel.id = "fifa-resale-network-probe";
    panel.style.position = "fixed";
    panel.style.left = "16px";
    panel.style.bottom = "16px";
    panel.style.zIndex = "999999";
    panel.style.width = "420px";
    panel.style.maxHeight = "45vh";
    panel.style.overflow = "auto";
    panel.style.padding = "12px";
    panel.style.background = "rgba(15, 15, 15, 0.95)";
    panel.style.color = "#f5f5f5";
    panel.style.border = "1px solid rgba(255,255,255,0.15)";
    panel.style.borderRadius = "12px";
    panel.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, monospace";
    panel.style.fontSize = "12px";
    panel.style.lineHeight = "1.35";
    panel.style.boxShadow = "0 10px 30px rgba(0,0,0,0.35)";
    document.body.appendChild(panel);
    return panel;
  }

  function renderPanel() {
    const panel = installPanel();
    const store = loadStore();
    const entries = store.entries || [];
    const latest = entries.slice(-6).reverse();
    panel.innerHTML = `
      <div style="font-weight:700;margin-bottom:8px">FIFA Resale Network Probe</div>
      <div>captured: ${entries.length}</div>
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
        <button id="probe-copy" style="background:#2d6cdf;color:#fff;border:0;border-radius:6px;padding:6px 8px;cursor:pointer">Copy JSON</button>
        <button id="probe-clear" style="background:#444;color:#fff;border:0;border-radius:6px;padding:6px 8px;cursor:pointer">Clear</button>
      </div>
      <div style="margin-top:8px;font-weight:700">latest</div>
      ${latest.map((entry) => `<div style="margin-top:6px;color:${entry.ok ? '#41d17d' : '#f87171'}">${entry.kind.toUpperCase()} ${entry.status} ${String(entry.method || 'GET')} ${String(entry.url || '').slice(0, 120)}</div>`).join("") || '<div style="margin-top:6px;color:#aaa">no captured requests yet</div>'}
    `;

    const copyButton = panel.querySelector("#probe-copy");
    const clearButton = panel.querySelector("#probe-clear");

    if (copyButton) {
      copyButton.onclick = () => {
        const payload = JSON.stringify(store, null, 2);
        if (navigator.clipboard?.writeText) {
          navigator.clipboard.writeText(payload).catch(() => {});
        }
        console.log("[resale-probe] store", store);
      };
    }

    if (clearButton) {
      clearButton.onclick = () => {
        saveStore({ entries: [] });
        renderPanel();
      };
    }
  }

  window.addEventListener("fifa-resale-probe-update", renderPanel);
  window.addEventListener("load", () => setTimeout(renderPanel, 1500));
  window.__fifaResaleProbeStore = loadStore();
})();
