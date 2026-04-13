import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MapPin, MessageSquare, Loader2, Luggage } from "lucide-react";
import { getSessions, type SessionInfo } from "../lib/api";

export default function History() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSessions()
      .then(setSessions)
      .catch((err) => {
        if (err.message?.includes("404") || err.message?.includes("405")) {
          setSessions([]);
        } else {
          setError("Could not load trip history");
        }
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 animate-spin text-mesh-blue" />
      </div>
    );
  }

  return (
    <div className="px-4 py-6 max-w-lg mx-auto">
      <h1 className="text-xl font-bold text-text-primary mb-6">Your Trips</h1>

      {error && (
        <p className="text-center text-text-muted py-8">{error}</p>
      )}

      {!error && sessions.length === 0 && (
        <div className="text-center py-16">
          <div className="flex items-center justify-center w-16 h-16 rounded-full bg-mesh-blue/10 mx-auto mb-4">
            <Luggage className="w-8 h-8 text-mesh-blue opacity-50" />
          </div>
          <p className="text-text-primary font-medium mb-1">No trips yet</p>
          <p className="text-sm text-text-muted mb-4">
            Start planning your next adventure!
          </p>
          <button
            onClick={() => navigate("/")}
            className="text-sm font-medium text-mesh-blue hover:underline"
          >
            Plan your first trip
          </button>
        </div>
      )}

      <div className="space-y-3">
        {sessions.map((session) => (
          <button
            key={session.session_id}
            onClick={() => navigate(`/plan/${session.session_id}`)}
            className="w-full text-left bg-bg-card rounded-2xl px-4 py-4 shadow-sm shadow-black/5 hover:shadow-md active:scale-[0.99] transition-all"
          >
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-mesh-blue/10 flex-shrink-0">
                <MapPin className="w-4 h-4 text-mesh-blue" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-text-primary truncate">
                  {session.destination}
                </p>
                <div className="flex items-center gap-3 text-xs text-text-muted mt-0.5">
                  <span>
                    {new Date(session.created_at).toLocaleDateString()}
                  </span>
                  <span className="flex items-center gap-1">
                    <MessageSquare className="w-3 h-3" />
                    {session.turn_count} turns
                  </span>
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
