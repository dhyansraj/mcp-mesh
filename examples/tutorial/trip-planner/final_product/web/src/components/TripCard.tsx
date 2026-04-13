import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  DollarSign,
  Compass,
  Clock,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface TripCardProps {
  type: "budget" | "adventure" | "logistics";
  content: string;
}

const cardConfig = {
  budget: {
    icon: DollarSign,
    label: "Budget Analysis",
    bg: "bg-emerald-50",
    iconBg: "bg-emerald-100",
    iconColor: "text-emerald-600",
    headerColor: "text-emerald-800",
    border: "border-emerald-200",
    accent: "text-emerald-700",
    accentBg: "bg-emerald-100",
    accentBorder: "border-emerald-200",
  },
  adventure: {
    icon: Compass,
    label: "Adventure Recommendations",
    bg: "bg-amber-50",
    iconBg: "bg-amber-100",
    iconColor: "text-amber-600",
    headerColor: "text-amber-800",
    border: "border-amber-200",
    accent: "text-amber-700",
    accentBg: "bg-amber-100",
    accentBorder: "border-amber-200",
  },
  logistics: {
    icon: Clock,
    label: "Logistics Plan",
    bg: "bg-blue-50",
    iconBg: "bg-blue-100",
    iconColor: "text-blue-600",
    headerColor: "text-blue-800",
    border: "border-blue-200",
    accent: "text-blue-700",
    accentBg: "bg-blue-100",
    accentBorder: "border-blue-200",
  },
};

/**
 * Convert a Python-repr string (single-quoted keys/values, True/False/None)
 * into valid JSON. Handles apostrophes inside string values (e.g. "you'll",
 * "Philosopher's") by walking character-by-character and only converting
 * the structural single quotes that serve as string delimiters.
 */
function pythonReprToJson(s: string): string {
  const result: string[] = [];
  let i = 0;

  while (i < s.length) {
    if (s[i] === "'") {
      // Opening single quote: convert to double quote, then consume until
      // the matching closing single quote. A closing delimiter is a single
      // quote followed by a structural character: , ] } : or whitespace
      // before one of those.
      result.push('"');
      i++;
      while (i < s.length) {
        if (s[i] === "'" ) {
          // Look ahead: is this closing the string or an apostrophe?
          // Closing quote is followed by optional whitespace then a
          // structural char (: , } ] or end of string).
          let ahead = i + 1;
          while (ahead < s.length && s[ahead] === " ") ahead++;
          const next = ahead < s.length ? s[ahead] : "\0";
          if (
            next === ":" ||
            next === "," ||
            next === "}" ||
            next === "]" ||
            next === "\0"
          ) {
            // Closing delimiter
            break;
          }
          // Otherwise it's a mid-string apostrophe — keep it
          result.push(s[i]);
          i++;
        } else if (s[i] === '"') {
          // Escape double quotes that appear inside the value
          result.push('\\"');
          i++;
        } else if (s[i] === "\\" && i + 1 < s.length) {
          result.push(s[i], s[i + 1]);
          i += 2;
        } else {
          result.push(s[i]);
          i++;
        }
      }
      result.push('"');
      if (i < s.length) i++; // skip closing single quote
    } else {
      result.push(s[i]);
      i++;
    }
  }
  return result.join("");
}

function tryParsePythonDict(raw: string): Record<string, unknown> | null {
  // Strip leading/trailing whitespace and surrounding markdown fences
  let s = raw.trim();
  s = s.replace(/^```(?:python|json)?\s*/i, "").replace(/\s*```$/, "");
  s = s.trim();

  // Only attempt parse if it looks like a dict/object
  if (!s.startsWith("{")) return null;

  // Try parsing as-is first (valid JSON or backend already sends JSON)
  try {
    return JSON.parse(s);
  } catch {
    // noop
  }

  // Fall back to Python-repr conversion
  try {
    const jsonified = pythonReprToJson(s)
      .replace(/\bTrue\b/g, "true")
      .replace(/\bFalse\b/g, "false")
      .replace(/\bNone\b/g, "null")
      // Handle trailing commas before } or ]
      .replace(/,\s*([}\]])/g, "$1");
    return JSON.parse(jsonified);
  } catch {
    return null;
  }
}

