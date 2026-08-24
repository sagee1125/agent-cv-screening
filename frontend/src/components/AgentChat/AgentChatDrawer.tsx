// Slide-over agent chat drawer with job context and local intent handling.
import { MessageCircle, X } from "lucide-react";
import { useMemo } from "react";
import { useAgentChat } from "../../hooks/useAgentChat";
import type { AgentChatBridge, AgentChatContext } from "../../types/agent";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { AgentChatInput } from "./AgentChatInput";
import { AgentMessageList } from "./AgentMessageList";

interface AgentChatDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  context: AgentChatContext;
  bridge: AgentChatBridge;
}

/** Fixed right drawer that hosts the HR screening assistant chat UI. */
export function AgentChatDrawer({
  open,
  onOpenChange,
  context,
  bridge,
}: AgentChatDrawerProps) {
  const { messages, pending, send, runAction } = useAgentChat({
    context,
    bridge,
    enabled: open,
  });

  const jobLabel = useMemo(() => {
    if (!context.jobId) return "No job selected";
    return context.jobTitle ?? `Job ${context.jobId}`;
  }, [context.jobId, context.jobTitle]);

  return (
    <>
      {!open ? (
        <Button
          type="button"
          className="fixed bottom-6 right-6 z-40 h-12 gap-2 rounded-full px-5 shadow-lg"
          onClick={() => onOpenChange(true)}
        >
          <MessageCircle className="h-5 w-5" />
          Ask Agent
        </Button>
      ) : null}

      {open ? (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-slate-900/20 xl:bg-transparent"
          aria-label="Close agent chat overlay"
          onClick={() => onOpenChange(false)}
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full pointer-events-none"
        }`}
        aria-hidden={!open}
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 py-4">
          <div className="space-y-1">
            <h2 className="text-base font-semibold text-slate-900">
              Screening Assistant
            </h2>
            <p className="text-xs text-slate-500 line-clamp-2">{jobLabel}</p>
            <Badge variant="outline" className="text-[10px]">
              Phase 1 · local intents
            </Badge>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="shrink-0"
            onClick={() => onOpenChange(false)}
            aria-label="Close agent chat"
          >
            <X className="h-4 w-4" />
          </Button>
        </header>

        <AgentMessageList
          messages={messages}
          pending={pending}
          onRunAction={(action) => void runAction(action)}
        />
        <AgentChatInput
          hasJob={Boolean(context.jobId)}
          pending={pending}
          onSend={(text) => void send(text)}
        />
      </aside>
    </>
  );
}
