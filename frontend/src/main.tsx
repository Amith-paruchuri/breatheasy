import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Self-hosted fonts: no third-party font requests, and they work offline in the installed app.
import "@fontsource-variable/bricolage-grotesque/opsz.css";
import "@fontsource-variable/instrument-sans/index.css";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Installable app + offline shell. Production builds only, so dev never serves stale code.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* non-fatal: the app works without it */
    });
  });
}
