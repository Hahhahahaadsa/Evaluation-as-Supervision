import { useState } from "react";
import { Activity, LayoutDashboard } from "lucide-react";
import Dashboard from "./pages/Dashboard.jsx";
import PipelineMonitor from "./pages/PipelineMonitor.jsx";

export default function App() {
  const [view, setView] = useState("dashboard");

  return (
    <>
      <nav className="app-nav">
        <button
          className={view === "dashboard" ? "is-active" : ""}
          onClick={() => setView("dashboard")}
        >
          <LayoutDashboard size={16} aria-hidden="true" />
          Dashboard
        </button>
        <button
          className={view === "monitor" ? "is-active" : ""}
          onClick={() => setView("monitor")}
        >
          <Activity size={16} aria-hidden="true" />
          Pipeline Monitor
        </button>
      </nav>

      {view === "dashboard" ? <Dashboard /> : <PipelineMonitor />}
    </>
  );
}
