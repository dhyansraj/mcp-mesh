// Docs-site entry for the PRERENDERED bundle — the React-free counterpart of
// embed.tsx. Built by vite.static.config.ts into an IIFE plus one stylesheet,
// both scoped to #mesh-scroll.
//
// THE STYLESHEET IS DELIBERATELY THE SAME PIPELINE as the React bundle's, down
// to the same entry: demo/entry.css, which is app/globals.css plus this
// bundle's source boundary. Keeping the two identical is what makes the
// equivalence comparison mean anything — the stylesheets come out byte-for-byte
// the same across the two bundles, so anything that looks wrong is the markup
// or the driver, which is the whole point of having built them side by side.
// Changing this import in only one of the two would give any visual difference
// a second possible cause.
import "@xyflow/react/dist/style.css";
import "./entry.css";
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
