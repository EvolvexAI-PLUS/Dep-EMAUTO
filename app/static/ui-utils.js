/**
 * Universal UI Utilities
 * Skeleton Screens & Offcanvas Management
 */

class SkeletonManager {
  constructor() {
    this.skeletons = new Map();
    this.init();
  }

  init() {
    // Auto-initialize all skeleton elements
    document.querySelectorAll('[data-skeleton]').forEach(element => {
      const skeletonId = element.dataset.skeleton;
      const contentPromise = this.getContentPromise(element);
      this.createSkeleton(skeletonId, element, contentPromise);
    });
  }

  createSkeleton(type, container, contentPromise = null) {
    const skeletonHTML = this.getSkeletonHTML(type);
    container.innerHTML = skeletonHTML;
    this.skeletons.set(container, { type, contentPromise });

    if (contentPromise) {
      this.loadContent(container, contentPromise);
    }
  }

  async loadContent(container, contentPromise) {
    try {
      const content = await contentPromise;
      this.showContent(container, content);
    } catch (error) {
      console.error('Failed to load content:', error);
      this.showError(container);
    }
  }

  showContent(container, content) {
    container.innerHTML = content;
    container.classList.add('skeleton-loaded');
  }

  showError(container) {
    const errorHTML = `
      <div class="skeleton-error">
        <div class="error-icon">⚠️</div>
        <div class="error-message">Failed to load content</div>
        <button class="error-retry" onclick="window.location.reload()">Retry</button>
      </div>
    `;
    container.innerHTML = errorHTML;
  }

  getContentPromise(container) {
    // Default implementation - override in specific pages
    return new Promise(resolve => setTimeout(() => resolve('<div>Content loaded</div>'), 1000));
  }

  getSkeletonHTML(type) {
    const templates = {
      emailList: this.getEmailListSkeleton(),
      emailCard: this.getEmailCardSkeleton(),
      dashboard: this.getDashboardSkeleton(),
      sidebar: this.getSidebarSkeleton(),
      table: this.getTableSkeleton(),
      form: this.getFormSkeleton()
    };
    return templates[type] || '<div class="skeleton skeleton-text long"></div>';
  }

  getEmailListSkeleton() {
    return `
      <div class="skeleton-email-list">
        ${Array(5).fill().map(() => `
          <div class="skeleton-email-item">
            <div class="skeleton skeleton-email-checkbox"></div>
            <div class="skeleton-email-content">
              <div class="skeleton skeleton-email-subject"></div>
              <div class="skeleton skeleton-email-preview"></div>
              <div class="skeleton-email-meta">
                <div class="skeleton skeleton-email-date"></div>
                <div class="skeleton skeleton-email-status"></div>
              </div>
            </div>
            <div class="skeleton-email-actions">
              <div class="skeleton skeleton-button"></div>
              <div class="skeleton skeleton-button"></div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  }

  getEmailCardSkeleton() {
    return `
      <div class="skeleton-card">
        <div class="skeleton-card-header">
          <div class="skeleton skeleton-avatar"></div>
          <div class="skeleton-email-content">
            <div class="skeleton skeleton-title"></div>
            <div class="skeleton skeleton-text medium"></div>
          </div>
        </div>
        <div class="skeleton-card-content">
          <div class="skeleton skeleton-text long"></div>
          <div class="skeleton skeleton-text short"></div>
          <div class="skeleton skeleton-text medium"></div>
        </div>
      </div>
    `;
  }

  getDashboardSkeleton() {
    return `
      <div class="skeleton-dashboard">
        <div class="skeleton-dashboard-header">
          <div class="skeleton skeleton-title"></div>
          <div class="skeleton-dashboard-actions">
            <div class="skeleton skeleton-button"></div>
            <div class="skeleton skeleton-button"></div>
          </div>
        </div>
        <div class="skeleton-dashboard-metrics">
          ${Array(4).fill().map(() => `
            <div class="skeleton-metric-card">
              <div class="skeleton skeleton-metric-value"></div>
              <div class="skeleton skeleton-metric-label"></div>
            </div>
          `).join('')}
        </div>
        <div class="skeleton-dashboard-content">
          <div class="skeleton skeleton-text xl"></div>
          <div class="skeleton skeleton-text long"></div>
        </div>
      </div>
    `;
  }

  getSidebarSkeleton() {
    return `
      <div class="skeleton-sidebar">
        <div class="skeleton-sidebar-user">
          <div class="skeleton skeleton-avatar"></div>
          <div class="skeleton-user-info">
            <div class="skeleton skeleton-text short"></div>
            <div class="skeleton skeleton-text medium"></div>
          </div>
        </div>
        ${Array(6).fill().map(() => `
          <div class="skeleton-sidebar-item">
            <div class="skeleton skeleton-sidebar-icon"></div>
            <div class="skeleton skeleton-sidebar-label"></div>
          </div>
        `).join('')}
      </div>
    `;
  }

