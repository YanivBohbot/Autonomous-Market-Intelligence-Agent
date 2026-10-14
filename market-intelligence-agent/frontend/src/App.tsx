import { Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "./layout/AppLayout";
import { BriefingPage } from "./briefing/BriefingPage";
import { ResearchPage } from "./research/ResearchPage";
import { DataPage } from "./data/DataPage";
import { ClientsPage } from "./clients/ClientsPage";
import { ClientWorkspace } from "./clients/ClientWorkspace";
import { ReportsPage } from "./reports/ReportsPage";
import { ReportWorkspace } from "./reports/ReportWorkspace";

export default function App() {
  return (
    <div className="flex h-full flex-col bg-terminal-bg">
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to="/research" replace />} />
          <Route path="/briefing" element={<BriefingPage />} />
          <Route path="/clients" element={<ClientsPage />} />
          <Route path="/clients/:id" element={<ClientWorkspace />} />
          <Route path="/research" element={<ResearchPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/reports/:id" element={<ReportWorkspace />} />
          <Route path="/data" element={<DataPage />} />
        </Route>
      </Routes>
    </div>
  );
}