function formatCurrency(n: number): string {
  return "$" + n.toLocaleString("en-US");
}

function isNonEmpty(val: unknown): boolean {
  if (val == null) return false;
  if (typeof val === "object" && !Array.isArray(val) && Object.keys(val as object).length === 0) return false;
  if (typeof val === "string" && val.trim() === "") return false;
  return true;
}

function filterNonEmpty<T>(arr: T[]): T[] {
  return arr.filter(isNonEmpty);
}

function BudgetView({ data, config }: { data: Record<string, unknown>; config: typeof cardConfig.budget }) {
  const total = data.total_estimated as number | undefined;
  const tips = filterNonEmpty((data.savings_tips as string[]) || []);
  const breakdown = filterNonEmpty((data.budget_breakdown as Record<string, unknown>[]) || []);

  return (
    <div className="space-y-4">
      {total != null && (
        <div className={`flex items-center gap-2 rounded-xl px-4 py-3 ${config.accentBg} ${config.accentBorder} border`}>
          <DollarSign className={`w-5 h-5 ${config.accent}`} />
          <span className={`text-2xl font-bold ${config.accent}`}>
            {formatCurrency(total)}
          </span>
          <span className="text-sm text-text-secondary ml-1">estimated total</span>
        </div>
      )}

      {breakdown.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-2">
            Breakdown
          </h4>
          <div className="space-y-1.5">
            {breakdown.map((item, i) => {
              const rec = item as Record<string, unknown>;
              const category = (rec.category || rec.name || rec.item || Object.keys(rec)[0] || "Item") as string;
              const amount = (rec.amount || rec.cost || rec.estimated || rec[Object.keys(rec).find(k => typeof rec[k] === "number") || ""] || 0) as number;
              return (
                <div key={i} className="flex items-center justify-between py-1.5 px-3 rounded-lg bg-white/60">
                  <span className="text-sm text-text-primary capitalize">{category}</span>
                  <span className={`text-sm font-semibold ${config.accent}`}>
                    {typeof amount === "number" ? formatCurrency(amount) : String(amount)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {tips.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-2">
            Savings Tips
          </h4>
          <ul className="space-y-1.5">
            {tips.map((tip, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-text-primary">
                <span className={`mt-0.5 ${config.accent}`}>&#8226;</span>
                <span>{String(tip)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function AdventureView({ data, config }: { data: Record<string, unknown>; config: typeof cardConfig.adventure }) {
  const experiences = filterNonEmpty((data.unique_experiences as Record<string, unknown>[]) || []);
  const gems = filterNonEmpty((data.local_gems as string[]) || []);
  const offPath = data.off_beaten_path as string | undefined;

  return (
    <div className="space-y-4">
      {experiences.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-2">
            Unique Experiences
          </h4>
          <div className="space-y-2">
            {experiences.map((exp, i) => {
              const rec = exp as Record<string, unknown>;
              const name = (rec.name || rec.title || `Experience ${i + 1}`) as string;
              const desc = (rec.description || rec.details || rec.summary || "") as string;
              const whySpecial = (rec.why_special || rec.why || "") as string;
              return (
                <div key={i} className={`rounded-lg border ${config.accentBorder} bg-white/60 px-3 py-2.5`}>
                  <div className={`text-sm font-semibold ${config.accent}`}>{name}</div>
                  {desc && <div className="text-sm text-text-secondary mt-0.5">{desc}</div>}
                  {whySpecial && (
                    <div className="text-xs text-text-muted mt-1 italic">{whySpecial}</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {gems.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-2">
            Local Gems
          </h4>
          <ul className="space-y-1.5">
            {gems.map((gem, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-text-primary">
                <span className={`mt-0.5 ${config.accent}`}>&#8226;</span>
                <span>{typeof gem === "object" ? JSON.stringify(gem) : String(gem)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {offPath && isNonEmpty(offPath) && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-2">
            Off the Beaten Path
          </h4>
          <p className="text-sm text-text-primary leading-relaxed">{String(offPath)}</p>
        </div>
      )}
    </div>
  );
}

function LogisticsView({ data, config }: { data: Record<string, unknown>; config: typeof cardConfig.logistics }) {
  const schedule = filterNonEmpty((data.daily_schedule as Record<string, unknown>[]) || []);
  const transitTips = filterNonEmpty((data.transit_tips as string[]) || []);
  const timeOpt = data.time_optimization as string | undefined;

  return (
    <div className="space-y-4">
      {schedule.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-2">
            Daily Schedule
          </h4>
          <div className="space-y-2">
            {schedule.map((day, i) => {
              const rec = day as Record<string, unknown>;
              const dayLabel = (rec.day || rec.date || `Day ${i + 1}`) as string;
              const activities = (rec.activities || rec.items || rec.plan) as string[] | string | undefined;
              return (
                <div key={i} className={`rounded-lg border ${config.accentBorder} bg-white/60 px-3 py-2.5`}>
                  <div className={`text-sm font-semibold ${config.accent}`}>{dayLabel}</div>
                  {activities && (
                    <div className="text-sm text-text-secondary mt-1">
                      {Array.isArray(activities)
                        ? activities.map((a, j) => (
                            <div key={j} className="flex items-start gap-2 mt-0.5">
                              <span className={`mt-0.5 ${config.accent}`}>&#8226;</span>
                              <span>{String(a)}</span>
                            </div>
                          ))
                        : String(activities)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {transitTips.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-2">
            Transit Tips
          </h4>
          <ul className="space-y-1.5">
            {transitTips.map((tip, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-text-primary">
                <span className={`mt-0.5 ${config.accent}`}>&#8226;</span>
                <span>{String(tip)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {timeOpt && isNonEmpty(timeOpt) && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-text-secondary mb-2">
            Time Optimization
          </h4>
          <p className="text-sm text-text-primary leading-relaxed">{String(timeOpt)}</p>
        </div>
      )}
    </div>
  );
}

function StructuredContent({ type, data }: { type: TripCardProps["type"]; data: Record<string, unknown> }) {
  const config = cardConfig[type];
  switch (type) {
    case "budget":
      return <BudgetView data={data} config={config} />;
    case "adventure":
      return <AdventureView data={data} config={config} />;
    case "logistics":
      return <LogisticsView data={data} config={config} />;
  }
}

export default function TripCard({ type, content }: TripCardProps) {
  const [expanded, setExpanded] = useState(false);
  const config = cardConfig[type];
  const Icon = config.icon;

  const parsed = tryParsePythonDict(content.trim());

  return (
    <div
      className={`rounded-2xl border ${config.border} ${config.bg} overflow-hidden shadow-sm`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full px-4 py-3.5 text-left"
      >
        <div className="flex items-center gap-3">
          <div
            className={`flex items-center justify-center w-8 h-8 rounded-lg ${config.iconBg}`}
          >
            <Icon className={`w-4 h-4 ${config.iconColor}`} />
          </div>
          <span className={`text-sm font-semibold ${config.headerColor}`}>
            {config.label}
          </span>
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-text-muted" />
        ) : (
          <ChevronDown className="w-4 h-4 text-text-muted" />
        )}
      </button>
      <div
        className={`overflow-hidden transition-all duration-300 ease-in-out ${
          expanded ? "max-h-[2000px] opacity-100 overflow-y-auto" : "max-h-0 opacity-0"
        }`}
      >
        <div className="px-4 pb-4 text-sm text-text-primary leading-relaxed">
          {parsed ? (
            <StructuredContent type={type} data={parsed} />
          ) : (
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
