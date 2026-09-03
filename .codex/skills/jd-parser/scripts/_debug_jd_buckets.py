# Debug helper: print the final must/preferred buckets and education fields for one jd.txt.
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import REPO_ROOT  # noqa: E402

from jd_parser.service import JDParserService  # noqa: E402


async def main() -> None:
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    result = await JDParserService().parse_jd(text)
    data = result["structured_data"]
    print("parse_path:", result["parse_path"])
    for bucket in ("must_skills", "preferred_skills"):
        names = [item["canonical_skill"] for item in data[bucket]]
        print(f"{bucket} ({len(names)}): {names}")
    print("education:", data["education_requirement"])
    print("experience:", data["experience_requirement"])
    print("languages:", [(i["language"], i["level"], i["is_mandatory"]) for i in data["language_requirements"]])


if __name__ == "__main__":
    asyncio.run(main())
