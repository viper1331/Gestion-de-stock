import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";

import { SpellcheckSettingsProvider } from "./app/spellcheckSettings";
import { ThemeProvider } from "./app/theme";
import { router } from "./app/routes";
import { initializeLogging } from "./lib/logger";
import "./styles/tailwind.css";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const queryClient = new QueryClient();

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
