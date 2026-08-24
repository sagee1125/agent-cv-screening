// Scrollable list of agent chat messages with a pending indicator.
import { Spinner } from "../ui/spinner";
import { AgentMessageBubble } from "./AgentMessageBubble";
import type { AgentMessage, AgentUiAction } from "../../types/agent";

interface AgentMessageListProps {
  messages: AgentMessage[];
  pending: boolean;
  onRunAction: (action: AgentUiAction) => void;
}

/** Renders the conversation history inside the agent drawer. */
export function AgentMessageList({
  messages,
  pending,
  onRunAction,
}: AgentMessageListProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-3">
      {messages.map((message) => (
        <AgentMessageBubble
          key={message.id}
          message={message}
          onRunAction={onRunAction}
        />
      ))}
      {pending ? (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Spinner className="h-4 w-4" />
          Thinking...
        </div>
      ) : null}
    </div>
  );
}
