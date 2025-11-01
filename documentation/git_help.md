# Git Help Commands

## 🔧 Setup & Info

git init                     # Initialize a new Git repo
git status                   # Show current changes and branch
git config --list             # View your git configuration
git remote -v                 # Show linked remote repositories

## 💾 Staging & Committing

- git add .                    # Add all changed files
- git add <file>               # Add a specific file
- git commit -m "Your message" # Commit with a message
- git log --oneline            # View commit history (short)

## 🌿 Branches

- git branch                   # List all branches
- git branch <new-branch>      # Create a new branch
- git checkout <branch>        # Switch branches
- git checkout -b <new-branch> # Create and switch to a new branch
- git merge <branch>           # Merge another branch into current one

## 🌍 Remote Operations (GitHub, etc.)

- git remote add origin <url>  # Connect local repo to GitHub
- git push -u origin main      # Push main branch (first time)
- git push                     # Push changes
- git pull                     # Get latest changes from remote
- git fetch                    # Fetch updates without merging

## 🧹 Fixes & Undo

- git restore <file>           # Undo local changes (unstaged)
- git reset HEAD <file>        # Unstage a file
- git reset --hard             # Reset everything to last commit
- git stash                    # Temporarily save uncommitted changes
- git stash pop                # Restore stashed changes

## 🕵️ Useful Extras

- git diff                     # See changes not yet staged
- git show                     # Show details of the last commit
- git reflog                   # View all recent Git actions
