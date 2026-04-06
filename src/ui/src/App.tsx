import { Routes, Route } from "react-router-dom";
import { Sidebar } from "../components/layout/Sidebar";
import { Providers } from "../components/layout/Providers";
import DashboardPage from "../app/page";
import AgentsPage from "../app/agents/page";
import TopologyPage from "../app/topology/page";
import TrafficPage from "../app/traffic/page";
import LivePage from "../app/live/page";

export function App() {
  return (
    <Providers>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-auto">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/topology" element={<TopologyPage />} />
            <Route path="/traffic" element={<TrafficPage />} />
            <Route path="/live" element={<LivePage />} />
          </Routes>
        </main>
      </div>
    </Providers>
  );
}
