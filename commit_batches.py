import subprocess
import sys

# Get all changed files safely using NUL-delimited format
result = subprocess.run(['git', 'status', '--porcelain=v1', '-z'], capture_output=True, text=True, check=True)
records = result.stdout.split('\0')

files_to_stage = []
i = 0
while i < len(records):
    record = records[i]
    if not record:
        i += 1
        continue

    # First two characters are status codes
    status = record[:2]
    path = record[3:]

    # Handle renames and copies (have two paths)
    if status[0] in ('R', 'C'):
        # Next record is the new path
        i += 1
        if i < len(records):
            path = records[i]

    if path:
        files_to_stage.append(path)
    i += 1

if not files_to_stage:
    print("No files to commit. Exiting.")
    sys.exit(0)

batch1 = files_to_stage[:80]
batch2 = files_to_stage[80:]

# Batch 1
if batch1:
    print("Staging batch 1...")
    subprocess.run(['git', 'add', '--'] + batch1, check=True)
    print("Committing batch 1...")
    subprocess.run(['git', 'commit', '-m', 'chore: batch 1 of 2 - core architecture, backend refactoring, and UI context renaming'], check=True)

    # Push batch 1
    print("Pushing batch 1...")
    subprocess.run(['git', 'push', '-u', 'origin', 'identity-token-refactor'], check=True)

# Batch 2
if batch2:
    print("Staging batch 2...")
    subprocess.run(['git', 'add', '--'] + batch2, check=True)
    print("Committing batch 2...")
    subprocess.run(['git', 'commit', '-m', 'chore: batch 2 of 2 - remaining UI components and minor updates'], check=True)

    # Push batch 2
    print("Pushing batch 2...")
    subprocess.run(['git', 'push', '-u', 'origin', 'identity-token-refactor'], check=True)
