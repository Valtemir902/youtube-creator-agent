'use strict';

(() => {
  const state = {
    serviceWorkerRegistered: false,
    installPromptAvailable: false,
    installedMode: false,
  };
  window.__YCA_PWA__ = state;

  const isStandalone = () => (
    window.matchMedia?.('(display-mode: standalone)').matches === true ||
    window.navigator.standalone === true
  );

  const installHost = () => document.querySelector('.top-actions');

  const ensureInstallButton = () => {
    const host = installHost();
    if (!host) return null;

    let button = document.getElementById('installApp');
    if (button) return button;

    button = document.createElement('button');
    button.type = 'button';
    button.id = 'installApp';
    button.className = 'btn';
    button.textContent = 'Instalar app';
    button.setAttribute('aria-label', 'Instalar Creator Agent como aplicativo');

    const logout = document.getElementById('logout');
    if (logout && logout.parentElement === host) host.insertBefore(button, logout);
    else host.appendChild(button);
    return button;
  };

  let deferredPrompt = null;

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    state.installPromptAvailable = true;
    const button = ensureInstallButton();
    if (!button) return;
    button.hidden = false;
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    state.installPromptAvailable = false;
    state.installedMode = true;
    const button = document.getElementById('installApp');
    if (button) button.remove();
  });

  document.addEventListener('click', async (event) => {
    const button = event.target.closest?.('#installApp');
    if (!button || !deferredPrompt) return;

    button.disabled = true;
    try {
      await deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      if (choice?.outcome === 'accepted') {
        deferredPrompt = null;
        state.installPromptAvailable = false;
        button.remove();
      } else {
        button.disabled = false;
      }
    } catch (error) {
      button.disabled = false;
      console.warn('PWA install prompt failed safely.', error);
    }
  });

  const register = async () => {
    state.installedMode = isStandalone();
    if (state.installedMode) {
      const button = document.getElementById('installApp');
      if (button) button.remove();
    }

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
