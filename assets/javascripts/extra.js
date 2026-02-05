// Custom JavaScript for MCP Mesh documentation

// =============================================================================
// Runtime Toggle - Python/TypeScript SDK Switcher
// =============================================================================

(function() {
  const STORAGE_KEY = 'mcp-mesh-runtime';
  const RUNTIMES = {
    python: { label: 'Python', icon: '🐍', navId: 'python-sdk' },
    java: { label: 'Java', icon: '☕', navId: 'java-sdk' },
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

  // Equivalent page groups - each array contains [python_path, typescript_path, java_path]
  const PAGE_EQUIVALENTS = [
    ['python', 'typescript', 'java'],
    ['python/getting-started', 'typescript/getting-started', 'java/getting-started'],
    ['python/getting-started/prerequisites', 'typescript/getting-started/prerequisites', 'java/getting-started/prerequisites'],
    ['python/decorators', 'typescript/mesh-functions', 'java/annotations'],
    ['python/dependency-injection', 'typescript/dependency-injection', 'java/dependency-injection'],
    ['python/capabilities-tags', 'typescript/capabilities-tags', 'java/capabilities-tags'],
    ['python/llm', 'typescript/llm', 'java/llm'],
    ['python/fastapi-integration', 'typescript/express-integration', 'java/spring-boot-integration'],
    ['python/examples', 'typescript/examples', 'java/examples'],
    ['python/local-development', 'typescript/local-development', 'java/local-development'],
    ['python/local-development/01-getting-started', 'typescript/local-development/01-getting-started', 'java/local-development/01-getting-started'],
    ['python/local-development/02-scaffold', 'typescript/local-development/02-scaffold', 'java/local-development/02-scaffold'],
    ['python/local-development/03-running-agents', 'typescript/local-development/03-running-agents', 'java/local-development/03-running-agents'],
    ['python/local-development/04-inspecting-mesh', 'typescript/local-development/04-inspecting-mesh', 'java/local-development/04-inspecting-mesh'],
    ['python/local-development/05-calling-tools', 'typescript/local-development/05-calling-tools', 'java/local-development/05-calling-tools'],
    ['python/local-development/troubleshooting', 'typescript/local-development/troubleshooting', 'java/local-development/troubleshooting'],
  ];

  // Build bidirectional mappings: PAGE_MAP[sourcePath] = { python: pyPath, typescript: tsPath, java: javaPath }
  const PAGE_MAP = {};
  const RUNTIME_KEYS = ['python', 'typescript', 'java'];
  PAGE_EQUIVALENTS.forEach(group => {
    group.forEach((path, idx) => {
      const mapping = {};
      RUNTIME_KEYS.forEach((runtime, rIdx) => {
        if (rIdx !== idx) {
          mapping[runtime] = group[rIdx];
        }
      });
      PAGE_MAP[path] = mapping;
    });
  });

  function getStoredRuntime() {
    return localStorage.getItem(STORAGE_KEY) || 'python';
  }

  function setStoredRuntime(runtime) {
    localStorage.setItem(STORAGE_KEY, runtime);
  }

  function getCurrentPagePath() {
    const path = window.location.pathname
      .replace(/\/$/, '')
      .replace(/\/index\.html$/, '')
      .replace(/\.html$/, '');

    const pythonMatch = path.match(/\/(python(?:\/.*)?)?$/);
    const tsMatch = path.match(/\/(typescript(?:\/.*)?)?$/);
    const javaMatch = path.match(/\/(java(?:\/.*)?)?$/);

    if (pythonMatch && pythonMatch[1]) return pythonMatch[1];
    if (tsMatch && tsMatch[1]) return tsMatch[1];
    if (javaMatch && javaMatch[1]) return javaMatch[1];

    const basePath = document.querySelector('base')?.href || '';
    if (basePath) {
      const basePathname = new URL(basePath, window.location.origin).pathname.replace(/\/$/, '');
      return path.replace(basePathname, '').replace(/^\//, '');
    }
    return path.replace(/^\//, '');
  }

  function isRuntimePage(path) {
    return path === 'python' || path.startsWith('python/') ||
           path === 'typescript' || path.startsWith('typescript/') ||
           path === 'java' || path.startsWith('java/');
  }

  function getEquivalentPage(currentPath, targetRuntime) {
    const mapping = PAGE_MAP[currentPath];
    if (mapping && mapping[targetRuntime]) {
      return mapping[targetRuntime];
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
      const runtimeMatch = pathname.match(/^(.*?)\/(python|typescript|java)(\/|$)/);
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
    const navItems = document.querySelectorAll('.md-nav__item');
    navItems.forEach(item => {
      const link = item.querySelector('.md-nav__link');
      if (!link) return;
      const href = link.getAttribute('href') || '';
      const text = link.textContent?.toLowerCase() || '';

      if (text.includes('python sdk') || href.includes('/python/')) {
        item.style.display = runtime === 'python' ? '' : 'none';
        item.dataset.runtime = 'python';
      } else if (text.includes('typescript sdk') || href.includes('/typescript/')) {
        item.style.display = runtime === 'typescript' ? '' : 'none';
        item.dataset.runtime = 'typescript';
      } else if (text.includes('java sdk') || href.includes('/java/')) {
        item.style.display = runtime === 'java' ? '' : 'none';
        item.dataset.runtime = 'java';
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
        <button class="runtime-option ${runtime === 'java' ? 'active' : ''}" data-runtime="java">
          ☕ Java
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
    insertToggleWidget();
    updateNavVisibility(runtime);

    const currentPath = getCurrentPagePath();
    if (currentPath === 'python' || currentPath.startsWith('python/')) {
      setStoredRuntime('python');
      updateNavVisibility('python');
      updateToggleUI('python');
    } else if (currentPath === 'typescript' || currentPath.startsWith('typescript/')) {
      setStoredRuntime('typescript');
      updateNavVisibility('typescript');
      updateToggleUI('typescript');
    } else if (currentPath === 'java' || currentPath.startsWith('java/')) {
      setStoredRuntime('java');
      updateNavVisibility('java');
      updateToggleUI('java');
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
