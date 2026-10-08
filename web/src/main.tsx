import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "./styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { CaseReplay } from "./pages/CaseReplay";
import { Cases } from "./pages/Cases";
import { Experiments } from "./pages/Experiments";
import { Integrity } from "./pages/Integrity";
import { Method } from "./pages/Method";
import { NotFound } from "./pages/NotFound";
import { Violations } from "./pages/Violations";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root element");

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/cases" replace />} />
          <Route path="cases" element={<Cases />} />
          <Route path="cases/:caseId" element={<CaseReplay />} />
          <Route path="violations" element={<Violations />} />
          <Route path="integrity" element={<Integrity />} />
          <Route path="experiments" element={<Experiments />} />
          <Route path="method" element={<Method />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
