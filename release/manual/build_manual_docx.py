#!/usr/bin/env python3
"""Build the CV Screening user setup manual as a Word .docx (python-docx).

This is the manual HR receives. The script writes it straight to the Desktop,
where the owner adds the screenshots and hands it over; the file is not part of
the release zip.

Run it with the managed Python, NOT the repo venv - python-docx lives in the
managed environment:

    "C:/Users/User/.workbuddy-ai/binaries/python/envs/default/Scripts/python.exe" \
        release/manual/build_manual_docx.py

    ... --out <path>    write somewhere other than the Desktop copy

`VERSION` below must match the release the manual describes (it is printed under
the title); it is not read from the zip, because the manual usually goes out
slightly before or after the build.

Slimmed rewrite (2026-10-05): 7 sections instead of 13. The previous version
narrated how the installer works internally (its private Python, the engine
environment, the configuration file it writes) and stated the internal-site
requirements twice. A user manual only needs what the reader has to DO, so the
internals are gone, the duplicated checklist is stated once, and the
JES_SITE_MODE switch is demoted to an "advanced" note at the end.

Real Heading 1/2 styles so the navigation pane and a TOC work, screenshot
placeholders in italic grey for the owner to replace with images.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

OUT = Path(r"C:\Users\User\Desktop\CV-Screening-User-Setup-Manual.docx")
GREY = RGBColor(0x80, 0x80, 0x80)
MONO = "Consolas"
VERSION = "1.2.6"

STORE_URL = "https://chromewebstore.google.com/detail/kimi/fldmhceldgbpfpkbgopacenieobmligc"
KIMI_URL = "https://www.kimi.com/products/kimi-browser-extension"

# ('kind', payload) — kinds: h1 h2 p bullets numbers code ph pagebreak
BLOCKS: list[tuple[str, object]] = [
    ("h1", "1. Before You Start"),
    ("p", "Please have these ready:"),
    ("bullets", [
        "The setup file **CV-Screening-Setup.zip** we sent you",
        "Your own personal API key (sent to you separately)",
        "An internet connection",
        "WorkBuddy installed on this computer",
        "Google Chrome, with the **Kimi browser extension** added — needed for internal jobs "
        "(if you do not have it yet, section 5 has the download links)",
    ]),
    ("p", "You do not need to install anything else, and you do not need administrator rights. "
          "The package is already set up for the University's internal job pages, so there is "
          "nothing to configure."),

    ("h1", "2. Install"),
    ("numbers", [
        "Unzip **CV-Screening-Setup.zip** into your **Downloads** folder, and keep the folder name "
        "**CV-Screening-Setup**.",
        "Open the folder and double-click **setup.bat** (Windows) or **setup.command** (Mac).",
        "Paste your personal API key when the installer asks for it, then press Enter.",
        "Wait until it says **Install complete.**",
        "Quit WorkBuddy completely, open it again, and go to **Experts → My Experts → Vera**.",
    ]),
    ("ph", "the downloaded zip and the extracted CV-Screening-Setup folder side by side"),
    ("ph", "setup.bat on Windows / setup.command on Mac, inside the extracted folder"),
    ("ph", "the installer window asking for the personal API key"),
    ("ph", "the two success lines at the end of the installation"),
    ("ph", "the Experts menu open, with My Experts and Vera visible"),
    ("bullets", [
        "The key stays hidden while you type or paste it. That is normal.",
        "Windows: if a security warning appears, choose **Open** or **Run**.",
        "Mac: if macOS blocks the file, right-click it once, choose **Open**, and confirm.",
        "The first run downloads about 50 MB and takes a few minutes. Do not close the window "
        "while it is working, and do not run the installer from inside the zip file.",
    ]),

    ("pagebreak", None),
    ("h1", "3. Screen a Job"),
    ("p", "Before you send anything, open the PolyU JES internal pages in Chrome and sign in "
          "until you are inside the system. Then open Vera and send a real internal Ref. No.:"),
    ("code", "screen Ref.No xxxxxxxxx"),
    ("p", "Replace **xxxxxxxxx** with a real Ref. No. from the internal PolyU JES system — or paste "
          "the link to that job's records page. Screening does not start until you are signed in "
          "on that web page."),
    ("ph", "a screening request typed into the Vera chat window"),
    ("p", "**For internal University jobs, four things must be true while the screening runs:**"),
    ("bullets", [
        "Chrome is open in a **normal window**, not Incognito / InPrivate",
        "the **Kimi browser extension** is enabled — check **chrome://extensions**",
        "you are signed in at **https://jobs.polyu.edu.hk/internal** (the public homepage is not enough)",
        "the computer is on the campus network or connected to the University VPN",
    ]),
    ("ph", "chrome://extensions showing the Kimi extension enabled"),
    ("p", "Vera checks these before the first screening and tells you which one is missing; nothing "
          "is screened until they all pass. You are never asked for a password, a cookie or a "
          "token in the chat."),

    ("h1", "4. Where the Results Are"),
    ("p", "When a screening finishes, the reports are saved on your Desktop in the folder "
          "**workbuddy-cv-screen** — one folder per job reference number."),
    ("ph", "the workbuddy-cv-screen folder on the Desktop, with a job folder inside"),
    ("p", "Each job folder contains:"),
    ("bullets", [
        "a ranking overview of all applicants",
        "one report per applicant",
        "the data needed to check for new applications later",
    ]),
    ("p", "Applicants appear as application numbers only — never names, emails or phone numbers."),

    ("pagebreak", None),
    ("h1", "5. If Something Goes Wrong"),
    ("h2", "The installer window closes immediately"),
    ("p", "Run it from a command line so the message stays visible."),
    ("p", "**Windows** — open Command Prompt and run:"),
    ("code", 'cd /d "%USERPROFILE%\\Downloads\\CV-Screening-Setup"'),
    ("code", "setup.bat"),
    ("p", "**Mac** — open Terminal and run:"),
    ("code", "cd ~/Downloads/CV-Screening-Setup && bash setup.command"),

    ("h2", "The installation cannot download something"),
    ("p", "Check the internet connection and run the installer again. Make sure the setup folder "
          "has not been moved or partly deleted."),

    ("h2", "Vera does not appear in WorkBuddy"),
    ("p", "Quit WorkBuddy completely and open it again, then look in **Experts → My Experts**. If "
          "Vera is still missing, run the setup installer again."),

    ("h2", "Vera says the Kimi extension is not installed"),
    ("p", "Install it, then ask again. Either link works:"),
    ("code", STORE_URL),
    ("code", KIMI_URL),
    ("p", "The second link is Kimi's own page — use it if the Chrome Web Store will not open."),

    ("h2", "Vera says the extension is switched off"),
    ("p", "Open **chrome://extensions** and switch **Kimi** on, then accept the permission prompt."),

    ("h2", "A screening fails with a sign-in or authentication error"),
    ("p", "Check the four points in section 3, then restart WorkBuddy and try again."),

    ("h2", "Nothing starts after an update"),
    ("p", "Quit WorkBuddy, open it again, and send the request once more."),
    ("p", "If you need help, tell us the job reference number, roughly what time it was, and what "
          "Vera said. Please never include your API key or applicant CV files."),

    ("h1", "6. Good to Know"),
    ("bullets", [
        "**Updates are automatic.** The expert looks for a new version before the first screening "
        "of a conversation and installs it quietly. Your API key, your saved conditions and your "
        "existing reports are kept. You can also update by hand: **update_engine.cmd** (Windows) "
        "or **update_engine.command** (Mac).",
        "**You can delete the setup files** once Vera appears in WorkBuddy and a screening has "
        "worked: both the downloaded zip and the extracted CV-Screening-Setup folder. Keep the "
        "installed **agent-cv-screening** folder — that is the working installation.",
        "**Your key and your data are yours.** Use only your own API key, and never paste it into "
        "a chat message, an email or a screenshot. The reports are confidential HR information — "
        "do not share them outside the authorised HR workflow.",
    ]),
    ("h2", "Demo mode (for testing or demonstrations only)"),
    ("p", "To practise on the public demo site instead of real jobs, open the **.env** file inside "
          "the installed **agent-cv-screening** folder (Notepad on Windows, TextEdit on Mac), "
          "change the site line to **JES_SITE_MODE=0**, save, and restart WorkBuddy. Change it back "
          "to **JES_SITE_MODE=1** to return to the internal job pages. Most users never need this."),
    ("ph", "the .env file open, with the JES_SITE_MODE line visible"),

    ("h1", "7. Quick Start"),
    ("numbers", [
        "Download the setup package and unzip it into **Downloads**.",
        "Double-click **setup.bat** (Windows) or **setup.command** (Mac).",
        "Paste your personal API key when asked.",
        "Wait for **Install complete.**",
        "Quit WorkBuddy, open it again, then open **Vera**.",
        "In Chrome, open the PolyU JES internal pages and sign in until you are inside the system.",
        "Send: **screen Ref.No xxxxxxxxx** — a real Ref. No. from that internal system.",
        "The reports appear on your Desktop in **workbuddy-cv-screen**.",
    ]),
]

BOLD = re.compile(r"\*\*(.+?)\*\*")


# The "List Number" style hardcodes one numId, and numbering.xml carries no startOverride, so
# every numbered list in the document would share a single counter - the Quick Start would come
# out numbered 6..12 after the install steps. Each list therefore gets its own <w:num> that points
# at the same abstract numbering with a startOverride of 1.
def new_numbering_instance(doc, abstract_id: str = "7") -> int:
    numbering = doc.part.numbering_part.element
    used = [int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))]
    num_id = max(used) + 1
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    ref = OxmlElement("w:abstractNumId")
    ref.set(qn("w:val"), abstract_id)
    num.append(ref)
    override = OxmlElement("w:lvlOverride")
    override.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:startOverride")
    start.set(qn("w:val"), "1")
    override.append(start)
    num.append(override)
    numbering.append(num)
    return num_id


# Attach that numbering to one paragraph, inserted right after w:pStyle (the order inside w:pPr is
# fixed by the schema, so appending blindly could produce an invalid document).
def apply_numbering(paragraph, num_id: int) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    numPr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    nid = OxmlElement("w:numId")
    nid.set(qn("w:val"), str(num_id))
    numPr.append(ilvl)
    numPr.append(nid)
    pStyle = pPr.find(qn("w:pStyle"))
    if pStyle is not None:
        pStyle.addnext(numPr)
    else:
        pPr.insert(0, numPr)


def add_runs(paragraph, text: str, *, italic: bool = False, grey: bool = False,
             mono: bool = False, size: float | None = None, bold_all: bool = False) -> None:
    pos = 0
    for match in BOLD.finditer(text):
        if match.start() > pos:
            _run(paragraph, text[pos:match.start()], italic, grey, mono, size, bold_all)
        _run(paragraph, match.group(1), italic, grey, mono, size, True)
        pos = match.end()
    if pos < len(text):
        _run(paragraph, text[pos:], italic, grey, mono, size, bold_all)


def _run(paragraph, text, italic, grey, mono, size, bold) -> None:
    if not text:
        return
    run = paragraph.add_run(text)
    run.italic = italic
    run.bold = bold
    if grey:
        run.font.color.rgb = GREY
    if mono:
        run.font.name = MONO
    if size:
        run.font.size = Pt(size)


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("Page ")
    run.font.size = Pt(9)
    run.font.color.rgb = GREY
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    paragraph._p.append(fld)


def build(out: Path = OUT) -> Path:
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.15

    section = doc.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, attr, Inches(1))

    title = doc.add_paragraph("CV Screening Tool", style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_runs(subtitle, "User Setup Manual", size=16, bold_all=True)
    version = doc.add_paragraph()
    version.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_runs(version, f"For Windows and macOS  ·  version {VERSION}", size=10.5, grey=True)

    for kind, payload in BLOCKS:
        if kind == "h1":
            heading = doc.add_heading(str(payload), level=1)
            heading.paragraph_format.keep_with_next = True
        elif kind == "h2":
            heading = doc.add_heading(str(payload), level=2)
            heading.paragraph_format.keep_with_next = True
        elif kind == "p":
            add_runs(doc.add_paragraph(), str(payload))
        elif kind == "bullets":
            for item in payload:  # type: ignore[union-attr]
                add_runs(doc.add_paragraph(style="List Bullet"), str(item))
        elif kind == "numbers":
            num_id = new_numbering_instance(doc)
            for item in payload:  # type: ignore[union-attr]
                para = doc.add_paragraph(style="List Number")
                apply_numbering(para, num_id)
                add_runs(para, str(item))
        elif kind == "code":
            para = doc.add_paragraph()
            para.paragraph_format.space_after = Pt(4)
            add_runs(para, str(payload), mono=True, size=10.5, bold_all=True)
        elif kind == "ph":
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_runs(para, f"[SCREENSHOT: {payload}]", italic=True, grey=True, size=10.5)
        elif kind == "pagebreak":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    add_page_number(section.footer.paragraphs[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the CV Screening user setup manual (.docx).")
    parser.add_argument("--out", type=Path, default=OUT, help=f"Output path (default: {OUT})")
    args = parser.parse_args()

    path = build(args.out)
    doc = Document(str(path))
    words = sum(len(p.text.split()) for p in doc.paragraphs)
    h1 = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    h2 = [p.text for p in doc.paragraphs if p.style.name == "Heading 2"]
    ph = [p.text for p in doc.paragraphs if p.text.startswith("[SCREENSHOT:")]
    print(f"saved: {path}  ({path.stat().st_size} bytes)")
    print(f"words: {words} | Heading 1: {len(h1)} | Heading 2: {len(h2)} | placeholders: {len(ph)}")
    print("sections:", h1)
