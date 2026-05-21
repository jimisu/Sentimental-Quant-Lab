#!/usr/bin/env python3
"""
Environment setup script for Sentimental-Quant-Lab.
This script ensures the virtual environment is properly set up with all dependencies.
"""
import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, cwd=None):
    """Run a command and return success status."""
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error running '{cmd}': {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"Exception running '{cmd}': {e}")
        return False

def main():
    print("Setting up Sentimental-Quant-Lab environment...")

    # Get the project root directory
    project_root = Path(__file__).parent.absolute()
    venv_path = project_root / "venv"

    # Check if virtual environment exists
    if not venv_path.exists():
        print("Creating virtual environment...")
        if not run_command(f"{sys.executable} -m venv venv", cwd=project_root):
            print("Failed to create virtual environment")
            return False
    else:
        print("Virtual environment already exists")

    # Determine the correct pip path
    if sys.platform == "win32":
        pip_path = venv_path / "Scripts" / "pip.exe"
        python_path = venv_path / "Scripts" / "python.exe"
    else:
        pip_path = venv_path / "bin" / "pip"
        python_path = venv_path / "bin" / "python"

    # Upgrade pip
    print("Upgrading pip...")
    if not run_command(f"{pip_path} install --upgrade pip"):
        print("Warning: Failed to upgrade pip")

    # Install requirements
    requirements_file = project_root / "requirements.txt"
    if requirements_file.exists():
        print("Installing requirements...")
        if not run_command(f"{pip_path} install -r {requirements_file}", cwd=project_root):
            print("Failed to install requirements")
            return False
    else:
        print("requirements.txt not found")
        return False

    # Verify installation
    print("Verifying installation...")
    verify_cmd = f"{python_path} -c \"import pandas, requests, rich; print('✓ All key packages imported successfully')\""
    if not run_command(verify_cmd, cwd=project_root):
        print("Verification failed")
        return False

    print("\n✓ Environment setup completed successfully!")
    print(f"\nTo activate the environment:")
    if sys.platform == "win32":
        print(f"    {venv_path}\\Scripts\\activate")
    else:
        print(f"    source {venv_path}/bin/activate")
    print(f"\nOr run scripts directly with:")
    print(f"    {python_path} <script_name>.py")

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)