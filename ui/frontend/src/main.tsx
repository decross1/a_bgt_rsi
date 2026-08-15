import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// Self-hosted variable fonts (Geist Sans + Geist Mono) — the documented
// fontsource-on-Vite pattern; the families are named in design/tokens.css.
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./index.css";
// R0 design tokens load AFTER index.css so the new system's custom
// properties win where names collide with the legacy shared block.
import "./design/tokens.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
