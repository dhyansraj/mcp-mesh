import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import TripCard from "./TripCard";

interface ChatBubbleProps {
  role: "user" | "assistant";
  content: string;
}

function parseSpecialistSections(text: string) {
  const parts: {
    type: "text" | "budget" | "adventure" | "logistics";
    content: string;
  }[] = [];
  const specialistMarker = "## Specialist Insights";
  const markerIdx = text.indexOf(specialistMarker);

  if (markerIdx === -1) {
    return [{ type: "text" as const, content: text }];
  }

  const mainContent = text.substring(0, markerIdx).trim();
  if (mainContent) {
    parts.push({ type: "text", content: mainContent });
  }

  const specialistText = text.substring(markerIdx + specialistMarker.length);

  const sections = specialistText.split(/### /);
  for (const section of sections) {
    const trimmed = section.trim();
    if (!trimmed) continue;

    if (trimmed.startsWith("Budget Analysis")) {
      parts.push({
        type: "budget",
        content: trimmed.replace("Budget Analysis", "").trim(),
      });
    } else if (trimmed.startsWith("Adventure Recommendations")) {
      parts.push({
        type: "adventure",
        content: trimmed.replace("Adventure Recommendations", "").trim(),
      });
    } else if (trimmed.startsWith("Logistics Plan")) {
      parts.push({
        type: "logistics",
        content: trimmed.replace("Logistics Plan", "").trim(),
      });
    }
  }

  return parts;
}

export default function ChatBubble({ role, content }: ChatBubbleProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-[85%] sm:max-w-[70%] bg-mesh-blue rounded-2xl rounded-br-md px-4 py-3 shadow-sm shadow-mesh-blue/20">
          <p className="text-sm text-white whitespace-pre-wrap leading-relaxed">
            {content}
          </p>
        </div>
      </div>
    );
  }

  const parts = parseSpecialistSections(content);

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[90%] sm:max-w-[80%] space-y-3">
        {parts.map((part, i) => {
          if (part.type === "text") {
            return (
              <div
                key={i}
                className="bg-bg-card rounded-2xl rounded-bl-md px-4 py-3 shadow-sm shadow-black/5"
              >
                <div className="text-sm text-text-primary leading-relaxed markdown-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {part.content}
                  </ReactMarkdown>
                </div>
              </div>
            );
          }
          return <TripCard key={i} type={part.type} content={part.content} />;
        })}
      </div>
    </div>
  );
}
