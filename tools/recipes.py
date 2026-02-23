#!/usr/bin/env python3

"""
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

     https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

"""
Cluster Toolkit Recipe Runner

Executes Markdown recipes for Cluster Toolkit by parsing code blocks,
generating files, and executing commands in a temporary workspace.

Modes:
- golden: Verifies that the recipe generation matches the golden snapshot.
- update: Updates the golden snapshot based on the current recipe generation.
- run: Executes the recipe in integration mode (deploys infrastructure).
"""

import dataclasses
import difflib
import filecmp
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from enum import Enum
from typing import Dict, List

class Mode(str, Enum):
    GOLDEN = "golden"
    UPDATE = "update"
    RUN = "run"

class Color:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    NC = "\033[0m"

@dataclasses.dataclass
class CodeBlock:
    command: str
    tags: Dict[str, str] = dataclasses.field(default_factory=dict)

def parse_tags(comment: str) -> Dict[str, str]:
    """Parses tags from HTML comment: <!-- key: value, key2: value -->"""
    content = comment.replace("<!--", "").replace("-->", "")
    parts = (p.split(":", 1) for p in content.split(",") if ":" in p)
    return {k.strip(): v.strip() for k, v in parts}

def parse_recipe(path: pathlib.Path) -> List[CodeBlock]:
    """Parses markdown file using pandoc to extract code blocks with tags."""
    try:
        proc = subprocess.run(
            ["pandoc", "-f", "markdown", "-t", "json", str(path)],
            capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"pandoc failed: {e.stderr or e}")
    except FileNotFoundError:
        raise RuntimeError("pandoc command not found.")

    blocks = []
    tags = {}
    
    for item in json.loads(proc.stdout).get("blocks", []):
        if item.get("t") == "RawBlock" and item["c"][0] == "html":
            content = item["c"][1].strip()
            if content.startswith("<!--"):
                tags = parse_tags(content)
                continue

        if item.get("t") == "CodeBlock" and tags.get("skip", "").lower() != "true":
            blocks.append(CodeBlock(command=item["c"][1], tags=tags))
            
        tags = {}
            
    return blocks

def setup_workspace(temp_dir: pathlib.Path, repo_root: pathlib.Path):
    """Symlinks project directories into the temporary workspace."""
    directories = ["modules", "tools", "community", "recipes", "examples"]
    for src in [repo_root / d for d in directories if (repo_root / d).exists()]:
        (temp_dir / src.name).symlink_to(src)

def generate_files(blocks: List[CodeBlock], temp_dir: pathlib.Path):
    """Writes files specified in code blocks with a 'file' tag."""
    files_to_create = [(b.tags["file"], b.command) for b in blocks if "file" in b.tags]

    for filename, content in files_to_create:
        path = temp_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

def execute_blocks(blocks: List[CodeBlock], temp_dir: pathlib.Path, run_phase: bool) -> bool:
    """Executes shell blocks for the given phase."""
    phase = "execution" if run_phase else "golden"
    raw_commands = [block.command for block in blocks if "file" not in block.tags and block.tags.get("phase", "execution") == phase]

    if len(raw_commands) <= 0:
        return True

    script_parts = ["set -e"]
    for command in raw_commands:
        if run_phase:
            sanitized = command.replace("'", "'\\''")
            script_parts.extend([
                "echo",
                f"echo '$ {sanitized}'",
                "echo"
            ])
        script_parts.append(command)

    full_script = "\n".join(script_parts)

    try:
        subprocess.run(
            full_script, shell=True, check=True, cwd=temp_dir,
            executable="/bin/bash", capture_output=not run_phase, text=True
        )
        return True
    except subprocess.CalledProcessError as e:
        return False

def destroy_deployments(temp_dir: pathlib.Path):
    """Destroys any terraform/gcluster deployments found in temp_dir."""
    deployments = (
        d for d in temp_dir.iterdir()
        if d.is_dir() and not d.is_symlink() and not d.name.startswith(".")
        if (d / ".gcluster").exists() or (d / "terraform").exists()
    )

    for deployment in deployments:
        subprocess.run(
            ["gcluster", "destroy", deployment.name, "--auto-approve"],
            cwd=temp_dir, capture_output=True
        )

def get_files(base: pathlib.Path) -> set[pathlib.Path]:
    """Recursively gets all file paths under base, relative to base."""
    if not base.exists():
        return set()
    return {
        f.relative_to(base) for f in base.rglob("*")
        if f.is_file() and not f.is_symlink() and not any(p.startswith(".") for p in f.relative_to(base).parts)
    }

def compare_dirs(golden: pathlib.Path, generated: pathlib.Path) -> List[str]:
    """Compares golden and generated directories, returning a git-like unified diff."""
    diffs = []
    for rel_path in sorted(get_files(golden) | get_files(generated)):
        g_path, gen_path = golden / rel_path, generated / rel_path
        
        g_lines = g_path.read_text().splitlines(keepends=True) if g_path.is_file() else []
        gen_lines = gen_path.read_text().splitlines(keepends=True) if gen_path.is_file() else []
        
        if g_lines != gen_lines:
            diffs.extend(difflib.unified_diff(
                g_lines, gen_lines,
                fromfile=f"a/{rel_path}" if g_path.is_file() else "/dev/null",
                tofile=f"b/{rel_path}" if gen_path.is_file() else "/dev/null"
            ))

    return diffs

def update_golden(temp_dir: pathlib.Path, golden_dir: pathlib.Path):
    """Copies generated files (excluding symlinks and hidden files) to golden directory."""
    if golden_dir.exists():
        shutil.rmtree(golden_dir)
    
    golden_dir.mkdir(parents=True)
    
    items_to_copy = (
        p for p in temp_dir.iterdir()
        if not p.is_symlink() and not p.name.startswith(".")
    )

    for item in items_to_copy:
        dest = golden_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

def run_recipe(path: str, mode: Mode, repo_root: pathlib.Path) -> bool:
    """Orchestrates the execution of a single recipe."""
    recipe_path = pathlib.Path(path).resolve()
    golden_dir = repo_root / "recipes" / "goldens" / recipe_path.stem

    print(f"{Color.YELLOW}{mode.value.title()}: {recipe_path.name}...{Color.NC} ", end="", flush=True)

    try:
        blocks = parse_recipe(recipe_path)
    except Exception as e:
        print(f"{Color.RED}FAIL{Color.NC}\n{e}")
        return False

    with tempfile.TemporaryDirectory(prefix=f"ctk-{recipe_path.stem}-") as tmp_str:
        temp_dir = pathlib.Path(tmp_str)
        setup_workspace(temp_dir, repo_root)
        generate_files(blocks, temp_dir)
        
        if not execute_blocks(
            blocks, 
            temp_dir, 
            run_phase=(mode == Mode.RUN)
        ):
            print(f"{Color.RED}FAIL{Color.NC}")
            return False

        if mode == Mode.RUN:
            destroy_deployments(temp_dir)
            print(f"{Color.GREEN}DONE{Color.NC}")
            return True

        if mode == Mode.UPDATE:
            update_golden(temp_dir, golden_dir)
            print(f"{Color.GREEN}UPDATED{Color.NC}")
            return True

        if mode == Mode.GOLDEN:
            if diffs := compare_dirs(golden_dir, temp_dir):
                print(f"{Color.RED}FAIL{Color.NC}")
                print("\n".join(diffs))
                return False
                
            print(f"{Color.GREEN}OK{Color.NC}")
            return True

    return False

def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <{'|'.join(m.value for m in Mode)}> <recipes...>")
        sys.exit(1)

    try:
        mode = Mode(sys.argv[1])
    except ValueError:
        print(f"Invalid mode: {sys.argv[1]}. Must be one of: {', '.join([m.value for m in Mode])}")
        sys.exit(1)

    repo_root = pathlib.Path(__file__).parent.parent.resolve()
    success = all(run_recipe(f, mode, repo_root) for f in sys.argv[2:])
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()