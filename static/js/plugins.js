import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';
import uiModule from './ui.js';

const PANEL_CLASS = 'plugin-panel-modal';
const BRIDGE_TYPE = 'odysseus:plugin';
const BRIDGE_VERSION = 1;

function modalId(panel) {
  return `plugin-panel-${panel.plugin_id}-${panel.id}`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`Plugin request failed: ${response.status}`);
  }
  return response.json();
}

function createPanelModal(panel) {
  const id = modalId(panel);
  const existing = document.getElementById(id);
  if (existing) return existing;

  const modal = document.createElement('div');
  modal.id = id;
  modal.className = PANEL_CLASS;
  modal.style.width = `${panel.width || 760}px`;
  modal.style.height = `${panel.height || 520}px`;
  modal.style.left = 'calc(50% - 380px)';
  modal.style.top = '96px';
  modal.innerHTML = `
    <div class="plugin-panel-header">
      <div class="plugin-panel-title"></div>
      <div class="plugin-panel-actions">
        <button type="button" class="minimize-btn" aria-label="Minimize plugin panel" title="Minimize">_</button>
        <button type="button" class="plugin-panel-close" aria-label="Close plugin panel" title="Close">×</button>
      </div>
    </div>
    <div class="plugin-panel-frame-wrap">
      <iframe class="plugin-panel-frame" title="" sandbox="allow-scripts allow-forms allow-popups allow-modals" referrerpolicy="no-referrer"></iframe>
    </div>
  `;

  modal.querySelector('.plugin-panel-title').textContent = panel.title || panel.id;
  const iframe = modal.querySelector('iframe');
  iframe.title = panel.title || panel.id;
  iframe.src = panel.iframe_url;
  iframe.dataset.pluginId = panel.plugin_id;
  iframe.dataset.panelId = panel.id;

  modal.querySelector('.plugin-panel-close')?.addEventListener('click', () => {
    Modals.unregister(id);
    modal.remove();
  });

  document.body.appendChild(modal);
  Modals.register(id, {
    label: panel.title || panel.id,
    icon: panel.icon || 'plug',
  });
  makeWindowDraggable(modal, {
    header: modal.querySelector('.plugin-panel-header'),
    content: modal.querySelector('.plugin-panel-frame-wrap'),
  });
  return modal;
}

function findPanelForSource(source) {
  for (const iframe of document.querySelectorAll('.plugin-panel-frame')) {
    if (eventSourceMatches(source, iframe)) {
      return {
        iframe,
        modal: iframe.closest(`.${PANEL_CLASS}`),
        pluginId: iframe.dataset.pluginId,
        panelId: iframe.dataset.panelId,
      };
    }
  }
  return null;
}

function eventSourceMatches(source, iframe) {
  return source && iframe && source === iframe.contentWindow;
}

function postBridgeResponse(iframe, requestId, ok, payload) {
  try {
    iframe.contentWindow?.postMessage({
      type: BRIDGE_TYPE,
      version: BRIDGE_VERSION,
      requestId,
      ok,
      payload,
    }, '*');
  } catch {}
}

async function handlePluginBridgeMessage(event) {
  const data = event.data || {};
  if (!data || data.type !== BRIDGE_TYPE || data.version !== BRIDGE_VERSION) return;

  const panel = findPanelForSource(event.source);
  if (!panel || !panel.iframe || event.source !== panel.iframe.contentWindow) return;

  const { iframe, modal, pluginId } = panel;
  const requestId = data.requestId || null;
  const action = String(data.action || '');
  const payload = data.payload || {};

  try {
    if (action === 'toast') {
      uiModule.showToast(String(payload.message || ''), Number(payload.duration || 3000));
      postBridgeResponse(iframe, requestId, true, { shown: true });
      return;
    }
    if (action === 'resize') {
      const width = Math.max(320, Math.min(1600, Number(payload.width || modal.offsetWidth)));
      const height = Math.max(240, Math.min(1200, Number(payload.height || modal.offsetHeight)));
      modal.style.width = `${width}px`;
      modal.style.height = `${height}px`;
      postBridgeResponse(iframe, requestId, true, { width, height });
      return;
    }
    if (action === 'close') {
      Modals.unregister(modal.id);
      modal.remove();
      postBridgeResponse(iframe, requestId, true, { closed: true });
      return;
    }
    if (action === 'refresh') {
      iframe.src = iframe.src;
      postBridgeResponse(iframe, requestId, true, { refreshed: true });
      return;
    }
    if (action === 'pluginApi') {
      const url = String(payload.url || '');
      if (!url.startsWith(`/api/plugins/${pluginId}/`)) {
        throw new Error('Plugin API bridge calls must stay inside this plugin namespace');
      }
      const method = String(payload.method || 'GET').toUpperCase();
      if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        throw new Error('Unsupported plugin API method');
      }
      const response = await fetch(url, {
        method,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: method === 'GET' ? undefined : JSON.stringify(payload.body || {}),
      });
      const contentType = response.headers.get('content-type') || '';
      const body = contentType.includes('application/json') ? await response.json() : await response.text();
      postBridgeResponse(iframe, requestId, response.ok, {
        status: response.status,
        body,
      });
      return;
    }
    throw new Error(`Unsupported plugin bridge action: ${action}`);
  } catch (err) {
    postBridgeResponse(iframe, requestId, false, {
      error: String(err && err.message || err),
    });
  }
}

window.addEventListener('message', handlePluginBridgeMessage);

export async function refreshPluginPanels() {
  return requestJson('/api/plugins/panels');
}

export async function openPanel(pluginId, panelId) {
  const panels = await refreshPluginPanels();
  const panel = panels.find((item) => item.plugin_id === pluginId && item.id === panelId);
  if (!panel) {
    throw new Error(`Plugin panel not available: ${pluginId}/${panelId}`);
  }
  const modal = createPanelModal(panel);
  modal.classList.add('active');
  modal.style.display = 'block';
  try { Modals.restore(modal.id); } catch {}
  return modal;
}

export async function enablePlugin(pluginId, enabled = true) {
  return requestJson(`/api/plugins/${encodeURIComponent(pluginId)}/enable`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  });
}

window.odysseusPlugins = {
  refreshPluginPanels,
  openPanel,
  enablePlugin,
};