  getTableSkeleton() {
    return `
      <div class="skeleton-table-container">
        <table class="skeleton-table">
          <thead class="skeleton-table-header">
            <tr>
              <th><div class="skeleton skeleton-text short"></div></th>
              <th><div class="skeleton skeleton-text medium"></div></th>
              <th><div class="skeleton skeleton-text short"></div></th>
              <th><div class="skeleton skeleton-text medium"></div></th>
            </tr>
          </thead>
          <tbody>
            ${Array(8).fill().map(() => `
              <tr>
                <td><div class="skeleton skeleton-text short"></div></td>
                <td><div class="skeleton skeleton-text long"></div></td>
                <td><div class="skeleton skeleton-status-badge"></div></td>
                <td><div class="skeleton skeleton-text medium"></div></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  getFormSkeleton() {
    return `
      <div class="skeleton-form">
        <div class="skeleton-form-group">
          <div class="skeleton skeleton-form-label"></div>
          <div class="skeleton skeleton-form-input"></div>
        </div>
        <div class="skeleton-form-group">
          <div class="skeleton skeleton-form-label"></div>
          <div class="skeleton skeleton-form-input"></div>
        </div>
        <div class="skeleton-form-group">
          <div class="skeleton skeleton-form-label"></div>
          <div class="skeleton skeleton-form-textarea"></div>
        </div>
        <div class="skeleton-form-actions">
          <div class="skeleton skeleton-button"></div>
          <div class="skeleton skeleton-button"></div>
        </div>
      </div>
    `;
  }
}

class OffcanvasManager {
  constructor(options = {}) {
    this.options = {
      selector: '.offcanvas',
      overlaySelector: '.offcanvas-overlay',
      hamburgerSelector: '.hamburger-btn',
      closeSelector: '.offcanvas-close',
      ...options
    };

    this.offcanvas = null;
    this.overlay = null;
    this.hamburgerBtn = null;
    this.closeBtn = null;
    this.isOpen = false;

    this.init();
  }

  init() {
    this.offcanvas = document.querySelector(this.options.selector);
    this.overlay = document.querySelector(this.options.overlaySelector);
    this.hamburgerBtn = document.querySelector(this.options.hamburgerSelector);
    this.closeBtn = document.querySelector(this.options.closeSelector);

    if (!this.offcanvas) return;

    this.bindEvents();
    this.initSwipeGesture();
  }

  bindEvents() {
    // Hamburger button
    if (this.hamburgerBtn) {
      this.hamburgerBtn.addEventListener('click', () => this.toggle());
    }

    // Close button
    if (this.closeBtn) {
      this.closeBtn.addEventListener('click', () => this.close());
    }

    // Overlay click
    if (this.overlay) {
      this.overlay.addEventListener('click', () => this.close());
    }

    // Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.isOpen) {
        this.close();
      }
    });
  }

  initSwipeGesture() {
    if (!this.offcanvas) return;

    let startX = 0;
    let currentX = 0;
    let isDragging = false;

    document.addEventListener('touchstart', (e) => {
      startX = e.touches[0].clientX;
      isDragging = true;
    }, { passive: true });

    document.addEventListener('touchmove', (e) => {
      if (!isDragging) return;
      currentX = e.touches[0].clientX;
      const diff = currentX - startX;

      // Swipe from left edge to open
      if (diff > 50 && startX < 20 && !this.isOpen) {
        this.open();
        isDragging = false;
      }
      // Swipe right to left to close
      else if (diff < -50 && this.isOpen) {
        this.close();
        isDragging = false;
      }
    }, { passive: true });

    document.addEventListener('touchend', () => {
      isDragging = false;
    }, { passive: true });
  }

  open() {
    if (!this.offcanvas || this.isOpen) return;

    this.isOpen = true;
    this.offcanvas.classList.add('open');
    this.offcanvas.classList.remove('closing');

    if (this.overlay) {
      this.overlay.classList.add('open');
      this.overlay.classList.remove('closing');
    }

    if (this.hamburgerBtn) {
      this.hamburgerBtn.classList.add('open');
    }

    document.body.style.overflow = 'hidden';
    this.onOpen();
  }

  close() {
    if (!this.offcanvas || !this.isOpen) return;

    this.isOpen = false;
    this.offcanvas.classList.add('closing');
    this.offcanvas.classList.remove('open');

    if (this.overlay) {
      this.overlay.classList.add('closing');
      this.overlay.classList.remove('open');
    }

    if (this.hamburgerBtn) {
      this.hamburgerBtn.classList.remove('open');
    }

    document.body.style.overflow = '';

    // Remove closing class after animation
    setTimeout(() => {
      this.offcanvas.classList.remove('closing');
      if (this.overlay) {
        this.overlay.classList.remove('closing');
      }
    }, 300);

    this.onClose();
  }

  toggle() {
    if (this.isOpen) {
      this.close();
    } else {
      this.open();
    }
  }

  onOpen() {
    // Override in subclasses
    this.triggerEvent('offcanvas:open');
  }

  onClose() {
    // Override in subclasses
    this.triggerEvent('offcanvas:close');
  }

  triggerEvent(eventName, data = {}) {
    const event = new CustomEvent(eventName, { detail: data });
    document.dispatchEvent(event);
  }
}

