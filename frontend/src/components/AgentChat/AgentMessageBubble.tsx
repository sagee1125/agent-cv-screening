// Renders one agent chat message bubble with optional action buttons.
import { Button } from "../ui/button";
import type { AgentActionButton, AgentMessage, AgentUiAction } from "../../types/agent";

interface AgentMessageBubbleProps {
  message: AgentMessage;
  onRunAction: (action: AgentUiAction) => void;
}

/** Shows a single user, assistant, or system chat message. */
export function AgentMessageBubble({
  message,
  onRunAction,
}: AgentMessageBubbleProps) {
  if (message.role === "user") {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
          You
        </p>
        <p className="whitespace-pre-wrap break-words">{message.text}</p>
      </div>
    );
  }

  if (message.role === "system") {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        {message.text}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-950">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-sky-700">
        Assistant
      </p>
      <p className="whitespace-pre-wrap break-words">{message.text}</p>
      {message.actions && message.actions.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {message.actions.map((actionButton: AgentActionButton) => (
            <Button
              key={`${actionButton.label}-${actionButton.action.type}`}
              type="button"
              size="sm"
              variant="outline"
              className="border-sky-300 bg-white text-sky-900 hover:bg-sky-100"
              onClick={() => onRunAction(actionButton.action)}
            >
              {actionButton.label}
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
