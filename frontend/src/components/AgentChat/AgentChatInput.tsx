// Text input, quick commands, and send button for the agent chat drawer.
import { useState } from "react";
import { AgentQuickCommands } from "./AgentQuickCommands";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";

interface AgentChatInputProps {
  hasJob: boolean;
  pending: boolean;
  onSend: (text: string) => void;
}

/** Captures user prompts and submits them to the agent hook. */
export function AgentChatInput({
  hasJob,
  pending,
  onSend,
}: AgentChatInputProps) {
  const [value, setValue] = useState("");

  const handleSubmit = (text?: string) => {
    const trimmed = (text ?? value).trim();
    if (!trimmed || pending) return;
    onSend(trimmed);
    setValue("");
  };

  return (
    <div className="border-t border-slate-200 bg-white">
      <AgentQuickCommands
        hasJob={hasJob}
        pending={pending}
        onSelect={(text) => handleSubmit(text)}
      />
      <div className="space-y-2 p-4">
        <Textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Ask to parse JD, show ranking, or why [name]..."
          className="min-h-20 resize-none"
          disabled={pending}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSubmit();
            }
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-slate-500">
            Enter to send · Shift+Enter for newline
          </p>
          <Button
            type="button"
            onClick={() => handleSubmit()}
            disabled={pending || !value.trim()}
          >
            Send
          </Button>
        </div>
      </div>
    </div>
  );
}
