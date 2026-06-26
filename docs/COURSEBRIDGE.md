# CourseBridge Selectors

CourseBridge is a Next.js/React app — no shadow DOM, standard selectors work fine.

- **File upload:** `input[type='file']` with `state="attached"` (input is hidden — never use default visible wait). Use `set_input_files()` directly, no clicking needed. Accept: `.pdf,.docx,.pptx,.txt,.md,.markdown,.text,.html,.htm,.csv,.tsv,.rtf,.json`
- **Template dropdown:** `button[data-slot="select-trigger"]` — defaults to "Course Syllabus", verify before clicking Convert
- **Convert button:** `button:has-text("Convert Document")`
- **Wait for completion:** poll `div.font-mono` for text containing `"Done!"`
- **Grab HTML output:** `pre.font-mono` → `.inner_text()` — more reliable than clipboard
- **Copy HTML button:** `button:has-text("Copy HTML")` — fallback only

---

# Course Outline Automator — Planned Tool

Playwright script to convert a course outline doc into a Brightspace-ready HTML page.

## Full flow
1. **Find outline** — searches Content tab for `syllabus` → `outline` → `guideline`; pauses for user confirmation before downloading
2. **PDF check** — if `.pdf`, converts locally with `pdf2docx`; if `.docx`, proceeds as-is
3. **CourseBridge conversion** — logs into `https://lms.harshsaw.ca/content-converter`, uploads `.docx`, sets template to "Course Syllabus", clicks Convert, grabs HTML
4. **Paste into Brightspace** — navigates to Welcome Module → "Course Syllabus" topic → opens TinyMCE editor → replaces HTML via Source Code dialog → saves

## How to run
```
python course_outline_automator.py            # full run
python course_outline_automator.py --dry-run  # download + convert only, no paste
```

## Config (top of file)
```python
BRIGHTSPACE_BASE = "https://learn.okanagancollege.ca"
COURSEBRIDGE_URL = "https://lms.harshsaw.ca/content-converter"
COURSEBRIDGE_EMAIL = ""
COURSEBRIDGE_PASSWORD = ""
OUTLINE_SEARCH_TERMS = ["syllabus", "outline", "guideline"]
SYLLABUS_TOPIC_NAME = "Course Syllabus"
```

## Key functions
| Function | What it does |
|---|---|
| `find_and_download_outline(page)` | Searches content tab, pauses for confirm, downloads file |
| `convert_pdf_to_docx(pdf_path)` | Converts PDF → docx locally via pdf2docx |
| `convert_with_coursebridge(file_path) -> str` | Uploads docx, returns HTML string |
| `paste_html_to_syllabus(page, html)` | Finds Course Syllabus topic, replaces HTML in TinyMCE |
| `run(dry_run)` | Main orchestrator |

## Notes
- `convert_with_coursebridge` is intentionally isolated — once an API endpoint exists, only its internals change; signature stays `(file_path) -> str`
- `--dry-run` stops before pasting; still downloads + converts so you can preview the HTML
- File does not exist yet (as of 2026-06-02). Spec in `COURSE_OUTLINE_AUTOMATOR_SPEC.md` (user's Downloads folder)
- Session files: `bs_session.json` (Brightspace), `cb_session.json` (CourseBridge)
