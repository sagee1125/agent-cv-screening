// Hook that manages agent chat messages, send flow, and UI-action dispatch.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  buildWelcomeMessages,
  processAgentMessage,
} from "../services/agentService";
import type {
  AgentChatBridge,
  AgentChatContext,
  AgentMessage,
  AgentUiAction,
} from "../types/agent";

interface UseAgentChatOptions {
  context: AgentChatContext;
  bridge: AgentChatBridge;
  enabled: boolean;
}

/** Runs local intent processing and dispatches bridge actions for the agent drawer. */
export function useAgentChat({ context, bridge, enabled }: UseAgentChatOptions) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [pending, setPending] = useState(false);
  const contextKey = `${context.jobId ?? "none"}:${context.jobTitle ?? ""}`;
  const lastContextKey = useRef<string | null>(null);

  // Reset welcome messages when the selected job changes while the drawer is open.
  useEffect(() => {
    if (!enabled) return;
    if (lastContextKey.current === contextKey) return;
    lastContextKey.current = contextKey;
    setMessages(buildWelcomeMessages(context));
  }, [context, contextKey, enabled]);

  /** Dispatches one UI action through the page bridge. */
  const dispatchUiActions = useCallback(
    async (actions: AgentUiAction[]) => {
      for (const action of actions) {
        if (action.type === "refresh_job") {
          await bridge.refreshJob();
        } else if (action.type === "open_candidate") {
          bridge.openCandidate(action.candidateId);
        } else if (action.type === "select_job") {
          bridge.selectJob(action.jobId);
        }
      }
    },
    [bridge]
  );

  /** Sends one user message and appends assistant replies. */
  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || pending) return;

      const userMessage: AgentMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        text: trimmed,
      };
      setMessages((current) => [...current, userMessage]);
      setPending(true);

      try {
        const result = await processAgentMessage(trimmed, context);
        setMessages((current) => [...current, ...result.messages]);
        await dispatchUiActions(result.uiActions);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Agent request failed.";
        setMessages((current) => [
          ...current,
          {
            id: `system-${Date.now()}`,
            role: "system",
            text: `Error: ${message}`,
          },
        ]);
      } finally {
        setPending(false);
      }
    },
    [context, dispatchUiActions, pending]
  );

  /** Runs one bridge action from an inline message button. */
  const runAction = useCallback(
    async (action: AgentUiAction) => {
      await dispatchUiActions([action]);
    },
    [dispatchUiActions]
  );

  return { messages, pending, send, runAction };
}
