import { Link } from "react-router-dom";
import { useLocation } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { LayoutDashboard, Bot, Network, BarChart3, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { getBasePath } from "@/lib/config";
import { useMesh } from "@/lib/mesh-context";

const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Agents", href: "/agents", icon: Bot },
  { name: "Topology", href: "/topology", icon: Network },
  { name: "Traffic", href: "/traffic", icon: BarChart3 },
  { name: "Live", href: "/live", icon: Radio },
];

export function Sidebar() {
  const { pathname } = useLocation();
  const { connected, traceActivity } = useMesh();

  // Pulse the Live dot only when new agent names appear in trace activity
  const [recentActivity, setRecentActivity] = useState(false);
  const prevKeysRef = useRef<string>("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const keys = Object.keys(traceActivity).sort().join(",");
    if (keys !== prevKeysRef.current && keys !== "") {
      // New agents appeared in trace activity
      if (prevKeysRef.current !== "") {
        setRecentActivity(true);
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => setRecentActivity(false), 10000);
      }
      prevKeysRef.current = keys;
    }
  }, [traceActivity]);

  // Clear timer on unmount only
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-border bg-sidebar">
      {/* Logo */}
      <div className="flex h-16 items-center gap-3 border-b border-border px-6">
        <img src={`${getBasePath()}/logo.svg`} alt="MCP Mesh" width={40} height={40} />
        <span className="text-xl font-semibold text-sidebar-foreground">
          MCP Mesh
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navigation.map((item) => {
          const normalizedPath = pathname.replace(/\/+$/, "") || "/";
          const normalizedHref = item.href.replace(/\/+$/, "") || "/";
          const isActive =
            normalizedPath === normalizedHref ||
            (normalizedHref !== "/" && normalizedPath.startsWith(normalizedHref));

          return (
            <Link
              key={item.name}
              to={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-base font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-primary"
                  : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              )}
            >
              <item.icon className="h-5 w-5" />
              {item.name}
              {item.name === "Live" && recentActivity && (
                <span className="h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer - SSE Connection Indicator */}
      <div className="border-t border-border px-6 py-4">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "flex h-2 w-2 rounded-full",
              connected ? "bg-green-500" : "bg-destructive"
            )}
          />
          <span className="text-xs text-muted-foreground">
            {connected ? "Connected" : "Disconnected"}
          </span>
        </div>
      </div>
    </aside>
  );
}
