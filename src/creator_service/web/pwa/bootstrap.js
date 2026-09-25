'use strict';

(() => {
  const state = {
    serviceWorkerRegistered: false,
    installPromptAvailable: false,
    installedMode: false,
    platform: 'generic',
  };
  window.__YCA_PWA__ = state;

  const isStandalone = () => (
    window.matchMedia?.('(display-mode: standalone)').matches === true ||
    window.navigator.standalone === true
  );

  const detectPlatform = () => {
    const ua = String(window.navigator.userAgent || '').toLowerCase();
    const platform = String(window.navigator.platform || '').toLowerCase();
    const touchMac = platform.includes('mac') && Number(window.navigator.maxTouchPoints || 0) > 1;
    if (/iphone|ipad|ipod/.test(ua) || touchMac) return 'ios';
    if (ua.includes('android')) return 'android';
    return 'generic';
  };

  const removeInstallUI = () => {
    document.getElementById('installApp')?.remove();
    document.getElementById('installAppWrap')?.remove();
    document.getElementById('installFallback')?.remove();
  };

  const fallbackCopy = () => {
    if (state.platform === 'ios') {
      return 'No Safari, toque em Compartilhar (quadrado com seta) e depois em “Adicionar à Tela de Início”.';
    }
    if (state.platform === 'android') {
      return 'No Chrome, abra o menu ⋮ e toque em “Instalar app” ou “Adicionar à tela inicial”.';
    }
    return 'Abra o menu do navegador e procure “Instalar app” ou “Adicionar à tela inicial”.';
  };

  const ensureFallback = () => {
    let modal = document.getElementById('installFallback');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'installFallback';
    modal.className = 'yca-install-fallback';
    modal.hidden = true;
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'installFallbackTitle');
    modal.innerHTML = `
      <div class="yca-install-card">
        <h2 id="installFallbackTitle">Instalar Creator Agent</h2>
        <p id="installFallbackText"></p>
        <button type="button" class="yca-install-close" id="installFallbackClose">Entendi</button>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('#installFallbackText').textContent = fallbackCopy();
    return modal;
  };

  const showFallback = () => {
    const modal = ensureFallback();
    modal.hidden = false;
    modal.querySelector('#installFallbackClose')?.focus();
  };

  const hideFallback = () => {
    const modal = document.getElementById('installFallback');
    if (modal) modal.hidden = true;
  };

  const makeButton = (className, label) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.id = 'installApp';
    button.className = `yca-install-cta ${className}`;
    button.textContent = label;
    button.setAttribute('aria-label', 'Instalar Creator Agent');
    return button;
  };

  const ensureInstallButton = () => {
    if (isStandalone()) {
      state.installedMode = true;
      removeInstallUI();
      return null;
    }

    const existing = document.getElementById('installApp');
    if (existing) return existing;

    if (location.pathname === '/login') {
      const wrap = document.createElement('div');
      wrap.id = 'installAppWrap';
      wrap.className = 'yca-install-login-wrap';
      const button = makeButton('yca-install-login', 'Instalar Creator Agent');
      wrap.appendChild(button);
      document.body.appendChild(wrap);
      return button;
    }

    if (location.pathname === '/dashboard') {
      const button = makeButton('yca-install-dashboard', 'Instalar');
      const host = document.querySelector('.top-actions');
      const logout = document.getElementById('logout');
      if (host) {
        if (logout && logout.parentElement === host) host.insertBefore(button, logout);
        else host.prepend(button);
      } else {
        button.style.position = 'fixed';
        button.style.top = '18px';
        button.style.right = '18px';
        document.body.appendChild(button);
      }
      return button;
    }

    return null;
  };

  let deferredPrompt = null;

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    state.installPromptAvailable = true;
    ensureInstallButton();
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    state.installPromptAvailable = false;
    state.installedMode = true;
    removeInstallUI();
  });

  document.addEventListener('click', async (event) => {
    if (event.target.closest?.('#installFallbackClose') || event.target.id === 'installFallback') {
      hideFallback();
      return;
    }

    const button = event.target.closest?.('#installApp');
    if (!button) return;

    if (!deferredPrompt) {
      showFallback();
      return;
    }

    button.disabled = true;
    try {
      await deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      if (choice?.outcome === 'accepted') {
        deferredPrompt = null;
        state.installPromptAvailable = false;
        removeInstallUI();
      } else {
        button.disabled = false;
      }
    } catch (error) {
      button.disabled = false;
      console.warn('PWA install prompt failed safely.', error);
      showFallback();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') hideFallback();
  });

  const register = async () => {
    state.platform = detectPlatform();
    state.installedMode = isStandalone();
    if (state.installedMode) {
      removeInstallUI();
      window.dispatchEvent(new CustomEvent('yca:pwa-ready'));
      return;
    }

    ensureInstallButton();

    const secureContext = location.protocol === 'https:' || ['localhost', '127.0.0.1'].includes(location.hostname);
    if (!secureContext || !('serviceWorker' in navigator)) {
      window.dispatchEvent(new CustomEvent('yca:pwa-ready'));
      return;
    }

    try {
      const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      await navigator.serviceWorker.ready;
      state.serviceWorkerRegistered = Boolean(registration);
      registration.update().catch(() => {});
    } catch (error) {
      console.warn('PWA service worker registration failed safely.', error);
    } finally {
      window.dispatchEvent(new CustomEvent('yca:pwa-ready'));
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', register, { once: true });
  } else {
    register();
  }
})();
