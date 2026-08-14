// Docs-site entry for the PRERENDERED bundle — the React-free counterpart of
// embed.tsx. Built by vite.static.config.ts into an IIFE plus one stylesheet,
// both scoped to #mesh-scroll.
//
// THE STYLESHEET IS DELIBERATELY THE SAME PIPELINE as the React bundle's, down
// to importing app/globals.css. That import is the open half of #1519 and it is
// tempting to close it here, but changing what Tailwind scans changes which
// utilities exist, and doing that in the same step as replacing the renderer
// would leave any visual difference with two possible causes. The stylesheets
// are byte-identical across the two bundles (the build asserts it), so anything
// that looks wrong is the markup or the driver — which is the whole point of
// having built them side by side.
import "@xyflow/react/dist/style.css";
import "../app/globals.css";
import "./scroll.css";
import "./embed.css";

import generated from "./generated/graph.json";
import { start, type Generated } from "./driver";

const MOUNT_ID = "mesh-scroll";

function mount(el: HTMLElement) {
  if (el.dataset.meshScrollMounted === "1") return;
  el.dataset.meshScrollMounted = "1";
  const G = generated as unknown as Generated;
  el.innerHTML = G.shell;
  start(el, G);
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
  // Give up once the document is done. Without this the observer runs for the
  // lifetime of the page on every page that loads this bundle without a mount
  // point, firing on every DOM mutation the site makes — a permanent cost for
  // a mount that is never going to appear.
  window.addEventListener(
    "load",
    () => {
      if (!document.getElementById(MOUNT_ID)) obs.disconnect();
    },
    { once: true }
  );
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
