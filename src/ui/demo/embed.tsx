// Docs-site entry. Built by vite.demo.config.ts into a self-contained IIFE
// plus one stylesheet, both scoped to #mesh-scroll.
//
// Mounting is idempotent and lazy-safe: the bundle can be injected at any
// point, and if the mount node is not in the DOM yet it waits for it rather
// than throwing. Phase 2 will load this from an IntersectionObserver.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@xyflow/react/dist/style.css";
// entry.css, not app/globals.css: same theme, plus this bundle's own source
// boundary. See the header of that file.
import "./entry.css";
import "./scroll.css";
import "./embed.css";

import { Stage } from "./stage";
import { EMBED_SHOWS_HEADER } from "./script";

const MOUNT_ID = "mesh-scroll";

function mount(el: HTMLElement) {
  if (el.dataset.meshScrollMounted === "1") return;
  el.dataset.meshScrollMounted = "1";
  // ?mesh-grid — the variant switch is a comparison tool, not part of the
  // design. `framed` is the shipped variant; this only exists so the two can
  // still be compared on the real site if that is ever needed again.
  const devTools = new URLSearchParams(window.location.search).has("mesh-grid");
  createRoot(el).render(
    <StrictMode>
      <Stage devTools={devTools} showHeader={EMBED_SHOWS_HEADER} />
    </StrictMode>
  );
}

function boot() {
  const el = document.getElementById(MOUNT_ID);
  if (el) {
    mount(el);
    return;
  }
  // Injected before the element exists — wait for it rather than failing.
  const obs = new MutationObserver(() => {
    const found = document.getElementById(MOUNT_ID);
    if (found) {
      obs.disconnect();
      mount(found);
    }
  });
  obs.observe(document.documentElement, { childList: true, subtree: true });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
