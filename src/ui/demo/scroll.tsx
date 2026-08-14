// Dev entry. Serve with `npm run dev` → http://localhost:3000/demo/scroll.html
//
// This page loads the stylesheets UNSCOPED — it owns the whole document, so
// Tailwind's preflight and meshui's `:root` variables landing globally is
// exactly what we want. The docs-site bundle (embed.tsx) imports embed.css
// instead, which is the same CSS confined to #mesh-scroll.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@xyflow/react/dist/style.css";
import "./entry.css";
import "./scroll.css";

import { Stage } from "./stage";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Stage devTools showHeader />
  </StrictMode>
);
