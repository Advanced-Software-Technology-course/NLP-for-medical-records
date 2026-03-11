
# Git Guide

If you've never used Git or GitHub before, this guide walks you through everything step by step.

> 💡 **Git** is a tool that tracks changes to your code. **GitHub** is a website that hosts your code online so your team can share it.

---

## Installing Git

- **Windows:** Download from [git-scm.com](https://git-scm.com/download/win), run the installer, leave all settings as default
- **Mac:** Open Terminal, run `git --version` — it will prompt you to install automatically
- **Linux:** Open a terminal and run `sudo apt install git`

After installing, open your terminal and set your name and email **once**:
```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

To verify git is installed correctly:
```bash
git --version
# should print something like: git version 2.43.0
```

---

## 1. Cloning the Repo

Cloning means downloading the project to your computer for the first time.

**Step 1 —** Go to the repository on GitHub:
 `https://github.com/Advanced-Software-Technology-course/NLP-for-medical-records`

**Step 2 —** Click the green **`<> Code`** button (top right of the file list)

**Step 3 —** Make sure **HTTPS** is selected, then click the copy icon to copy the URL

**Step 4 —** Open your terminal, navigate to where you want the project folder, and run (this is where you would paste the copied URL):
```bash
git clone https://github.com/Advanced-Software-Technology-course/NLP-for-medical-records.git
```

**Step 5 —** Move into the project folder:
```bash
cd NLP-for-medical-records
```

You only clone **once**. From now on you use `git pull` to get updates!

Then make your own API keys to run the AI pipeline (see [docs/api_setup_guide.md](docs/api_setup_guide.md)).

---

## 2. Basic Workflow

Every single time you sit down to work, follow these steps in order.

### Step 1 — Open your terminal and go to the project folder
```bash
cd path/to/NLP-for-medical-records
```

### Step 2 — Make sure you're on the right branch
```bash
git branch
```
This prints a list of branches. The one with `*` next to it is your current branch. You should **never** be on `main` when working. If you are, switch to your branch first (see Section 3).

### Step 3 — Pull the latest changes
Always do this before starting work so you have your teammates' latest changes:
```bash
git pull
```
You should see either `Already up to date.` or a list of files that were updated.

### Step 4 — Do your work
Edit files, write code, do whatever you need to do.

### Step 5 — Check what you've changed
```bash
git status
```
This shows you which files have been modified (in red) and which are staged/ready to commit (in green).

### Step 6 — Stage your changes
Staging means telling git "I want to include these changes in my next save point."

To stage everything you changed:
```bash
git add --all
```

To stage only a specific file:
```bash
git add pipeline/medical_pipeline.py
```

Run `git status` again — your files should now appear in green.

### Step 7 — Commit your changes
A commit is a save point with a message describing what you did:
```bash
git commit -m "add diarization support to transcribe function"
```

Write commit messages in plain English describing **what** you did.
- Good: `"fix SOAP prompt formatting"`, `"add evaluation script for ACI-Bench"`
- Bad: `"stuff"`, `"changes"`, `"temp"`, `"bug fix"`, `"tested some things"`

### Step 8 — Push to GitHub
Send your commits to GitHub so your teammates can see them:
```bash
git push
```

Go to the repository on GitHub and click **"Commits"** — you should see your commit at the top of the list.

---

## 3. Branches

A branch is your own personal workspace. Changes on your branch don't affect anyone else until you deliberately merge them in.

> 💡 Think of `main` as the "official" version everyone can see. You never work directly on it, you work on your own branch and then propose your changes via a Pull Request.

### Creating a branch (two ways)

**Option A — From an Issue on GitHub (RECOMMENDED):**

This is the best way because it automatically links your branch to the task you're working on.

1. Go to the repository on GitHub
2. Click **"Issues"** in the top menu
3. Click on the Issue you're working on
4. On the right side, scroll down and click **"Create a branch"** (under Development)
5. Leave the settings as default and click **"Create branch"**
6. GitHub will show you two commands, copy and run them in your terminal:
```bash
git fetch
git checkout your-branch-name
```

**Option B — From the terminal:**
```bash
git checkout -b feature-name
# example: git checkout -b evaluation-scripts
```

### Checking which branch you're on
```bash
git branch
```
The branch with `*` is your current one. Example output:
```
* evaluation-scripts
  develop
  main
```

### Switching to an existing branch
```bash
git checkout branch-name
```
If git says the branch doesn't exist, fetch it from GitHub first:
```bash
git fetch
git checkout branch-name
```

### When your work is done — open a Pull Request

A Pull Request (PR) is how you propose merging your work into the shared codebase. A teammate reviews it before it goes in.

1. First, push your branch to GitHub:
```bash
git push
```
If it's your first push on this branch, git will tell you to run:
```bash
git push --set-upstream origin your-branch-name
```
Just copy and run whatever git tells you.

2. Go to the repository on GitHub — you'll see a yellow banner at the top saying **"your-branch had recent pushes — Compare & pull request"**. Click it.

3. On the Pull Request page:
   - Make sure **base** is set to `develop` (not `main`) — change it if needed
   - Write a short description of what you changed and why
   - Click **"Create pull request"**

4. Wait for a teammate to review and approve it. Don't merge it yourself unless told to.

> 💡 We always merge into `develop` first, not `main`. The `main` branch is only updated when we have a stable, working version to show.

---

## 4. Resolving Merge Conflicts

A merge conflict happens when two people edited the same lines in the same file and git doesn't know which version to keep. It sounds scary but it's very normal and fixable.

### How you'll know there's a conflict

**On GitHub** — when you open your Pull Request, you'll see:
```
This branch has conflicts that must be resolved
```

**In the terminal** — after running `git pull`, you'll see:
```
CONFLICT (content): Merge conflict in pipeline/medical_pipeline.py
Automatic merge failed; fix conflicts and then commit the result.
```

### Resolving on GitHub (easier, recommended for simple conflicts)

1. Go to **Pull Requests** on GitHub and open your PR
2. Click **"Resolve conflicts"**
3. GitHub opens an editor showing the conflicting file with markers like this:
```
<<<<<<< your-branch
summary = summarize_transcript(transcript)
=======
summary = summarize_transcript(transcript, groq_token)
>>>>>>> develop
```
4. Everything between `<<<<<<<` and `=======` is your version. Everything between `=======` and `>>>>>>>` is the other version.
5. Delete the version you don't want, and delete all three marker lines (`<<<<<<<`, `=======`, `>>>>>>>`) so only clean code remains:
```python
summary = summarize_transcript(transcript, groq_token)
```
6. Click **"Mark as resolved"** at the top right
7. Click **"Commit merge"**

### Resolving in the terminal (for more complex conflicts)

```bash
git pull                        # conflict appears here
# open the conflicted file in your editor
# find and fix the conflict markers (same as above)
git add .                       # stage the resolved file
git commit -m "resolve merge conflict in medical_pipeline.py"
git push
```

> **How to avoid conflicts in the first place:**
> - Always `git pull` before starting work
> - Work on your own files where possible, e.g.: backend on `backend/`, frontend on `frontend/`

---

## Quick Reference

| Command | What it does |
|---|---|
| `git clone <url>` | Download the repo for the first time |
| `git pull` | Get latest changes from GitHub |
| `git status` | See what files have changed |
| `git add --all` | Stage all changes |
| `git add <file>` | Stage a specific file |
| `git commit -m "message"` | Save a snapshot with a message |
| `git push` | Upload your commits to GitHub |
| `git branch` | See all branches and which you're on |
| `git checkout <branch>` | Switch to an existing branch |
| `git checkout -b <branch>` | Create and switch to a new branch |
| `git fetch` | Download branch info without merging |
| `git log --oneline` | See recent commit history |

---
