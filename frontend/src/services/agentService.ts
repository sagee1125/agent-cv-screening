// Local intent processor for the HR agent chat (Phase 1: REST-backed, no orchestrator API).
import {
  getCandidateMatchDetail,
  getJobCandidates,
  parseJobJD,
  recalculateJob,
} from "./jobService";
import type {
  AgentActionButton,
  AgentChatContext,
  AgentMessage,
  AgentProcessResult,
  AgentUiAction,
} from "../types/agent";
import type { CandidateSummary } from "../types";

const USE_MOCK =
  import.meta.env.VITE_USE_MOCK === "true" ||
  import.meta.env.VITE_USE_MOCK === "1";

/** Creates a unique message id for chat bubbles. */
function createMessageId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Builds one assistant message with optional action buttons. */
function assistantMessage(
  text: string,
  actions?: AgentActionButton[]
): AgentMessage {
  return {
    id: createMessageId("assistant"),
    role: "assistant",
    text,
    actions,
  };
}

/** Builds one system status message. */
function systemMessage(text: string): AgentMessage {
  return { id: createMessageId("system"), role: "system", text };
}

/** Returns true when any keyword appears in the normalized user text. */
function matchesAny(text: string, keywords: string[]): boolean {
  return keywords.some((keyword) => text.includes(keyword));
}

/** Finds a candidate whose name or filename loosely matches the query. */
function findCandidateByQuery(
  candidates: CandidateSummary[],
  query: string
): CandidateSummary | null {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return null;

  return (
    candidates.find((candidate) => {
      const name = candidate.candidateName?.toLowerCase() ?? "";
      const file = candidate.originalFilename?.toLowerCase() ?? "";
      const email = candidate.candidateEmail?.toLowerCase() ?? "";
      return (
        name.includes(normalized) ||
        file.includes(normalized) ||
        email.includes(normalized) ||
        normalized.includes(name) ||
        normalized.includes(file)
      );
    }) ?? null
  );
}

/** Extracts a candidate name query from a "why" style message. */
function extractWhyQuery(text: string): string | null {
  const patterns = [
    /why\s+(?:is\s+)?(.+?)(?:\s+(?:lower|higher|ranked|score)|[?.!]|$)/i,
    /為什麼\s*(.+?)(?:[？?]|$)/,
    /為何\s*(.+?)(?:[？?]|$)/,
    /explain\s+(.+?)(?:[?.!]|$)/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match?.[1]) return match[1].trim();
  }
  return null;
}

/** Formats a ranked candidate list for the chat panel. */
function formatRankingSummary(candidates: CandidateSummary[]): string {
  const ranked = [...candidates]
    .filter((c) => c.recommendationRank != null || c.matchScore != null)
    .sort((a, b) => {
      const rankA = a.recommendationRank ?? 9999;
      const rankB = b.recommendationRank ?? 9999;
      if (rankA !== rankB) return rankA - rankB;
      return (b.matchScore ?? 0) - (a.matchScore ?? 0);
    });

  if (ranked.length === 0) {
    return "No scored candidates yet. Upload CVs and wait for matching to finish, or run recalculate.";
  }

  const lines = ranked.slice(0, 10).map((candidate) => {
    const rank = candidate.recommendationRank ?? "—";
    const score = candidate.matchScore ?? "—";
    const name = candidate.candidateName || candidate.originalFilename || "Unknown";
    const band = candidate.fitBand ?? "n/a";
    return `#${rank} ${name} — score ${score}, fit ${band}`;
  });

  return `Current ranking (top ${lines.length}):\n\n${lines.join("\n")}`;
}

/** Builds a short explanation from matching detail dimensions. */
function formatMatchExplanation(
  candidate: CandidateSummary,
  detailText: string
): string {
  const header = `Match summary for ${candidate.candidateName || candidate.originalFilename || "candidate"}:`;
  const scoreLine = `Total score: ${detailText}`;
  return `${header}\n\n${scoreLine}`;
}

