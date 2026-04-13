import { useEffect, useRef, useState } from "react";
import { useSearchParams, useParams } from "react-router-dom";
import { Send, ArrowLeft } from "lucide-react";
import { planTrip, getSessionHistory, type PlanResponse } from "../lib/api";
import ChatBubble from "../components/ChatBubble";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function Plan() {
  const [searchParams] = useSearchParams();
  const { sessionId: routeSessionId } = useParams();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>(
    routeSessionId
  );
  const [tripInfo, setTripInfo] = useState({
    from: searchParams.get("from") || "",
    destination: searchParams.get("destination") || "",
    dates: searchParams.get("dates") || "",
    budget: searchParams.get("budget") || "$2000",
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const initialFetchDone = useRef(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Load existing session history
  useEffect(() => {
    if (routeSessionId && !initialFetchDone.current) {
      initialFetchDone.current = true;
      getSessionHistory(routeSessionId)
        .then((history) => {
          setMessages(history);
          setSessionId(routeSessionId);
        })
        .catch(() => {});
    }
  }, [routeSessionId]);

  // Auto-submit initial trip request
  useEffect(() => {
    if (
      !routeSessionId &&
      tripInfo.destination &&
      messages.length === 0 &&
      !initialFetchDone.current
    ) {
      initialFetchDone.current = true;
      submitPlan();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submitPlan(followUpMessage?: string) {
    const message = followUpMessage || "";
    const fromClause = tripInfo.from ? ` departing from ${tripInfo.from}` : "";
    const userText =
      message ||
      `Plan a trip to ${tripInfo.destination}${fromClause} from ${tripInfo.dates} with a budget of ${tripInfo.budget}.`;

    setMessages((prev) => [...prev, { role: "user", content: userText }]);
    setLoading(true);
    setInput("");

    try {
      const response: PlanResponse = await planTrip(
        {
          destination: tripInfo.destination,
          dates: tripInfo.dates,
          budget: tripInfo.budget,
          from: tripInfo.from || undefined,
          message: message || undefined,
        },
        sessionId
      );

      setSessionId(response.session_id);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: response.result },
      ]);
    } catch (err) {
      const errorMsg =
        err instanceof Error ? err.message : "Something went wrong";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Error: ${errorMsg}. Please check that the mesh agents are running.`,
        },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function handleFollowUp(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;
    submitPlan(input.trim());
  }

  return (
    <div className="flex flex-col h-[calc(100vh-52px-64px)] sm:h-[calc(100vh-52px)]">
      {/* Trip header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-bg-card border-b border-border-default shadow-sm">
        <a
          href="/"
          className="p-1.5 text-text-muted hover:text-text-primary transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </a>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-text-primary truncate">
            {tripInfo.from
              ? `${tripInfo.from} \u2192 ${tripInfo.destination || "Trip Plan"}`
              : tripInfo.destination || "Trip Plan"}
          </h2>
          <p className="text-xs text-text-muted truncate">
            {tripInfo.dates} {tripInfo.budget ? `\u00B7 ${tripInfo.budget}` : ""}
          </p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 bg-bg-primary">
        {messages.map((msg, i) => (
          <ChatBubble key={i} role={msg.role} content={msg.content} />
        ))}

        {loading && (
          <div className="flex justify-start mb-4">
            <div className="bg-bg-card rounded-2xl rounded-bl-md px-5 py-4 shadow-sm shadow-black/5">
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-mesh-blue typing-dot" />
                <div className="w-2 h-2 rounded-full bg-mesh-blue typing-dot" />
                <div className="w-2 h-2 rounded-full bg-mesh-blue typing-dot" />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleFollowUp}
        className="flex items-center gap-2 px-4 py-3 bg-bg-card border-t border-border-default"
      >
        <input
          ref={inputRef}
          type="text"
          placeholder="Ask a follow-up..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={loading}
          className="flex-1 px-4 py-2.5 bg-bg-input border border-border-default rounded-xl text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-mesh-blue focus:ring-2 focus:ring-mesh-blue/10 disabled:opacity-50 transition-all"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="p-2.5 bg-mesh-blue text-white rounded-xl hover:bg-mesh-blue/90 disabled:opacity-40 disabled:cursor-not-allowed active:scale-95 transition-all shadow-sm shadow-mesh-blue/20"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}