class LoadingManager {
  constructor() {
    this.loadingElements = new Map();
  }

  showLoading(element, type = 'spinner') {
    const loadingHTML = this.getLoadingHTML(type);
    element.innerHTML = loadingHTML;
    element.classList.add('loading');
    this.loadingElements.set(element, type);
  }

  hideLoading(element) {
    element.classList.remove('loading');
    this.loadingElements.delete(element);
  }

  getLoadingHTML(type) {
    const templates = {
      spinner: `
        <div class="loading-spinner">
          <div class="loading-spinner-circle"></div>
        </div>
      `,
      dots: `
        <div class="loading-dots">
          <div class="loading-dot"></div>
          <div class="loading-dot"></div>
          <div class="loading-dot"></div>
        </div>
      `,
      pulse: `
        <div class="loading-pulse">
          <div class="loading-pulse-bar"></div>
        </div>
      `,
      skeleton: `
        <div class="skeleton-loading-overlay">
          <div class="skeleton-loading-spinner"></div>
        </div>
      `
    };
    return templates[type] || templates.spinner;
  }

  async withLoading(element, promise, type = 'spinner') {
    this.showLoading(element, type);
    try {
      const result = await promise;
      this.hideLoading(element);
      return result;
    } catch (error) {
      this.hideLoading(element);
      throw error;
    }
  }
}

// Utility functions
const UIUtils = {
  // Debounce function for performance
  debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  },

  // Throttle function for performance
  throttle(func, limit) {
    let inThrottle;
    return function() {
      const args = arguments;
      const context = this;
      if (!inThrottle) {
        func.apply(context, args);
        inThrottle = true;
        setTimeout(() => inThrottle = false, limit);
      }
    };
  },

  // Check if element is in viewport
  isInViewport(element) {
    const rect = element.getBoundingClientRect();
    return (
      rect.top >= 0 &&
      rect.left >= 0 &&
      rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
      rect.right <= (window.innerWidth || document.documentElement.clientWidth)
    );
  },

  // Smooth scroll to element
  scrollTo(element, offset = 0) {
    const elementTop = element.getBoundingClientRect().top + window.pageYOffset;
    window.scrollTo({
      top: elementTop - offset,
      behavior: 'smooth'
    });
  },

  // Copy to clipboard
  async copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      // Fallback for older browsers
      const textArea = document.createElement('textarea');
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      try {
        document.execCommand('copy');
        return true;
      } catch (err) {
        return false;
      } finally {
        document.body.removeChild(textArea);
      }
    }
  },

  // Show toast notification
  showToast(message, type = 'info', duration = 3000) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    // Add to DOM
    const container = document.querySelector('.toast-container') ||
                     this.createToastContainer();
    container.appendChild(toast);

    // Auto remove
    setTimeout(() => {
      toast.classList.add('toast-hide');
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 300);
    }, duration);
  },

  createToastContainer() {
    const container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
  }
};

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  // Initialize global instances
  window.skeletonManager = new SkeletonManager();
  window.offcanvasManager = new OffcanvasManager();
  window.loadingManager = new LoadingManager();
  window.uiUtils = UIUtils;

  // Auto-initialize components with data attributes
  document.querySelectorAll('[data-offcanvas]').forEach(element => {
    const options = element.dataset.offcanvas ? JSON.parse(element.dataset.offcanvas) : {};
    new OffcanvasManager({ ...options, triggerElement: element });
  });

  document.querySelectorAll('[data-loading]').forEach(element => {
    const type = element.dataset.loading || 'spinner';
    window.loadingManager.showLoading(element, type);
  });
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { SkeletonManager, OffcanvasManager, LoadingManager, UIUtils };
}