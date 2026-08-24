// TypeScript types for the HR agent chat UI and UI-bridge actions.
import type { JDParsedPayload } from "./index";

/** Actions the agent can request the host page to perform. */
export type AgentUiAction =
  | { type: "refresh_job" }
  | { type: "open_candidate"; candidateId: string }
  | { type: "select_job"; jobId: string };

/** Clickable action rendered inside an assistant message bubble. */
export interface AgentActionButton {
  label: string;
  action: AgentUiAction;
}

/** One chat message shown in the agent drawer. */
export type AgentMessage =
  | {
      id: string;
      role: "user";
      text: string;
    }
  | {
      id: string;
      role: "assistant";
      text: string;
      actions?: AgentActionButton[];
    }
  | {
      id: string;
      role: "system";
      text: string;
    };

/** Job-scoped context passed into the local intent processor. */
export interface AgentChatContext {
  jobId: string | null;
  jobTitle: string | null;
  jobDescription: string | null;
  jdParsedJson: JDParsedPayload | null;
}

/** Callbacks registered by the Job Board page for agent-driven navigation. */
export interface AgentChatBridge {
  refreshJob: () => Promise<void>;
  selectJob: (jobId: string) => void;
  openCandidate: (candidateId: string) => void;
}

/** Result returned after processing one user message. */
export interface AgentProcessResult {
  messages: AgentMessage[];
  uiActions: AgentUiAction[];
}
