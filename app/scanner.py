import os
from pathlib import Path
from dataclasses import dataclass, field
from app.parser import parse_source, FileFacts, detect_language_from_path

DEFAULT_IGNORES = {
    ".git", "venv", ".venv", "__pycache__", "node_modules", 
    ".idea", ".vscode", "build", "dist", ".pytest_cache"
}

@dataclass
class ProjectSummary:
    total_files: int = 0
    total_loc: int = 0
    total_risky_calls: int = 0
    file_facts: list[FileFacts] = field(default_factory=list)


def scan_directory(
    root_dir: str | Path, 
    ignored_dirs: set[str] = DEFAULT_IGNORES
) -> ProjectSummary:
    root_path = Path(root_dir)
    summary = ProjectSummary()

    if not root_path.exists():
        raise ValueError(f"Belirtilen dizin bulunamadı: {root_dir}")

    for current_root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]

        for file_name in files:
            file_path = Path(current_root) / file_name
            
            # Yolu string (düz metin) türüne garantiye alıyoruz
            str_path = str(file_path.as_posix())
            lang = detect_language_from_path(str_path)
            if not lang:
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    code = f.read()

                facts = parse_source(
                    source=code, 
                    path=str_path, 
                    language=lang
                )
                
                summary.file_facts.append(facts)
                summary.total_files += 1
                summary.total_loc += facts.loc
                summary.total_risky_calls += len([c for c in facts.calls if c.risky])

            except Exception:
                continue

    return summary