import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { loadRuntimeConfig } from "./lib/runtime-config";
import "./index.css";

// Fetch runtime config before first render so API calls use the right URL.
// Falls back to baked env vars if /config.json isn't present.
loadRuntimeConfig().finally(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </React.StrictMode>
  );
});
