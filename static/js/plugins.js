import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const PANEL_CLASS = 'plugin-panel-modal';

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
