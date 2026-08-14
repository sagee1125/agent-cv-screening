import { Badge } from "../ui/badge";
import type { JDParsedPayload } from "../../types";

interface SkillTagListProps {
  jdParsed: JDParsedPayload | null;
}

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
            <Badge
              variant="success"
              title={skill.sourceSentence}
              className="cursor-help"
            >
              {skill.name}
            </Badge>
          ))}
        </div>
      </section>

      <section className="space-y-2 flex flex-wrap gap-2 items-start text-sm font-semibold">
        Preferred Skills:
        <div className="flex flex-wrap gap-2">
          {preferredSkills.map((skill) => (
            <Badge
              variant="info"
              title={skill.sourceSentence}
              className="cursor-help"
            >
              {skill.name}
            </Badge>
          ))}
        </div>
      </section>
      <section className="space-y-2 flex flex-wrap gap-2 items-start text-sm font-semibold">
        Language Requirements
        <div className="flex flex-wrap gap-2">
          {languageRequirements.map((language) => (
            <Badge
              variant="language"
              title={language.sourceSentence}
              className="cursor-help"
            >
              {language.language}
            </Badge>
          ))}
        </div>
      </section>
      {/* <section className="space-y-2">
        <h4 className="text-sm font-semibold">Other Preferences</h4>
        <div className="flex flex-wrap gap-2">
          {otherPreferences.map((preference) => (
            <Badge variant="language" title={preference?.sourceSentence ?? ""} className="cursor-help">
              {preference?. ?? ""}
            </Badge>
          ))}
        </div>
      </section> */}
    </div>
  );
}
