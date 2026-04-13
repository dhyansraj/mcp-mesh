import { useState } from "react";
import { Outlet, NavLink } from "react-router-dom";
import { Home, Compass, Luggage, Heart, User, Plane } from "lucide-react";
import { useAuth } from "../lib/auth";

export default function Layout() {
  const { user } = useAuth();
  const [showMenu, setShowMenu] = useState(false);

  const initials = user?.name
    ? user.name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "?";

  return (
    <div className="flex flex-col min-h-screen bg-bg-primary">
      {/* Header — extra top padding clears iPhone notch/Dynamic Island */}
      <header className="flex items-center justify-between px-4 pt-12 pb-3 bg-mesh-blue">
        <div className="flex items-center gap-2">
          <Plane className="w-5 h-5 text-white" />
          <span className="text-lg font-bold text-white">
            TripPlanner
          </span>
        </div>
        <div className="relative flex items-center gap-2.5">
          <span className="text-sm text-white/80 hidden sm:block">
            {user?.name || user?.email}
          </span>
          <button
            onClick={() => setShowMenu((v) => !v)}
            className="flex items-center justify-center w-8 h-8 rounded-full bg-white/20 text-white text-xs font-semibold cursor-pointer"
          >
            {initials}
          </button>

          {showMenu && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setShowMenu(false)}
              />
              <div className="absolute right-0 top-full mt-2 z-50 w-56 bg-white rounded-xl shadow-lg shadow-black/15 py-2 animate-[fadeIn_150ms_ease-out]">
                <div className="px-4 py-2.5">
                  <p className="text-sm font-bold text-gray-900 truncate">
                    {user?.name}
                  </p>
                  <p className="text-xs text-gray-500 truncate">
                    {user?.email}
                  </p>
                </div>
                <div className="border-t border-gray-100 my-1" />
                <a
                  href="/auth/logout"
                  className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  Sign out
                </a>
              </div>
            </>
          )}
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto pb-16 sm:pb-0">
        <Outlet />
      </main>

      {/* Bottom navigation */}
      <nav className="fixed bottom-0 left-0 right-0 flex items-center justify-around px-2 py-1.5 bg-bg-card border-t border-border-default sm:hidden" style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + 0.375rem)' }}>
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            `flex flex-col items-center gap-0.5 px-3 py-1 transition-colors ${
              isActive ? "text-mesh-blue" : "text-text-muted"
            }`
          }
        >
          <Home className="w-5 h-5" />
          <span className="text-[10px] font-medium">Home</span>
        </NavLink>

        <div className="flex flex-col items-center gap-0.5 px-3 py-1 text-text-muted/40 cursor-default">
          <Compass className="w-5 h-5" />
          <span className="text-[10px] font-medium">Explore</span>
        </div>

        <NavLink
          to="/history"
          className={({ isActive }) =>
            `flex flex-col items-center gap-0.5 px-3 py-1 transition-colors ${
              isActive ? "text-mesh-blue" : "text-text-muted"
            }`
          }
        >
          <Luggage className="w-5 h-5" />
          <span className="text-[10px] font-medium">Trips</span>
        </NavLink>

        <div className="flex flex-col items-center gap-0.5 px-3 py-1 text-text-muted/40 cursor-default">
          <Heart className="w-5 h-5" />
          <span className="text-[10px] font-medium">Saved</span>
        </div>

        <div className="flex flex-col items-center gap-0.5 px-3 py-1 text-text-muted/40 cursor-default">
          <User className="w-5 h-5" />
          <span className="text-[10px] font-medium">Profile</span>
        </div>
      </nav>
    </div>
  );
}
