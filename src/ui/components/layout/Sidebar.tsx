"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Bot, Network } from "lucide-react";
// eslint-disable-next-line @next/next/no-img-element
import { cn } from "@/lib/utils";
import { useMesh } from "@/lib/mesh-context";

const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Agents", href: "/agents", icon: Bot },
  { name: "Topology", href: "/topology", icon: Network },
];

export function Sidebar() {
  const pathname = usePathname();
  const { connected } = useMesh();

  return (
    <aside className="flex h-screen w-64 flex-col border-r border-border bg-sidebar">
      {/* Logo */}
      <div className="flex h-16 items-center gap-3 border-b border-border px-6">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo.svg" alt="MCP Mesh" width={40} height={40} />
        <span className="text-xl font-semibold text-sidebar-foreground">
          MCP Mesh
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navigation.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));

          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-base font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-primary"
                  : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              )}
            >
              <item.icon className="h-5 w-5" />
              {item.name}
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