/** Returns mock assistant replies when VITE_USE_MOCK is enabled. */
function processMockMessage(text: string, context: AgentChatContext): AgentProcessResult {
  const normalized = text.trim().toLowerCase();
  if (!context.jobId) {
    return {
      messages: [
        assistantMessage(
          "Select a job post from the left list first, then ask me to parse JD, show ranking, or explain a candidate."
        ),
      ],
      uiActions: [],
    };
  }

  if (matchesAny(normalized, ["help", "幫助", "說明"])) {
    return {
      messages: [
        assistantMessage(
          "Mock mode is on. Try:\n• parse jd / 解析 jd\n• show ranking / 排名\n• recalculate / 重新計算\n• why Alice / 為什麼 Alice"
        ),
      ],
      uiActions: [],
    };
  }

  return {
    messages: [
      assistantMessage(
        `[Mock] Received your message for job "${context.jobTitle ?? context.jobId}". Backend calls are skipped in mock mode. Turn off VITE_USE_MOCK to use live APIs.`
      ),
    ],
    uiActions: [{ type: "refresh_job" }],
  };
}

/** Processes one user message against live REST APIs using simple intents. */
async function processLiveMessage(
  text: string,
  context: AgentChatContext
): Promise<AgentProcessResult> {
  const normalized = text.trim().toLowerCase();
  const uiActions: AgentUiAction[] = [];

  if (!context.jobId) {
    return {
      messages: [
        assistantMessage(
          "Select a job post from the left list first. I can then parse its JD, show candidate ranking, recalculate scores, or explain why someone ranked where they did."
        ),
      ],
      uiActions: [],
    };
  }

  const jobId = context.jobId;

  if (matchesAny(normalized, ["help", "幫助", "說明", "commands"])) {
    return {
      messages: [
        assistantMessage(
          "You can ask me:\n• parse jd / 解析 jd — parse the current job description\n• show ranking / 排名 / shortlist — list ranked candidates\n• recalculate / 重新計算 — rerun matching\n• why Alice / 為什麼 Alice — explain a candidate's score\n• skills / 技能 — summarize parsed must/preferred skills"
        ),
      ],
      uiActions: [],
    };
  }

  if (
    matchesAny(normalized, [
      "parse jd",
      "parse job",
      "解析",
      "分析 jd",
      "parse description",
    ])
  ) {
    const jdText = context.jobDescription?.trim() ?? "";
    if (!jdText) {
      return {
        messages: [
          assistantMessage(
            "This job has no JD text yet. Paste the job description in the panel above, then ask me to parse it again."
          ),
        ],
        uiActions: [],
      };
    }

    const result = await parseJobJD(jobId, jdText);
    const mustCount = result.jdParsedJson.mustSkills.length;
    const prefCount = result.jdParsedJson.preferredSkills.length;
    uiActions.push({ type: "refresh_job" });
    return {
      messages: [
        assistantMessage(
          `JD parsed successfully.\n• Must skills: ${mustCount}\n• Preferred skills: ${prefCount}\n\nReview the Skill Tags section in the panel to confirm before screening CVs.`
        ),
      ],
      uiActions,
    };
  }

  if (
    matchesAny(normalized, [
      "ranking",
      "rank",
      "shortlist",
      "排名",
      "候選人",
      "candidates",
    ])
  ) {
    const response = await getJobCandidates(jobId, 1, 50);
    const summary = formatRankingSummary(response.items);
    const actions: AgentActionButton[] = response.items
      .filter((c) => c.recommendationRank != null)
      .slice(0, 3)
      .map((candidate) => ({
        label: `Open #${candidate.recommendationRank} ${candidate.candidateName || "candidate"}`,
        action: { type: "open_candidate", candidateId: candidate.candidateId },
      }));

    return {
      messages: [assistantMessage(summary, actions)],
      uiActions: [],
    };
  }

  if (
    matchesAny(normalized, ["recalculate", "重新計算", "rerun", "re-score", "rescore"])
  ) {
    await recalculateJob(jobId, "manual", "agent chat");
    uiActions.push({ type: "refresh_job" });
    return {
      messages: [
        assistantMessage(
          "Matching recalculation started. Refresh in a few seconds, then ask for ranking again."
        ),
      ],
      uiActions,
    };
  }

  if (matchesAny(normalized, ["skills", "技能", "must skill", "preferred"])) {
    const parsed = context.jdParsedJson;
    if (!parsed) {
      return {
        messages: [
          assistantMessage(
            "No parsed JD yet. Ask me to parse jd after you paste a job description."
          ),
        ],
        uiActions: [],
      };
    }
    const must = parsed.mustSkills.map((s) => s.name).join(", ") || "none";
    const pref = parsed.preferredSkills.map((s) => s.name).join(", ") || "none";
    return {
      messages: [
        assistantMessage(`Parsed skills for this job:\n\nMust: ${must}\nPreferred: ${pref}`),
      ],
      uiActions: [],
    };
  }

  const whyQuery = extractWhyQuery(text);
  if (whyQuery || matchesAny(normalized, ["why", "為什麼", "為何", "explain"])) {
    const query = whyQuery ?? normalized.replace(/^(why|explain|為什麼|為何)\s*/i, "").trim();
    const response = await getJobCandidates(jobId, 1, 50);
    const candidate = findCandidateByQuery(response.items, query);

    if (!candidate) {
      return {
        messages: [
          assistantMessage(
            "I could not find that candidate. Try show ranking first, then ask why [name] or click Open on a ranked row."
          ),
        ],
        uiActions: [],
      };
    }

    const detail = await getCandidateMatchDetail(jobId, candidate.candidateId);
    const dimensionLines = detail.radarDimensions
      .filter((d) => d.active && d.score != null)
      .map(
        (d) =>
          `• ${d.label}: ${d.score} (weight ${d.normalizedWeight.toFixed(2)}) — ${d.reasoning?.summary ?? "no summary"}`
      )
      .join("\n");

    const gaps =
      candidate.keyGaps?.length
        ? `\n\nKey gaps: ${candidate.keyGaps.join("; ")}`
        : "";
    const strengths =
      candidate.topStrengths?.length
        ? `\n\nStrengths: ${candidate.topStrengths.join("; ")}`
        : "";

    const actions: AgentActionButton[] = [
      {
        label: "Open full detail",
        action: { type: "open_candidate", candidateId: candidate.candidateId },
      },
    ];

    uiActions.push({ type: "open_candidate", candidateId: candidate.candidateId });

    return {
      messages: [
        assistantMessage(
          formatMatchExplanation(
            candidate,
            `${detail.matchScore ?? "—"} (fit ${detail.fitBand ?? "n/a"}, rank #${detail.recommendationRank ?? "—"})\n\n${dimensionLines}${gaps}${strengths}`
          ),
          actions
        ),
      ],
      uiActions,
    };
  }

  return {
    messages: [
      assistantMessage(
        "I didn't recognize that request. Try help for commands, or ask to parse jd, show ranking, recalculate, or why [candidate name]."
      ),
    ],
    uiActions: [],
  };
}

/** Dispatches one chat message to mock or live intent handlers. */
export async function processAgentMessage(
  text: string,
  context: AgentChatContext
): Promise<AgentProcessResult> {
  if (USE_MOCK) {
    return processMockMessage(text, context);
  }
  return processLiveMessage(text, context);
}

/** Welcome messages shown when the drawer opens for a job. */
export function buildWelcomeMessages(context: AgentChatContext): AgentMessage[] {
  if (!context.jobId) {
    return [
      systemMessage(
        "Select a job post to start. I can parse JDs, show rankings, and explain candidate scores."
      ),
    ];
  }

  const title = context.jobTitle ?? "this job";
  const hasJd = Boolean(context.jobDescription?.trim());
  const hasParsed = Boolean(context.jdParsedJson);

  return [
    systemMessage(`Assistant ready for "${title}".`),
    assistantMessage(
      hasParsed
        ? `JD is already parsed. Ask for ranking, recalculate, or why [name].`
        : hasJd
          ? "JD text is saved but not parsed yet. Say parse jd to extract skills."
          : "Paste a JD in the panel, then say parse jd to begin screening."
    ),
  ];
}
