import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";

import { SpellcheckSettingsProvider } from "./app/spellcheckSettings";
import { ThemeProvider } from "./app/theme";
import { router } from "./app/routes";
import { initializeLogging } from "./lib/logger";
import { queryClient } from "./lib/queryClient";
import "./styles/tailwind.css";

initializeLogging();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <SpellcheckSettingsProvider>
          <RouterProvider router={router} />
        </SpellcheckSettingsProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>
);
