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

/**
 * Move what the SERVED DOCUMENT already contains into the prerendered shell.
 *
 * The mount is replaced wholesale — `innerHTML = shell` — so anything the host
 * page put inside it has to be taken out first and put back after. Two things
 * qualify, and they are kept for opposite reasons:
 *
 *   the copy blocks — the fourteen beats are real elements in the first HTML
 *     response. The animation adopts those nodes rather than rendering its own,
 *     so there is exactly one copy of every beat in the document and the prose
 *     a search engine indexed is the prose on screen. What each reader gets of
 *     it differs, and NOT in the order the sequence here suggests: a crawler
 *     reads the response, so it has all fourteen; a reader without JavaScript
 *     sees them laid out as linear prose, because nothing ever arms the mount;
 *     and a reader WITH JavaScript never meets more than one at a time, since
 *     the loader arms the section during parse and the armed rules leave only
 *     beat 1 rendered until this runs. From here on it is the frame that
 *     decides — the blocks it paints are in the accessibility tree and the rest
 *     are `inert` (rail.ts) — so the change at this line is which one block is
 *     readable, not how many.
 *
 *   the skip link — the first focusable thing in the section, and it has to
 *     survive the section becoming twenty-one screens of pinned scroll.
 *
 * Detached nodes stay valid, so these references still work after the wipe.
 *
 * Returns false if the shell it was handed has nowhere to put the copy, having
 * left the caller's saved markup untouched for the restore.
 */
function adopt(el: HTMLElement, G: Generated): boolean {
  const blocks = Array.from(el.querySelectorAll<HTMLElement>("[data-mesh-beat]"));
  const skip = el.querySelector<HTMLElement>("[data-mesh-skip]");

  el.innerHTML = G.shell;

  const slot = el.querySelector<HTMLElement>('[data-mesh="copy"]');
  // NO SLOT, NO ANIMATION. The blocks are held in a detached fragment at this
  // point, so carrying on here would drop every word in the section on the
  // floor and reserve ~2205vh of scroll for what was left.
  if (!slot) return false;
  // Indices must be present, in order, and complete. A host page carrying a
  // partial or stale set is worse than one carrying none: the driver would
  // address blocks by index and animate the wrong beats.
  const ok =
    blocks.length === G.beatCount &&
    blocks.every((b, i) => b.dataset.meshBeat === String(i));
  if (ok) for (const b of blocks) slot.appendChild(b);
  else slot.innerHTML = G.beatCopy.map((b) => b.html).join("");
  if (skip) el.insertBefore(skip, el.firstChild);
  return true;
}

/**
 * Adopt, then animate — and put the served copy back if either declines.
 *
 * THE RESTORE IS THE POINT. Adoption is destructive and used to be irreversible:
 * the mount was overwritten before anything had checked the shell, and both
 * failure paths after that were silent returns. A shell with no copy slot
 * dropped the adopted blocks, and a driver that bailed left the custom
 * properties unwritten — which, with `opacity: var(--b, 0)` on every block,
 * is ~2205vh of reserved height containing no prose at all. The previous shell
 * carried beat 1 inline, so this failure at least still showed the opening
 * words; the copy stack removed that accident, and this replaces it with a
 * deliberate version.
 *
 * A THROW LANDS IN THE SAME PLACE AS A REFUSAL. Both failure paths return a
 * boolean, but neither of them is the only way this can end badly: `start()`
 * runs a synchronous first apply that measures label boxes, reads element
 * geometry and writes ~80 custom properties, all of it against markup that came
 * out of a build artifact. An exception anywhere in there would escape with the
 * mount already wiped, the blocks already moved into a stack that begins at
 * zero opacity, and the reserved height already in force — the exact state this
 * function exists to prevent, reached by the one route the return values cannot
 * describe.
 *
 * The saved fragment is a deep clone of live nodes rather than a serialisation,
 * so what comes back is exactly what was served.
 */
function mount(el: HTMLElement) {
  // NOT re-entrancy — boot() calls this once per element. The attribute is the
  // MOUNTED SIGNAL, which the equivalence harness waits on: it is written only
  // once the driver has taken over, so a restored section carries neither the
  // flag nor the reservation and cannot be mistaken for a running one.
  if (el.dataset.meshScrollMounted === "1") return;
  const G = generated as unknown as Generated;

  // Taken BEFORE the wipe, and cloned rather than referenced: adoption moves
  // the real blocks into the shell, so a fragment of the originals would come
  // back missing exactly the part worth restoring.
  const served = document.createDocumentFragment();
  for (const node of Array.from(el.childNodes)) served.appendChild(node.cloneNode(true));

  let running = false;
  let why = "declined";
  try {
    running = adopt(el, G) && start(el, G);
  } catch (err) {
    why = "threw";
    // Reported, not swallowed: the reader gets the served reading either way,
    // but a section that quietly declines to animate should still say why.
    console.error("[mesh-scroll] the animation could not start; served copy restored", err);
  }
  if (running) {
    el.dataset.meshScrollMounted = "1";
    return;
  }
  // Back to the served reading: the copy as linear prose, no reserved height.
  // Disarming is what the loader does when the bundle cannot be fetched at all,
  // and this is the same outcome by a different route.
  el.innerHTML = "";
  el.appendChild(served);
  el.classList.remove("mesh-scroll-armed");
  // THE RESTORED SIGNAL, the counterpart of the mounted one above and set for
  // the same reason: the two together say which of the section's two readings
  // is on screen, so anyone looking at a live page — or a harness waiting on
  // the mount — can tell "restored, and by which route" from "still starting"
  // without waiting for a timeout to decide for them. Written LAST, after the
  // served nodes are back, so its presence also means the restore finished.
  el.dataset.meshScrollRestored = why;
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
