import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { MapPin, CalendarDays, DollarSign, Plane } from "lucide-react";
import { useAuth } from "../lib/auth";
import { getSessions, type SessionInfo } from "../lib/api";

export default function Home() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [from, setFrom] = useState("");
  const [destination, setDestination] = useState("");
  const defaultFrom = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000);
  const defaultTo = new Date(Date.now() + 35 * 24 * 60 * 60 * 1000);
  const toDateStr = (d: Date) => d.toISOString().split("T")[0];

  const [fromDate, setFromDate] = useState(toDateStr(defaultFrom));
  const [toDate, setToDate] = useState(toDateStr(defaultTo));
  const [budget, setBudget] = useState(2000);
  const [recentTrips, setRecentTrips] = useState<SessionInfo[]>([]);

  useEffect(() => {
    getSessions()
      .then((sessions) => setRecentTrips(sessions.slice(0, 3)))
      .catch(() => {});
  }, []);

  const formatDates = (from: string, to: string): string => {
    const f = new Date(from + "T00:00:00");
    const t = new Date(to + "T00:00:00");
    const monthFmt = new Intl.DateTimeFormat("en-US", { month: "long" });
    const fMonth = monthFmt.format(f);
    const tMonth = monthFmt.format(t);
    if (f.getFullYear() === t.getFullYear() && f.getMonth() === t.getMonth()) {
      return `${fMonth} ${f.getDate()}-${t.getDate()}, ${f.getFullYear()}`;
    }
    if (f.getFullYear() === t.getFullYear()) {
      return `${fMonth} ${f.getDate()} - ${tMonth} ${t.getDate()}, ${f.getFullYear()}`;
    }
    return `${fMonth} ${f.getDate()}, ${f.getFullYear()} - ${tMonth} ${t.getDate()}, ${t.getFullYear()}`;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!destination.trim() || !fromDate || !toDate) return;

    const dates = formatDates(fromDate, toDate);
    const params = new URLSearchParams({
      destination: destination.trim(),
      dates,
      budget: `$${budget}`,
      ...(from.trim() && { from: from.trim() }),
    });
    navigate(`/plan?${params.toString()}`);
  };

  const firstName = user?.name?.split(" ")[0] || "there";

  return (
    <div className="flex flex-col items-center px-4 py-6 sm:py-12">
      <div className="w-full max-w-lg">
        {/* Greeting */}
        <div className="mb-6">
          <h1 className="text-2xl sm:text-3xl font-bold text-text-primary">
            Hi, {firstName}!
          </h1>
          <p className="text-text-secondary mt-1">Where to next?</p>
        </div>

        {/* Search form card */}
        <form
          onSubmit={handleSubmit}
          className="bg-bg-card rounded-2xl shadow-lg shadow-black/5 p-5 space-y-4"
        >
          {/* From */}
          <div>
            <label className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-1.5 block">
              From
            </label>
            <div className="relative">
              <Plane className="absolute left-3.5 top-1/2 -translate-y-1/2 w-5 h-5 text-mesh-blue" />
              <input
                type="text"
                placeholder="San Francisco, New York..."
                value={from}
                onChange={(e) => setFrom(e.target.value)}
                className="w-full pl-12 pr-4 py-3.5 bg-bg-input border border-border-default rounded-xl text-text-primary text-lg placeholder:text-text-muted focus:outline-none focus:border-mesh-blue focus:ring-2 focus:ring-mesh-blue/10 transition-all"
              />
            </div>
          </div>

          {/* Destination */}
          <div>
            <label className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-1.5 block">
              Destination
            </label>
            <div className="relative">
              <MapPin className="absolute left-3.5 top-1/2 -translate-y-1/2 w-5 h-5 text-mesh-blue" />
              <input
                type="text"
                placeholder="Tokyo, Paris, Bali..."
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                className="w-full pl-12 pr-4 py-3.5 bg-bg-input border border-border-default rounded-xl text-text-primary text-lg placeholder:text-text-muted focus:outline-none focus:border-mesh-blue focus:ring-2 focus:ring-mesh-blue/10 transition-all"
                required
              />
            </div>
          </div>

          {/* Dates */}
          <div className="flex gap-3">
            <div className="flex-1 min-w-0">
              <label className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-1.5 block">
                Depart
              </label>
              <div className="relative">
                <CalendarDays className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-mesh-blue pointer-events-none" />
                <input
                  type="date"
                  value={fromDate}
                  onChange={(e) => setFromDate(e.target.value)}
                  className="w-full pl-11 pr-2 py-3.5 bg-bg-input border border-border-default rounded-xl text-text-primary focus:outline-none focus:border-mesh-blue focus:ring-2 focus:ring-mesh-blue/10 transition-all"
                  required
                />
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <label className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-1.5 block">
                Return
              </label>
              <div className="relative">
                <CalendarDays className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-mesh-blue pointer-events-none" />
                <input
                  type="date"
                  value={toDate}
                  min={fromDate}
                  onChange={(e) => setToDate(e.target.value)}
                  className="w-full pl-11 pr-2 py-3.5 bg-bg-input border border-border-default rounded-xl text-text-primary focus:outline-none focus:border-mesh-blue focus:ring-2 focus:ring-mesh-blue/10 transition-all"
                  required
                />
              </div>
            </div>
          </div>

          {/* Budget */}
          <div>
            <label className="text-xs font-medium text-text-secondary uppercase tracking-wide mb-1.5 block">
              Budget
            </label>
            <div className="bg-bg-input border border-border-default rounded-xl px-4 py-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <DollarSign className="w-5 h-5 text-mesh-blue" />
                  <span className="text-sm text-text-secondary">Total budget</span>
                </div>
                <span className="text-2xl font-bold text-mesh-blue">
                  ${budget.toLocaleString()}
                </span>
              </div>
              <input
                type="range"
                min={500}
                max={10000}
                step={100}
                value={budget}
                onChange={(e) => setBudget(Number(e.target.value))}
                className="w-full"
              />
              <div className="flex justify-between text-xs text-text-muted mt-1.5">
                <span>$500</span>
                <span>$10,000</span>
              </div>
            </div>
          </div>

          {/* Submit */}
          <button
            type="submit"
            className="w-full py-4 bg-mesh-blue text-white text-lg font-semibold rounded-xl hover:bg-mesh-blue/90 active:scale-[0.98] transition-all shadow-md shadow-mesh-blue/20"
          >
            Plan my trip
          </button>
        </form>

        {/* Recent trips */}
        {recentTrips.length > 0 && (
          <div className="mt-8">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wide mb-3">
              Recent Trips
            </h2>
            <div className="space-y-2">
              {recentTrips.map((trip) => (
                <button
                  key={trip.session_id}
                  onClick={() => navigate(`/plan/${trip.session_id}`)}
                  className="w-full text-left bg-bg-card rounded-xl px-4 py-3 flex items-center gap-3 shadow-sm shadow-black/5 hover:shadow-md transition-shadow"
                >
                  <div className="flex items-center justify-center w-10 h-10 rounded-full bg-mesh-blue/10">
                    <MapPin className="w-4 h-4 text-mesh-blue" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-text-primary truncate">
                      {trip.destination}
                    </p>
                    <p className="text-xs text-text-muted">
                      {new Date(trip.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
