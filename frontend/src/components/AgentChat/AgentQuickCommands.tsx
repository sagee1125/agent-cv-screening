// Horizontal quick-command chips above the agent chat input.
import { Button } from "../ui/button";

/** One preset command shown as a quick-action chip. */
export interface AgentQuickCommand {
  id: string;
  label: string;
  text: string;
  requiresJob?: boolean;
}

/** Clickable shortcuts that map to local agent intents in agentService. */
export const AGENT_QUICK_COMMANDS: AgentQuickCommand[] = [
  { id: "help", label: "Help", text: "help" },
  { id: "parse-jd", label: "Parse JD", text: "parse jd", requiresJob: true },
  { id: "skills", label: "Skills", text: "skills", requiresJob: true },
  { id: "ranking", label: "Ranking", text: "show ranking", requiresJob: true },
  {
    id: "recalculate",
    label: "Recalculate",
    text: "recalculate",
    requiresJob: true,
  },
];

interface AgentQuickCommandsProps {
  hasJob: boolean;
  pending: boolean;
  onSelect: (text: string) => void;
}

/** Renders shortcut buttons that send preset agent commands on click. */
export function AgentQuickCommands({
  hasJob,
  pending,
  onSelect,
}: AgentQuickCommandsProps) {
  const commands = AGENT_QUICK_COMMANDS.filter(
    (command) => !command.requiresJob || hasJob
  );

  return (
    <div className="border-t border-slate-200 bg-slate-50 px-4 py-3">
      <p className="mb-2 text-xs font-medium text-slate-600">Quick commands</p>
      <div className="flex flex-wrap gap-2">
        {commands.map((command) => (
          <Button
            key={command.id}
            type="button"
            size="sm"
            variant="outline"
            className="h-8 bg-white text-xs"
            disabled={pending}
            onClick={() => onSelect(command.text)}
          >
            {command.label}
          </Button>
        ))}
      </div>
      {hasJob ? (
        <p className="mt-2 text-[11px] text-slate-500">
          Tip: type why [name] to explain a candidate&apos;s score.
        </p>
      ) : (
        <p className="mt-2 text-[11px] text-slate-500">
          Select a job post to unlock screening commands.
        </p>
      )}
    </div>
  );
}
