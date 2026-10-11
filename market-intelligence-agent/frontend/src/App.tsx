import { useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "./layout/AppLayout";
import { BriefingPage } from "./briefing/BriefingPage";
import { newThreadId } from "./lib/api";
import { DeskView } from "./desk/DeskView";
import { DataPage } from "./data/DataPage";
import { ClientsPage } from "./clients/ClientsPage";
import { ClientWorkspace } from "./clients/ClientWorkspace";
import { ReportsPage } from "./reports/ReportsPage";
import { ReportWorkspace } from "./reports/ReportWorkspace";

export default function App() {
  const [threadId, setThreadId] = useState(newThreadId);

  function onNewSession() {
    setThreadId(newThreadId());
  }

  return (
    <div className="flex h-full flex-col bg-terminal-bg">
      <Routes>
        <Route element={<AppLayout threadId={threadId} onNewSession={onNewSession} />}>
          <Route path="/" element={<Navigate to="/research" replace />} />
          <Route path="/briefing" element={<BriefingPage />} />
          <Route path="/clients" element={<ClientsPage />} />
          <Route path="/clients/:id" element={<ClientWorkspace />} />
          <Route path="/research" element={<DeskView key={threadId} threadId={`desk_${threadId}`} voiceEnabled />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/reports/:id" element={<ReportWorkspace />} />
          <Route path="/data" element={<DataPage />} />
        </Route>
      </Routes>
    </div>
  );
}
