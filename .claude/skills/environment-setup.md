# Environment Setup Skill

This skill ensures the correct Python environment is set up for the Sentimental-Quant-Lab project.

## Description
Automatically sets up a Python virtual environment and installs all required dependencies from requirements.txt. This ensures consistent environments across different machines and sessions.

## Steps
1. Check if virtual environment exists, if not create it
2. Activate the virtual environment
3. Install/upgrade pip
4. Install all packages from requirements.txt
5. Verify installation by checking key packages

## Usage
To run this skill manually:
```bash
source venv/bin/activate  # activate the virtual environment
pip install -r requirements.txt
```

## Automation
To have this run automatically when starting work in this directory, you can add it to your CLAUDE.md or use Claude Code's hook system.

## Verification
After running, you can verify the environment with:
```bash
python -c "import pandas, requests, rich; print('✓ All key packages imported successfully')"
```

## Troubleshooting
If you encounter issues:
1. **ModuleNotFoundError**: Run `pip install -r requirements.txt` in the activated venv
2. **Wrong Python**: Ensure you're using `venv/bin/python` or have activated the venv
3. **Corrupted venv**: Delete the `venv/` directory and re-run setup

## Notes
- This skill is designed to be idempotent - running it multiple times is safe
- It will reuse existing virtual environments if they're valid
- If the virtual environment becomes corrupted, delete the venv/ directory and re-run
