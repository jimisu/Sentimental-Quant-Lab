#!/usr/bin/env python3
"""
Append latest commit info into CHANGELOG.md under a dated section.
Usage:
  python scripts/update_changelog.py       # use last commit
  python scripts/update_changelog.py --test "Commit message"  # test with custom subject
"""
import argparse
import subprocess
import datetime
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")


def get_last_commit():
    fmt = "%H%x1f%an%x1f%ae%x1f%ad%x1f%s%x1f%b"
    cmd = ["git", "log", "-1", f"--pretty=format:{fmt}", "--date=short"]
    p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"git log failed: {p.stderr.strip()}")
    raw = p.stdout
    parts = raw.split("\x1f")
    parts = [p.strip() for p in parts]
    # H, author, email, date, subject, body
    while len(parts) < 6:
        parts.append("")
    return {
        "hash": parts[0],
        "author": parts[1],
        "email": parts[2],
        "date": parts[3],
        "subject": parts[4],
        "body": parts[5],
    }


def build_entry(commit):
    date = commit.get("date") or datetime.date.today().isoformat()
    header = f"## [{date} AutoCommit]"
    lines = [header]
    lines.append(f"- **Commit**: {commit.get('subject')}")
    lines.append(f"- **Author**: {commit.get('author')} <{commit.get('email')}>")
    if commit.get('body'):
        body = commit.get('body').strip()
        for l in body.splitlines():
            lines.append(f"  {l}")
    lines.append("")
    return "\n".join(lines)


def insert_into_changelog(entry_text):
    if not os.path.exists(CHANGELOG):
        # create minimal changelog
        with open(CHANGELOG, "w", encoding="utf-8") as f:
            f.write("# 變更紀錄 (CHANGELOG)\n\n所有關於 Sentimental-Quant-Lab 專案的開發動態與版本更新將記錄於此。\n\n---\n\n")

    with open(CHANGELOG, "r", encoding="utf-8") as f:
        content = f.read()

    # find insertion point after the first '---' separator
    idx = content.find('\n---\n')
    if idx != -1:
        insert_pos = idx + len('\n---\n')
        new_content = content[:insert_pos] + entry_text + content[insert_pos:]
    else:
        # prepend
        new_content = entry_text + "\n" + content

    with open(CHANGELOG, "w", encoding="utf-8") as f:
        f.write(new_content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", help="Use provided simple subject as commit message")
    parser.add_argument("--run-hook", action="store_true", help="Run using git log to fetch last commit (default) ")
    args = parser.parse_args()

    if args.test:
        commit = {
            "hash": "",
            "author": os.getenv('GIT_AUTHOR_NAME', 'local'),
            "email": os.getenv('GIT_AUTHOR_EMAIL', ''),
            "date": datetime.date.today().isoformat(),
            "subject": args.test,
            "body": "",
        }
    else:
        try:
            commit = get_last_commit()
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    entry = build_entry(commit)
    insert_into_changelog(entry)
    print("CHANGELOG.md updated.")


if __name__ == '__main__':
    main()
