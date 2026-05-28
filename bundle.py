import argparse
import os
from datetime import datetime
from pathlib import Path


IGNORE_DIR_NAMES = {
    ".git",
    ".idea",
    ".vscode",
    ".codex",
    ".nexus",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",

    "node_modules",
    "vendor",
    "venv",
    ".venv",
    "env",
    ".env",
    "site-packages",

    ".postgress-data",
    ".postgres-data",
    "postgres-data",
    "postgres_data",
    "pgdata",

    "bundle_builders",
    "context",
    "nexus-pbund",
    "output",
    "pbund",

    "dist",
    "build",
    "coverage",
    ".next",
    ".nuxt",
    ".turbo",
    ".parcel-cache",
    "storage",
    "logs",
    "tmp",
    "temp",
    "cache",
}

IGNORE_FILE_NAMES = {
    "scratch.txt",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".DS_Store",
    "Thumbs.db",

    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "composer.lock",
    "poetry.lock",
    "Pipfile.lock",
}

TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".html",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".gitignore",
    ".dockerignore",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".sql",
    ".php",
    ".blade.php",
    ".xml",
    ".csv",
}

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".svg",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".pyo",
    ".class",
    ".jar",
    ".war",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
}


def normalize_path(path):
    return str(path).replace("\\", "/")


def path_is_inside(path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def should_ignore_dir(path, root, output_dir):
    name = path.name

    if name in IGNORE_DIR_NAMES:
        return True

    if output_dir and path.resolve() == output_dir.resolve():
        return True

    try:
        relative = path.relative_to(root)
    except ValueError:
        return True

    for part in relative.parts:
        if part in IGNORE_DIR_NAMES:
            return True

    return False


def should_ignore_file(path, root, output_file, output_dir, max_file_size_kb):
    if path.name in IGNORE_FILE_NAMES:
        return True

    if output_file and path.resolve() == output_file.resolve():
        return True

    if output_dir and path_is_inside(path, output_dir):
        return True

    try:
        relative = path.relative_to(root)
    except ValueError:
        return True

    for part in relative.parts:
        if part in IGNORE_DIR_NAMES:
            return True

    suffix = path.suffix.lower()

    if suffix in BINARY_EXTENSIONS:
        return True

    if suffix not in TEXT_EXTENSIONS and path.name.lower() not in {
        "dockerfile",
        "makefile",
        "readme",
        "license",
        "procfile",
    }:
        return True

    try:
        if path.stat().st_size > max_file_size_kb * 1024:
            return True
    except OSError:
        return True

    return False


def read_file(path):
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            return "[READ ERROR] {}".format(exc)

    return "[SKIPPED UNREADABLE FILE]"


def collect_files(root, output_file, max_file_size_kb):
    output_dir = output_file.parent.resolve()
    files = []

    for current_root, dir_names, file_names in os.walk(root):
        current_path = Path(current_root).resolve()

        dir_names[:] = [
            dir_name
            for dir_name in dir_names
            if not should_ignore_dir(
                current_path / dir_name,
                root,
                output_dir,
            )
        ]

        for file_name in file_names:
            file_path = (current_path / file_name).resolve()

            if should_ignore_file(
                file_path,
                root,
                output_file,
                output_dir,
                max_file_size_kb,
            ):
                continue

            files.append(file_path)

    return sorted(files)


def build_tree(files, root):
    lines = []

    for file_path in files:
        relative = file_path.relative_to(root)
        depth = len(relative.parts) - 1
        lines.append("{}- {}".format("  " * depth, normalize_path(relative)))

    return "\n".join(lines)


def dump_codebase(root_dir, output_path, max_file_size_kb):
    root = Path(root_dir).resolve()
    output_file = Path(output_path)

    if not output_file.is_absolute():
        output_file = (root / output_file).resolve()

    output_file.parent.mkdir(parents=True, exist_ok=True)

    files = collect_files(
        root=root,
        output_file=output_file,
        max_file_size_kb=max_file_size_kb,
    )

    lines = [
        "# Nexus Codebase Dump",
        "",
        "- Generated at: `{}`".format(datetime.now().isoformat(timespec="seconds")),
        "- Root: `{}`".format(normalize_path(root)),
        "- Output file: `{}`".format(normalize_path(output_file)),
        "- Files included: `{}`".format(len(files)),
        "- Max file size: `{} KB`".format(max_file_size_kb),
        "",
        "## Hard ignored directories",
        "",
        "```text",
        "\n".join(sorted(IGNORE_DIR_NAMES)),
        "```",
        "",
        "## Hard ignored files",
        "",
        "```text",
        "\n".join(sorted(IGNORE_FILE_NAMES)),
        "```",
        "",
        "## Project tree",
        "",
        "```text",
        build_tree(files, root),
        "```",
        "",
        "## File contents",
        "",
    ]

    for file_path in files:
        relative = normalize_path(file_path.relative_to(root))
        suffix = file_path.suffix.lower().replace(".", "") or "text"
        content = read_file(file_path)

        lines.extend([
            "### `{}`".format(relative),
            "",
            "```{}".format(suffix),
            content.rstrip(),
            "```",
            "",
        ])

    output_file.write_text("\n".join(lines), encoding="utf-8")

    return output_file, len(files)


def main():
    parser = argparse.ArgumentParser(description="Safe Nexus codebase dumper")
    parser.add_argument("command", choices=["dump"])
    parser.add_argument("--dir", default=".")
    parser.add_argument("--output", default="output/nexus_codebase_dump.md")
    parser.add_argument("--max-file-size-kb", type=int, default=256)

    args = parser.parse_args()

    if args.command == "dump":
        output_file, count = dump_codebase(
            root_dir=args.dir,
            output_path=args.output,
            max_file_size_kb=args.max_file_size_kb,
        )

        print("[*] Dump created: {}".format(output_file))
        print("[*] Files included: {}".format(count))


if __name__ == "__main__":
    main()