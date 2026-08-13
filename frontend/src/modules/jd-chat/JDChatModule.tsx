import { useMemo, useState } from "react";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Textarea } from "../../components/ui/textarea";

interface JDMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
}

function createMessage(role: "user" | "assistant", text: string): JDMessage {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    role,
    text,
  };
}

export function JDChatModule() {
  const [jdText, setJdText] = useState("");
  const [messages, setMessages] = useState<JDMessage[]>([]);

  const canSubmit = useMemo(() => jdText.trim().length > 0, [jdText]);

  const onAnalyze = () => {
    if (!canSubmit) return;

    const userMessage = createMessage("user", jdText.trim());
    const assistantMessage = createMessage(
      "assistant",
      "JD text received. The frontend now uses an isolated conversation entry point and can be connected to a dedicated JDParserService for must/preferred tags, evidence sentences, and missing-field guidance."
    );

    setMessages((current) => [...current, userMessage, assistantMessage]);
    setJdText("");
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">JD Conversation and Review</CardTitle>
          <CardDescription>
            Paste a job description (JD) to enter a conversation-based review
            flow. This module is independent from CV parsing and is ready for a
            dedicated JD parser integration.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            value={jdText}
            onChange={(event) => setJdText(event.target.value)}
            placeholder="Paste full JD text, e.g. Must have Python..."
            className="min-h-40"
          />
          <div className="flex items-center gap-3">
            <Button type="button" onClick={onAnalyze} disabled={!canSubmit}>
              Send and Analyze
            </Button>
            <Badge variant="outline">Conversation Mode (JD Module)</Badge>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Conversation History</CardTitle>
          <CardDescription>
            This is the frontend interaction scaffold. The "Send and Analyze"
            action can be wired to a backend JD parser API next.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {messages.length === 0 ? (
            <p className="text-sm text-slate-500">
              No conversation yet. Paste a JD and send it first.
            </p>
          ) : (
            messages.map((message) => (
              <div
                key={message.id}
                className={
                  message.role === "assistant"
                    ? "rounded-md border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900"
                    : "rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800"
                }
              >
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-70">
                  {message.role === "assistant" ? "Assistant" : "You"}
                </p>
                <p className="whitespace-pre-wrap break-words">{message.text}</p>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
