"""The personal llm-wiki vault shared by every agent.

The vault is user data: it lives outside Git and outside the deploy copy. This
module only lays down the structure and the seed files that every agent reads
(`index.md` and `AGENTS.md`) plus the note templates. A file is written only
when it is missing, so notes an agent or the user already wrote are never
overwritten on a restart.
"""

import os
from pathlib import Path

from core.config import PROJECT_ROOT, WIKI_ROOT


WIKI_DIRECTORIES = ("inbox", "notes", "projects", "daily", "templates", "attachments")

WIKI_FILES = {
    "AGENTS.md": """---
title: Agent guide
tags: [meta]
---

# llm-wiki — guide for every agent

This vault is the personal knowledge base of this machine. Every agent (chat,
scheduled jobs, Discord and development agents) reads and writes here, and
relative tool paths plus `run_command` start in this folder.

## Rules

- Read `index.md` first, then only the notes a task needs.
- One topic per note. Permanent notes go in `notes/`, a project page goes in
  `projects/`, and a quick capture goes in `inbox/`.
- Name files in lowercase with hyphens (`thai-llm-notes.md`), never spaces.
  Thai text inside the note is fine.
- Start every note with the frontmatter from `templates/note.md` and update
  `updated:` whenever you change it.
- Link notes with `[[note-name]]`. Link every new note from `index.md` or from
  a project page so the graph has no orphans.
- Process `inbox/` regularly: move what matters into `notes/` or `projects/`,
  then delete it from the inbox.
- Daily notes live at `daily/YYYY-MM-DD.md` (template: `templates/daily.md`).
- Never delete knowledge. Set `status: archived` instead of removing a note.
- Never write API keys, passwords, tokens, private keys or other secrets into
  this vault.
""",
    "index.md": """---
title: llm-wiki
tags: [index]
---

# llm-wiki

สมุดความรู้ส่วนตัวของเครื่องนี้ — อ่านหน้านี้ก่อนเสมอ
Personal knowledge base of this machine — read this page first.

ทุก agent อ่านและเขียนในโฟลเดอร์นี้ กติกาอยู่ที่ [[AGENTS]]
Every agent reads and writes here; the rules live in [[AGENTS]].

## โครงสร้าง / Structure

| โฟลเดอร์ | ใช้ทำอะไร |
| --- | --- |
| `inbox/` | บันทึกด่วนที่ยังไม่ได้จัดระเบียบ / quick captures |
| `notes/` | โน้ตถาวรหนึ่งเรื่องต่อหนึ่งไฟล์ / permanent notes |
| `projects/` | หน้าโปรเจกต์ / one page per project |
| `daily/` | โน้ตรายวัน `YYYY-MM-DD.md` / daily notes |
| `templates/` | เทมเพลต / note templates |
| `attachments/` | รูปและไฟล์แนบ / images and files |

## โปรเจกต์ / Projects

_ยังไม่มี — เพิ่มลิงก์แบบ `[[projects/<ชื่อ>]]` ที่นี่_
_None yet — add `[[projects/<name>]]` links here._

## โน้ต / Notes

_ยังไม่มี — เพิ่มลิงก์แบบ `[[notes/<ชื่อ>]]` ที่นี่_
_None yet — add `[[notes/<name>]]` links here._

## กล่องรับ / Inbox

- เก็บของด่วนไว้ใน `inbox/` แล้วย้ายไป `notes/` หรือ `projects/` เมื่อจัดระเบียบแล้ว
- Keep quick captures in `inbox/` and move them to `notes/` or `projects/` once processed.
""",
    "templates/note.md": """---
title: "{{title}}"
created: "{{date}}"
updated: "{{date}}"
tags: []
status: active
---

# {{title}}

## สรุป / Summary

## รายละเอียด / Details

## ที่เกี่ยวข้อง / Related

-
""",
    "templates/project.md": """---
title: "{{title}}"
created: "{{date}}"
updated: "{{date}}"
tags: [project]
status: active
repo:
---

# {{title}}

## เป้าหมาย / Goal

## สถานะ / Status

## การตัดสินใจ / Decisions

## โน้ต / Notes

## ที่เกี่ยวข้อง / Related

-
""",
    "templates/daily.md": """---
title: "{{date}}"
created: "{{date}}"
tags: [daily]
---

# {{date}}

## งาน / Tasks

- [ ]

## โน้ต / Notes

## เก็บเพิ่ม / Captured
""",
}


def wiki_directory() -> Path:
    """Return the llm-wiki vault folder, creating it on first use."""
    root = Path(os.path.normpath(str(PROJECT_ROOT / WIKI_ROOT)))
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_wiki(root: Path | None = None) -> Path:
    """Create the vault structure and any seed file that is still missing."""
    target = Path(root) if root is not None else wiki_directory()
    target.mkdir(parents=True, exist_ok=True)
    for name in WIKI_DIRECTORIES:
        (target / name).mkdir(parents=True, exist_ok=True)
    for relative, content in WIKI_FILES.items():
        path = target / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return target
