import subprocess
import os

# Get all changed files safely
result = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True)
lines = result.stdout.strip().split('\n')

files_to_stage = []
for line in lines:
    if not line: continue
    # Extract filename correctly, handling renames like "R  file1 -> file2"
    if ' -> ' in line:
        file = line.split(' -> ')[1].strip()
    else:
        file = line[3:].strip()
    # Strip quotes if any
    if file.startswith('"') and file.endswith('"'):
        file = file[1:-1]
    files_to_stage.append(file)

batch1 = files_to_stage[:80]
batch2 = files_to_stage[80:]

# Batch 1
print("Staging batch 1...")
subprocess.run(['git', 'add'] + batch1)
print("Committing batch 1...")
subprocess.run(['git', 'commit', '-m', 'chore: batch 1 of 2 - core architecture, backend refactoring, and UI context renaming'])

# Push batch 1
print("Pushing batch 1...")
subprocess.run(['git', 'push', '-u', 'origin', 'identity-token-refactor'])

# Batch 2
print("Staging batch 2...")
subprocess.run(['git', 'add'] + batch2)
print("Committing batch 2...")
subprocess.run(['git', 'commit', '-m', 'chore: batch 2 of 2 - remaining UI components and minor updates'])

# Push batch 2
print("Pushing batch 2...")
subprocess.run(['git', 'push', '-u', 'origin', 'identity-token-refactor'])
