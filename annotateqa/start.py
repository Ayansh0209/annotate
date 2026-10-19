"""Cross-platform launcher. Uses the project environment and preserves all study data."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def run(command):
    subprocess.run(command, cwd=ROOT, check=True)

def main():
    parser = argparse.ArgumentParser(description='Start AnnotateQA on localhost.')
    parser.add_argument('--setup', action='store_true', help='Install dependencies and build the frontend first.')
    args = parser.parse_args()
    os.chdir(ROOT)
    local_python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    parent_python = ROOT.parent / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    python = local_python if local_python.exists() else parent_python if parent_python.exists() else Path(sys.executable)
    if args.setup:
        if not local_python.exists():
            run([sys.executable, '-m', 'venv', str(ROOT / '.venv')])
        python = local_python
        run([str(python), '-m', 'pip', 'install', '-r', 'requirements.txt'])
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            raise SystemExit('Install Node.js 22+ and restart your terminal, then run python start.py --setup.')
        run([npm, 'install', '--no-audit', '--no-fund'])
        run([npm, 'run', 'build'])
    if not (ROOT / 'dist' / 'index.html').exists():
        raise SystemExit('The frontend needs building. Run: python start.py --setup')
    check = subprocess.run([str(python), '-c', 'import flask, dotenv, sklearn'], capture_output=True)
    if check.returncode:
        raise SystemExit('Python dependencies are missing. Run: python start.py --setup')
    if not (ROOT / '.env').exists():
        shutil.copyfile(ROOT / '.env.example', ROOT / '.env')
    run([str(python), str(ROOT / 'scripts' / 'seed_practice.py')])
    print('Starting your workspace. Open the local URL shown below. Press Ctrl+C to stop.', flush=True)
    run([str(python), '-m', 'backend.app'])

if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f'Setup or launch failed (exit {error.returncode}). See the message above. Your study data was preserved.')
    except KeyboardInterrupt:
        print('\nStopped. Your annotations remain in data/annotateqa.sqlite3.')
