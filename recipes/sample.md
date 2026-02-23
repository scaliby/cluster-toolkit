# Sample Recipe

This is a comprehensive sample recipe demonstrating the capabilities of the `tools/recipes.py` runner. 
Recipes are executable Markdown files that can generate configurations, verify file outputs against golden snapshots, and run integration tests.

## 1. File Generation

Code blocks can be extracted into files within the temporary execution workspace using the `file` tag. This is typically used to define source code, configuration files, or scripts.

<!-- file: script.py -->
```python
import json
import sys

def main():
    with open('config/settings.json') as f:
        config = json.load(f)
    
    print(f"Running in {config['environment']} environment for {config['name']}.")
    
    # If the '--generate' flag is passed, write an output file
    if len(sys.argv) > 1 and sys.argv[1] == '--generate':
        with open('output.txt', 'w') as f:
            f.write(f"Generated snapshot output for {config['name']}\n")

if __name__ == '__main__':
    main()
```

You can define multiple files, and the runner will automatically create any necessary parent directories. Let's create a supplementary configuration file in a subfolder.

<!-- file: config/settings.json -->
```json
{
  "name": "Recipe Runner",
  "environment": "testing"
}
```

## 2. The Golden Phase

The `golden` phase is used for commands that generate, render, or modify files that we want to track in version control as a snapshot.
- When running `tools/recipes.py golden`, the resulting workspace file tree is compared against `recipes/goldens/sample/`. 
- When running `tools/recipes.py update`, the current workspace file tree replaces that golden snapshot.

<!-- phase: golden -->
```shell
# This script runs during 'golden' and 'update' modes.
echo "Generating files for the golden snapshot..."
python3 script.py --generate
echo "Golden phase preparation complete."
```

## 3. The Execution Phase

The `execution` phase is reserved for integration testing and actual operations. These blocks **only** run when the tool is invoked with the `run` mode. 

<!-- phase: execution -->
```shell
# This script ONLY runs during 'run' mode.
echo "Executing the main script..."
python3 script.py
echo "Execution successfully completed!"
```

## 4. Skipped Blocks

Sometimes you want to include code blocks in your documentation that should *not* be executed by the automated test runner (e.g., prerequisite installation commands, intentional errors, or hypothetical examples).

<!-- skip: true -->
```shell
# This block is completely ignored by the runner in all modes.
pip install imaginary-package
rm -rf / # Just kidding, this won't run!
```
