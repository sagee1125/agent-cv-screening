import { Badge } from "../ui/badge";
import type { JDParsedPayload } from "../../types";

interface SkillTagListProps {
  jdParsed: JDParsedPayload | null;
}

export function SkillTagList({ jdParsed }: SkillTagListProps) {
  const mustSkills = jdParsed?.mustSkills ?? [];
  const preferredSkills = jdParsed?.preferredSkills ?? [];

  if (!jdParsed || (mustSkills.length === 0 && preferredSkills.length === 0)) {
    return <p className="text-sm text-slate-500">No parsed skills yet.</p>;
  }

  return (
    <div className="space-y-4">
      <section className="space-y-2">
        <h4 className="text-sm font-semibold">Must Skills</h4>
        <div className="flex flex-wrap gap-2">
          {mustSkills.map((skill) => (
            <div key={skill.id} className="inline-flex items-center gap-1">
              <Badge
                variant="success"
                title={skill.sourceSentence}
                className="cursor-help"
              >
                {skill.name}
              </Badge>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <h4 className="text-sm font-semibold">Preferred Skills</h4>
        <div className="flex flex-wrap gap-2">
          {preferredSkills.map((skill) => (
            <div key={skill.id} className="inline-flex items-center gap-1">
              <Badge
                variant="info"
                title={skill.sourceSentence}
                className="cursor-help"
              >
                {skill.name}
              </Badge>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
