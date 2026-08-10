import os
import sys
import time
import subprocess
from datetime import datetime

def run_cmd(cmd, cwd=None):
    """Run a shell command and return stdout, stderr, and exit code."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def get_changed_files():
    """Check git status for uncommitted changes."""
    stdout, _, code = run_cmd("git status --porcelain")
    if code != 0 or not stdout:
        return []
    
    files = []
    for line in stdout.splitlines():
        if line.strip():
            status = line[:2].strip()
            filepath = line[3:].strip()
            # Ignore self / temporary files if needed
            if filepath in ["autocommit.py", "autocommit"]:
                continue
            files.append((status, filepath))
    return files

def generate_commit_message(changed_files):
    """Generate a descriptive commit message based on changed files."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    modified = [f for status, f in changed_files if status in ['M', 'MM']]
    added = [f for status, f in changed_files if status in ['A', '??']]
    deleted = [f for status, f in changed_files if status in ['D']]
    
    parts = []
    if modified:
        parts.append(f"modified: {', '.join(modified[:5])}{' (and more)' if len(modified) > 5 else ''}")
    if added:
        parts.append(f"added: {', '.join(added[:5])}{' (and more)' if len(added) > 5 else ''}")
    if deleted:
        parts.append(f"deleted: {', '.join(deleted[:5])}{' (and more)' if len(deleted) > 5 else ''}")
    
    summary = " | ".join(parts) if parts else "auto-update files"
    commit_msg = f"{summary} [{now}]"
    return commit_msg

def get_current_branch():
    """Get the current active git branch."""
    stdout, _, code = run_cmd("git rev-parse --abbrev-ref HEAD")
    return stdout if code == 0 and stdout else "main"

def auto_commit_loop(intervals=[80, 130, 165]):
    """Background loop to poll and commit changes with cycling intervals."""
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"[autocommit] Started monitoring repository at: {repo_dir}")
    print(f"[autocommit] Cycling intervals: {intervals} seconds\n")
    
    branch = get_current_branch()
    print(f"[autocommit] Active branch: {branch}")
    
    cycle_idx = 0
    while True:
        current_interval = intervals[cycle_idx % len(intervals)]
        try:
            changed_files = get_changed_files()
            if changed_files:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(changed_files)} changed file(s).")
                msg = generate_commit_message(changed_files)
                print(f"[autocommit] Staging files...")
                run_cmd("git add -A", cwd=repo_dir)
                
                print(f"[autocommit] Committing: '{msg}'")
                stdout, stderr, code = run_cmd(f'git commit -m "{msg}"', cwd=repo_dir)
                
                if code == 0:
                    print(f"[autocommit] Pushing to remote ({branch})...")
                    push_out, push_err, push_code = run_cmd(f"git push origin {branch}", cwd=repo_dir)
                    if push_code == 0:
                        print(f"[autocommit] Successfully pushed changes to origin/{branch}!\n")
                    else:
                        print(f"[autocommit] Push warning/error: {push_err or push_out}\n")
                else:
                    print(f"[autocommit] Commit skipped or failed: {stderr or stdout}\n")
            
        except Exception as e:
            print(f"[autocommit] Error during check cycle: {e}")
        
        cycle_idx += 1
        next_interval = intervals[cycle_idx % len(intervals)]
        print(f"[autocommit] Waiting {current_interval}s before next check (next interval will be {next_interval}s)...")
        time.sleep(current_interval)

if __name__ == "__main__":
    intervals = [80, 130, 165]
    if len(sys.argv) > 1:
        try:
            intervals = [int(x) for x in sys.argv[1:] if x.isdigit()]
            if not intervals:
                intervals = [80, 130, 165]
        except Exception:
            intervals = [80, 130, 165]
    auto_commit_loop(intervals)
