// Toast Notification System
class NotificationManager {
  constructor() {
    this.container = this.createContainer();
    this.toasts = [];
  }

  createContainer() {
    let container = document.getElementById('notification-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'notification-container';
      container.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 9999;
        pointer-events: none;
      `;
      document.body.appendChild(container);
    }
    return container;
  }

  show(message, type = 'info', duration = 5000) {
    const toast = this.createToast(message, type);
    this.container.appendChild(toast);
    this.toasts.push(toast);

    // Trigger animation
    setTimeout(() => toast.classList.add('toast-show'), 10);

    // Auto remove
    if (duration > 0) {
      setTimeout(() => this.remove(toast), duration);
    }

    return toast;
  }

  createToast(message, type) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.style.cssText = `
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: var(--space-md) var(--space-lg);
      margin-bottom: var(--space-sm);
      box-shadow: var(--shadow-lg);
      backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px);
      color: var(--text-primary);
      font-size: var(--font-size-sm);
      font-family: var(--font-family);
      max-width: 400px;
      min-width: 300px;
      pointer-events: auto;
      transform: translateX(100%);
      opacity: 0;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      position: relative;
    `;

    const icon = this.getIcon(type);
    const content = `
      <div style="display: flex; align-items: flex-start; gap: var(--space-md);">
        <div class="toast-icon" style="flex-shrink: 0; margin-top: 2px;">${icon}</div>
        <div class="toast-content" style="flex: 1; line-height: 1.5;">${message}</div>
        <button class="toast-close" style="
          background: none;
          border: none;
          color: var(--text-muted);
          cursor: pointer;
          padding: 0;
          font-size: 18px;
          line-height: 1;
          margin-left: var(--space-sm);
        " onclick="this.closest('.toast').remove()">×</button>
      </div>
    `;

    toast.innerHTML = content;

    // Add show animation
    toast.classList.add('toast-enter');

    return toast;
  }

  getIcon(type) {
    const icons = {
      success: '✅',
      error: '❌',
      warning: '⚠️',
      info: 'ℹ️'
    };
    return icons[type] || icons.info;
  }

  remove(toast) {
    toast.classList.add('toast-hide');
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
      this.toasts = this.toasts.filter(t => t !== toast);
    }, 300);
  }

  // Convenience methods
  success(message, duration) {
    return this.show(message, 'success', duration);
  }

  error(message, duration) {
    return this.show(message, 'error', duration);
  }

  warning(message, duration) {
    return this.show(message, 'warning', duration);
  }

  info(message, duration) {
    return this.show(message, 'info', duration);
  }
}

// Global notification manager
const notifications = new NotificationManager();

// Add CSS for animations
const style = document.createElement('style');
style.textContent = `
  .toast-enter {
    transform: translateX(100%);
    opacity: 0;
  }

  .toast-show {
    transform: translateX(0);
    opacity: 1;
  }

  .toast-hide {
    transform: translateX(100%);
    opacity: 0;
  }

  .toast-success {
    border-left: 4px solid var(--success);
  }

  .toast-error {
    border-left: 4px solid var(--error);
  }

  .toast-warning {
    border-left: 4px solid var(--warning);
  }

  .toast-info {
    border-left: 4px solid var(--info);
  }

  .toast-close:hover {
    color: var(--text-primary);
  }
`;
document.head.appendChild(style);

// Export for use in other scripts
window.notifications = notifications;