// Renders parsed JD skill tags with hover cards that show each skill's source sentence.
import type { ComponentProps } from "react";
import { Badge } from "../ui/badge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "../ui/hover-card";
import type { JDParsedPayload } from "../../types";

interface SkillTagListProps {
  jdParsed: JDParsedPayload | null;
}

interface SourceBadgeProps {
  variant: ComponentProps<typeof Badge>["variant"];
  label: string;
  sourceSentence?: string | null;
}

// Renders the parsed JD skill sections (must, preferred, language) as tag badges.
export function SkillTagList({ jdParsed }: SkillTagListProps) {
  const mustSkills = jdParsed?.mustSkills ?? [];
  const preferredSkills = jdParsed?.preferredSkills ?? [];
  const languageRequirements = jdParsed?.languageRequirements ?? [];
  // const otherPreferences = [
  //   jdParsed?.visaRequirement,
  //   jdParsed?.educationRequirement,
  // ].filter(Boolean);

  if (!jdParsed || (mustSkills.length === 0 && preferredSkills.length === 0)) {
    return <p className="text-sm text-slate-500">No parsed skills yet.</p>;
  }

  return (
    <div className="space-y-4">
      <section className="space-y-2 flex flex-wrap gap-2 items-start text-sm font-semibold">
        Must Skills:
        <div className="flex flex-wrap gap-2">
          {mustSkills.map((skill) => (
            <SourceBadge
              key={skill.id}
              variant="success"
              label={skill.name}
              sourceSentence={skill.sourceSentence}
            />
          ))}
        </div>
      </section>

      <section className="space-y-2 flex flex-wrap gap-2 items-start text-sm font-semibold">
        Preferred Skills:
        <div className="flex flex-wrap gap-2">
          {preferredSkills.map((skill) => (
            <SourceBadge
              key={skill.id}
              variant="info"
              label={skill.name}
              sourceSentence={skill.sourceSentence}
            />
          ))}
        </div>
      </section>
      <section className="space-y-2 flex flex-wrap gap-2 items-start text-sm font-semibold">
        Language Requirements
        <div className="flex flex-wrap gap-2">
          {languageRequirements.map((language) => (
            <SourceBadge
              key={language.language}
              variant="language"
              label={language.language}
              sourceSentence={language.sourceSentence}
            />
          ))}
        </div>
      </section>
      {/* <section className="space-y-2">
        <h4 className="text-sm font-semibold">Other Preferences</h4>
        <div className="flex flex-wrap gap-2">
          {otherPreferences.map((preference) => (
            <SourceBadge variant="language" label={preference?. ?? ""} sourceSentence={preference?.sourceSentence ?? ""} />
          ))}
        </div>
      </section> */}
    </div>
  );
}

// Renders a badge that reveals its source sentence in a hover card when available.
function SourceBadge({ variant, label, sourceSentence }: SourceBadgeProps) {
  if (!sourceSentence) {
    return <Badge variant={variant}>{label}</Badge>;
  }

  return (
    <HoverCard openDelay={200} closeDelay={200}>
      <HoverCardTrigger
        tabIndex={0}
        className="rounded-full no-underline outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
      >
        <Badge variant={variant} className="cursor-help">
          {label}
        </Badge>
      </HoverCardTrigger>
      <HoverCardContent
        side="bottom"
        align="start"
        sideOffset={12}
        className="w-96 text-xs leading-relaxed"
      >
        <p>{sourceSentence}</p>
      </HoverCardContent>
    </HoverCard>
  );
}
