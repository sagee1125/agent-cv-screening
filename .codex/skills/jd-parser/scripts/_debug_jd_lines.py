# Debug helper: print what the JD parser actually reads for one jd.txt.
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import REPO_ROOT  # noqa: E402

from jd_parser.service import JDParserService  # noqa: E402


def main() -> None:
    jd_path = Path(sys.argv[1])
    text = jd_path.read_text(encoding="utf-8")
    svc = JDParserService()
    lowered = svc._clean_text(text)
    sections = svc._split_sections(lowered)
    for name, lines in sections.items():
        print(f"=== section {name}: {len(lines)} line(s)")
        for i, line in enumerate(lines):
            meta = svc._is_metadata_line(line)
            degree = svc._is_degree_field_line(line)
            cue = svc._line_has_skill_cue(line)
            ignore = svc._should_ignore_line(line)
            target, weight = svc._line_target_and_weight(name, line)
            print(f"  [{i}] len={len(line)} meta={meta} degree={degree} cue={cue} ignore={ignore} -> {target}/{weight}")
            print(f"       {line[:160]}")
            if degree:
                print(f"       fields={svc._fields_from_degree_line(line)}")
            cands = svc._extract_candidates_from_line(line)
            print(f"       candidates={cands}")


if __name__ == "__main__":
    main()
