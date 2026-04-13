import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Plane, Sparkles, RefreshCw, Zap } from "lucide-react";
import { useAuth } from "../lib/auth";

const features = [
  {
    icon: Sparkles,
    title: "AI-Powered Planning",
    desc: "Specialist agents analyze budget, adventures, and logistics",
  },
  {
    icon: RefreshCw,
    title: "Multi-Provider LLM",
    desc: "Seamlessly switch between Claude, GPT, and Gemini",
  },
  {
    icon: Zap,
    title: "Real-Time Insights",
    desc: "Live flight prices, hotel rates, and weather data",
  },
];

export default function Login() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && user) {
      navigate("/", { replace: true });
    }
  }, [user, loading, navigate]);

  return (
    <div
      className="flex flex-col items-center justify-center min-h-screen px-6 py-12"
      style={{
        background:
          "linear-gradient(160deg, #5a6bc4 0%, #4051b5 40%, #3545a0 70%, #2a3780 100%)",
      }}
    >
      <div className="flex flex-col items-center max-w-md w-full">
        {/* Logo */}
        <div className="flex items-center gap-2.5 mb-10">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-white/15 backdrop-blur-sm">
            <Plane className="w-5 h-5 text-white" />
          </div>
          <span className="text-xl font-bold text-white">TripPlanner</span>
        </div>

        {/* Hero headline */}
        <h1 className="text-3xl sm:text-4xl font-extrabold text-white text-center leading-tight tracking-tight mb-4">
          Plan your perfect trip with AI
        </h1>
        <p className="text-white/70 text-center text-base sm:text-lg leading-relaxed mb-10 max-w-sm">
          Powered by a mesh of specialist AI agents that search flights, analyze
          budgets, and craft personalized itineraries
        </p>

        {/* Feature cards */}
        <div className="flex flex-col gap-3 w-full mb-10">
          {features.map((f) => (
            <div
              key={f.title}
              className="flex items-start gap-4 px-5 py-4 rounded-2xl bg-white/10 backdrop-blur-sm"
            >
              <div className="flex items-center justify-center w-9 h-9 rounded-xl bg-white/15 shrink-0 mt-0.5">
                <f.icon className="w-[18px] h-[18px] text-white" />
              </div>
              <div>
                <p className="text-sm font-semibold text-white">{f.title}</p>
                <p className="text-xs text-white/60 leading-relaxed mt-0.5">
                  {f.desc}
                </p>
              </div>
            </div>
          ))}
        </div>

        {/* Google sign-in */}
        <a
          href="/auth/google"
          className="flex items-center justify-center gap-3 w-full px-6 py-4 bg-white text-gray-800 font-semibold rounded-2xl hover:bg-gray-50 active:scale-[0.98] transition-all shadow-xl shadow-black/10"
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24">
            <path
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
              fill="#4285F4"
            />
            <path
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              fill="#34A853"
            />
            <path
              d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              fill="#FBBC05"
            />
            <path
              d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              fill="#EA4335"
            />
          </svg>
          Sign in with Google
        </a>

        {/* Footer */}
        <div className="flex items-center justify-center gap-2 mt-10">
          <img src="/mesh-logo.svg" alt="MCP Mesh" className="h-5 opacity-40" />
          <p className="text-sm text-white/40">
            Powered by MCP Mesh
          </p>
        </div>
      </div>
    </div>
  );
}
