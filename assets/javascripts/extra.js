// Custom JavaScript for MCP Mesh documentation

// =============================================================================
// Runtime Toggle - Python/TypeScript SDK Switcher
// =============================================================================

(function() {
  const STORAGE_KEY = 'mcp-mesh-runtime';
  const RUNTIMES = {
    python: { label: 'Python', icon: '🐍', navId: 'python-sdk' },
    typescript: { label: 'TypeScript', icon: '📘', navId: 'typescript-sdk' }
  };

  // Module-scoped flag to prevent duplicate document click listeners
  let documentClickListenerAdded = false;

  // Named handler for closing dropdown on outside click
  function onDocumentClick() {
    const toggle = document.getElementById('runtime-toggle');
    if (toggle) {
      toggle.classList.remove('open');
    }
  }

  // Page mappings between Python and TypeScript equivalents
  // Note: paths should NOT include 'index' - just the directory path
  const PAGE_MAPPINGS = {
    // Python -> TypeScript
    'python': 'typescript',
    'python/getting-started': 'typescript/getting-started',
    'python/getting-started/prerequisites': 'typescript/getting-started/prerequisites',
    'python/getting-started/installation': 'typescript/getting-started/installation',
    'python/getting-started/hello-world': 'typescript/getting-started/hello-world',
    'python/decorators': 'typescript/mesh-functions',
    'python/dependency-injection': 'typescript/dependency-injection',
    'python/capabilities-tags': 'typescript/capabilities-tags',
    'python/llm': 'typescript/llm',
    'python/llm/llm-agents': 'typescript/llm/llm-agents',
    'python/llm/llm-providers': 'typescript/llm/llm-providers',
    'python/llm/prompt-templates': 'typescript/llm/prompt-templates',
    'python/fastapi-integration': 'typescript/express-integration',
    'python/examples': 'typescript/examples',
  };

  // Build reverse mappings (TypeScript -> Python)
  const REVERSE_MAPPINGS = {};
  for (const [py, ts] of Object.entries(PAGE_MAPPINGS)) {
    REVERSE_MAPPINGS[ts] = py;
  }

  function getStoredRuntime() {
    return localStorage.getItem(STORAGE_KEY) || 'python';
  }

  function setStoredRuntime(runtime) {
    localStorage.setItem(STORAGE_KEY, runtime);
  }

  function getCurrentPagePath() {
    // Extract path without domain and trailing slash/index.html
    const path = window.location.pathname
      .replace(/\/$/, '')
      .replace(/\/index\.html$/, '')
      .replace(/\.html$/, '');

    // Try to find runtime path segments (python or typescript)
    // This handles cases with or without base path (e.g., /mcp-mesh/python/ or /python/)
    const pythonMatch = path.match(/\/(python(?:\/.*)?)?$/);
    const tsMatch = path.match(/\/(typescript(?:\/.*)?)?$/);

    if (pythonMatch && pythonMatch[1]) {
      return pythonMatch[1];
    }
    if (tsMatch && tsMatch[1]) {
      return tsMatch[1];
    }

    // Fallback: Remove base path if present (e.g., /mcp-mesh/)
    const basePath = document.querySelector('base')?.href || '';
    if (basePath) {
      const basePathname = new URL(basePath, window.location.origin).pathname.replace(/\/$/, '');
      return path.replace(basePathname, '').replace(/^\//, '');
    }

    // Last resort: return path without leading slash
    return path.replace(/^\//, '');
  }

  function isRuntimePage(path) {
    return path === 'python' || path.startsWith('python/') ||
           path === 'typescript' || path.startsWith('typescript/');
  }

  function getEquivalentPage(currentPath, targetRuntime) {
    if (targetRuntime === 'typescript' && PAGE_MAPPINGS[currentPath]) {
      return PAGE_MAPPINGS[currentPath];
    }
    if (targetRuntime === 'python' && REVERSE_MAPPINGS[currentPath]) {
      return REVERSE_MAPPINGS[currentPath];
    }
    return null;
  }

  function navigateToRuntime(runtime) {
    const currentPath = getCurrentPagePath();
    const equivalentPage = getEquivalentPage(currentPath, runtime);

    if (equivalentPage) {
      // Navigate to equivalent page
      // Detect base path from current URL (everything before /python/ or /typescript/)
      const pathname = window.location.pathname;
      const runtimeMatch = pathname.match(/^(.*?)\/(python|typescript)(\/|$)/);
      const basePath = runtimeMatch ? runtimeMatch[1] + '/' : '/';

      window.location.href = basePath + equivalentPage + '/';
    } else {
      // Just save preference and update UI
      setStoredRuntime(runtime);
      updateNavVisibility(runtime);
      updateToggleUI(runtime);
    }
  }

  function updateNavVisibility(runtime) {
    // Show/hide nav sections based on runtime preference
    const navItems = document.querySelectorAll('.md-nav__item');

    navItems.forEach(item => {
      const link = item.querySelector('.md-nav__link');
      if (!link) return;

      const href = link.getAttribute('href') || '';
      const text = link.textContent?.toLowerCase() || '';

      // Check if this is a Python or TypeScript SDK nav item
      if (text.includes('python sdk') || href.includes('/python/')) {
        item.style.display = runtime === 'python' ? '' : 'none';
        item.dataset.runtime = 'python';
      } else if (text.includes('typescript sdk') || href.includes('/typescript/')) {
        item.style.display = runtime === 'typescript' ? '' : 'none';
        item.dataset.runtime = 'typescript';
      }
    });
  }

  function updateToggleUI(runtime) {
    const toggle = document.getElementById('runtime-toggle');
    if (!toggle) return;

    const btn = toggle.querySelector('.runtime-toggle-btn');
    const dropdown = toggle.querySelector('.runtime-toggle-dropdown');

    if (btn) {
      const config = RUNTIMES[runtime];
      btn.innerHTML = `${config.icon} ${config.label} <span class="runtime-toggle-arrow">▾</span>`;
    }

    // Update active state in dropdown
    if (dropdown) {
      dropdown.querySelectorAll('.runtime-option').forEach(opt => {
        opt.classList.toggle('active', opt.dataset.runtime === runtime);
      });
    }
  }

  function createToggleWidget() {
    const runtime = getStoredRuntime();
    const config = RUNTIMES[runtime];

    const toggle = document.createElement('div');
    toggle.id = 'runtime-toggle';
    toggle.className = 'runtime-toggle';
    toggle.innerHTML = `
      <button class="runtime-toggle-btn" aria-label="Select runtime">
        ${config.icon} ${config.label} <span class="runtime-toggle-arrow">▾</span>
      </button>
      <div class="runtime-toggle-dropdown">
        <button class="runtime-option ${runtime === 'python' ? 'active' : ''}" data-runtime="python">
          🐍 Python
        </button>
        <button class="runtime-option ${runtime === 'typescript' ? 'active' : ''}" data-runtime="typescript">
          📘 TypeScript
        </button>
      </div>
    `;

    // Event handlers
    const btn = toggle.querySelector('.runtime-toggle-btn');
    const dropdown = toggle.querySelector('.runtime-toggle-dropdown');

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggle.classList.toggle('open');
    });

    dropdown.querySelectorAll('.runtime-option').forEach(opt => {
      opt.addEventListener('click', (e) => {
        e.stopPropagation();
        const newRuntime = opt.dataset.runtime;
        setStoredRuntime(newRuntime);
        toggle.classList.remove('open');
        navigateToRuntime(newRuntime);
      });
    });

    // Register document click listener once to close dropdown when clicking outside
    if (!documentClickListenerAdded) {
      document.addEventListener('click', onDocumentClick);
      documentClickListenerAdded = true;
    }

    return toggle;
  }

  function insertToggleWidget() {
    // Insert into header
    const header = document.querySelector('.md-header__inner');
    if (!header) return;

    // Check if already inserted
    if (document.getElementById('runtime-toggle')) return;

    // Only show toggle on runtime-specific pages (python/* or typescript/*)
    const currentPath = getCurrentPagePath();
    if (!isRuntimePage(currentPath)) {
      return; // Don't show toggle on non-runtime pages
    }

    const toggle = createToggleWidget();

    // Insert after the header title
    const title = header.querySelector('.md-header__title');
    if (title) {
      title.insertAdjacentElement('afterend', toggle);
    } else {
      header.appendChild(toggle);
    }
  }

  function init() {
    const runtime = getStoredRuntime();

    // Insert toggle widget
    insertToggleWidget();

    // Update nav visibility based on stored preference
    updateNavVisibility(runtime);

    // If on a runtime page, ensure correct runtime is set
    const currentPath = getCurrentPagePath();
    if (currentPath === 'python' || currentPath.startsWith('python/')) {
      setStoredRuntime('python');
      updateNavVisibility('python');
      updateToggleUI('python');
    } else if (currentPath === 'typescript' || currentPath.startsWith('typescript/')) {
      setStoredRuntime('typescript');
      updateNavVisibility('typescript');
      updateToggleUI('typescript');
    }
  }

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Handle MkDocs Material instant navigation
  if (typeof document$ !== 'undefined') {
    document$.subscribe(init);
  }
})();

// =============================================================================
// Google Analytics (if configured)
// =============================================================================

if (window.GOOGLE_ANALYTICS_KEY) {
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', window.GOOGLE_ANALYTICS_KEY);
}

// =============================================================================
// Smooth scroll for anchor links
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      e.preventDefault();
      const target = document.querySelector(this.getAttribute('href'));
      if (target) {
        target.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
      }
    });
  });
});
