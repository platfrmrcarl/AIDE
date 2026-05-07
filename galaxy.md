# **Technical Orchestration of Multi-Agent AI Swarms via Git Worktree Isolation: Evaluation of Existing Frameworks and Design Specification for the galaxy Protocol**

The trajectory of software engineering has reached a critical inflection point where the bottleneck of productivity is no longer the speed of human typing or the individual reasoning capacity of a single large language model, but rather the orchestration of parallel, autonomous agents.1 As artificial intelligence entities such as Claude and Gemini demonstrate increasing proficiency in isolated coding tasks, the demand for systems that can manage dozens of concurrent sessions has intensified. Traditional version control workflows, designed for human-paced sequential development, are fundamentally inadequate for the high-velocity, multi-threaded output of modern agentic systems.3 This report provides an exhaustive analysis of the technical necessity for Git worktree isolation in multi-agent development, evaluates the current landscape of open-source and proprietary tools, and presents a formal design specification for "galaxy," a hypothetical yet functionally grounded orchestrator capable of managing 10 to 15 concurrent AI sessions.5

## **The Infrastructure of Isolation: Theoretical Underpinnings of Git Worktrees in AI Workflows**

The fundamental problem with multi-agent development on a single repository is the collision of logical state and physical file access. When multiple agents attempt to modify a codebase simultaneously within a single directory, they inevitably encounter race conditions on the Git index, package manager lockfiles, and local development environments.7 Even if agents are assigned to different branches, the physical act of switching branches in a single directory—involving stashing, checking out, and re-indexing—is a synchronous operation that blocks parallelism.9 Git worktrees resolve this by allowing multiple working directories to be linked to a single repository, sharing the underlying object database while maintaining independent staging areas and HEAD pointers.10

### **Physical vs. Logical Separation**

While branches provide logical separation of code history, they do not provide the physical workspace necessary for concurrent execution. A Git worktree acts as a "desk" for an agent, providing a dedicated space where it can run compilers, linters, and tests without interfering with the primary working directory or other active agents.10 This distinction is critical because modern development involves more than just text editing; it involves stateful environments including node\_modules, virtual environments, and local databases.13

| Git Component | Shared Across Worktrees | Isolated Per Worktree | Technical Implication for Swarms |
| :---- | :---- | :---- | :---- |
| Object Database (.git/objects/) | Yes | No | History and blobs are stored once; highly space-efficient for 15+ sessions.3 |
| Branch References (.git/refs/) | Yes | No | All agents can see the existence and state of all other feature branches.3 |
| Working Files | No | Yes | Agents can edit, delete, or create files without causing race conditions.3 |
| Index/Staging Area | No | Yes | Each agent can manage its own commits and staging lifecycle independently.3 |
| HEAD Pointer | No | Yes | Each worktree tracks a unique branch, preventing "branch stomping".3 |
| Git Hooks | Yes | No | Shared hooks ensure consistent linting/testing across the entire swarm.15 |
| Configuration | Yes | No | Remotes and global settings are consistent across all agent workspaces.12 |

The sharing of the object database is the primary technical advantage of worktrees over repository cloning. In a system running 15 parallel sessions, cloning the repository 15 times would duplicate massive amounts of data and require constant fetching to keep the clones in sync. Worktrees, by contrast, allow a commit made by Agent A in Worktree 1 to be immediately visible to the Manager Agent in the root directory via the shared history, without any network overhead.10

### **The "Setup Tax" and Environmental Friction**

The implementation of parallel worktrees introduces a significant "setup tax" that orchestrators must mitigate. When a new worktree is created, it does not automatically include files listed in .gitignore, such as .env files or the node\_modules directory.10 For a tool to manage 10-15 sessions effectively, it must automate the replication of these environments. Evidence suggests that for large monorepos, the time spent re-indexing and reinstalling dependencies can reach 10-15 minutes per session if not handled by a sophisticated manager.9

Effective orchestration requires the automated symlinking of build caches and dependency folders from the main repository into each worktree.16 This allows the agent to begin working in seconds rather than minutes. Furthermore, the orchestrator must handle port isolation; if 15 agents are running dev servers, they cannot all bind to port 3000\. Advanced tools implement hash-based port assignment to ensure each worktree has a unique local URL for testing.13

## **Survey of Existing Multi-Agent Orchestration Tools**

The market for AI-assisted development tools has diverged into several specialized categories, ranging from research-focused frameworks to high-productivity CLI tools and comprehensive desktop environments.

### **Research Frameworks: CAID and Asynchronous Delegation**

One of the most theoretically grounded systems is Centralized Asynchronous Isolated Delegation (CAID), which is built on the OpenHands framework. CAID explicitly maps software engineering primitives—git worktrees, branches, and merges—onto a multi-agent coordination mechanism.2 The architecture follows a strict "Manager-Worker" hierarchy where a central agent decomposes a high-level task into a dependency graph.18

The CAID workflow demonstrates that multi-agent collaboration is more effective when grounded in "branch-and-merge" coordination rather than free-form chat. In empirical evaluations, CAID improved accuracy by 26.7% on paper reproduction tasks and 14.3% on Python library development tasks compared to single-agent baselines.4 The manager agent in CAID does not simply prompt the workers; it creates an isolated worktree for each, assigns a specific sub-task via structured JSON instructions, and monitors completion via Git commits.2

| CAID Mechanism | Corresponding SWE Primitive | Role in Swarm Coordination |
| :---- | :---- | :---- |
| Scheduling Constraints | Dependency Graph | Determines the order of task delegation to prevent conflicts.18 |
| Workspace Isolation | git worktree | Ensures physical separation of parallel edits.18 |
| Structured Signaling | git commit / git push | Agents report task completion through version control state.18 |
| Output Integration | git merge | Completed sub-tasks are consolidated into the main branch.18 |
| State Synchronization | git reset \--hard | Synchronizes worktrees to the latest integrated state of the project.18 |

### **Open-Source CLI Orchestrators**

For developers seeking a terminal-centric experience, several open-source CLI tools provide the foundation for multi-agent worktree management.

#### **Overstory: Swarm Orchestration with SQLite Messaging**

Overstory is a sophisticated tool that turns a single coding session into a multi-agent team.19 Its architecture is notable for using a custom SQLite mail system for inter-agent communication, which allows for a typed protocol of messages like worker\_done, merge\_ready, and escalation.19 Overstory spawns worker agents in isolated worktrees and coordinates them through a "Watchdog" system that monitors liveness across tmux sessions.19

One of the key features of Overstory is its "AgentRuntime" interface, which allows the user to swap between 11 different runtimes, including Claude Code, Gemini CLI, and Aider.19 This flexibility addresses the user's requirement for a tool that can utilize both Gemini and Claude. Overstory enforces tool-specific guards that prevent agents from performing dangerous operations like modifying files outside their assigned worktree or making unapproved Git pushes.19

#### **Octobots and the "Soul" Pattern**

The Octobots framework (derived from Claude Code) implements a multi-agent team architecture where each agent is assigned a "Role" defined by three specific files: a PROFILE.md for technical instructions, a TASK.md for the current objective, and a SOUL.md for personality and communication style.20 This system uses a SQLite "Taskbox" for asynchronous communication, allowing agents like "Py" (a methodical Python expert) and "Sage" (a QA agent focused on evidence) to collaborate on a single repository.20

Octobots solves the multi-repo challenge by creating full clones when necessary, though it primarily relies on the "Operator" pattern where a supervisor TUI manages workers from a single terminal dashboard.20 This model demonstrates the feasibility of managing a "team" of 10-15 agents by treating them as independent processes that communicate through a shared data layer rather than a direct chat interface.20

#### **Parallel Code and CLI Wrappers**

Parallel Code (johannesjo/parallel-code) is an Electron and SolidJS desktop application that runs multiple agents—Claude Code, Gemini CLI, and Codex—simultaneously.17 It automates the creation of a new Git branch and worktree for every task and symlinks node\_modules to ensure rapid startup.17 A unique feature of Parallel Code is the "AI Arena," which allows a user to run different agents head-to-head on the same task to compare their approaches in isolated worktrees.17

Similarly, git-worktree-manager (gw) is a high-performance Rust CLI that integrates with AI assistants. Its delegate command allows a user to spawn a new worktree and a Claude Code session with a single command: gw new fix-auth \--prompt "Fix the JWT token expiration bug".22 The tool includes safety mechanisms that prevent the deletion of a worktree if an active AI session is still writing to its event logs.22

### **AI-Native Development Environments (ADEs)**

The most integrated experience is found in purpose-built ADEs that treat agents and worktrees as first-class citizens.

#### **galaxy (galaxy.build)**

The "galaxy" tool mentioned in the user query is a highly polished macOS application (built with Tauri and React) designed for parallel development.5 It features a "Multi-Agent Canvas" where sessions appear as nodes, allowing users to watch multiple approaches evolve side-by-side.5 galaxy uses a "Coordinator-Specialist" architecture where the primary agent can spawn parallel sub-tasks that run independently in their own worktrees.5

| galaxy.build Feature | Technical Implementation |
| :---- | :---- |
| Worktree Lifecycle | Integrated sidebar for creating, switching, and pruning worktrees.5 |
| Subagent Spawning | Inline spawning of independent tasks that report back to the main thread.5 |
| MCP Integration | Built-in Model Context Protocol creator for extending agent tools.23 |
| Multi-Model Support | Support for 200+ models across 20+ providers, including Claude and Gemini.5 |
| Visual Coordination | Drag-and-drop pane layout for monitoring 15+ concurrent sessions.5 |

It is important to distinguish the commercial "galaxy.build" from various open-source projects with similar names. For instance, ArjenSchwarz/galaxy is an open-source CLI orchestrator that manages sequential and parallel AI sessions across worktrees, specifically designed for "variant" runs where different agents tackle the same spec phase to find the best implementation.26 This tool handles session lifecycle, error recovery, and "consolidation," which is the process of merging the best ideas from multiple variants into a single final commit.26

## **The Hierarchy of Parallelism: Manager-Worker Coordination Patterns**

Managing 10-15 parallel sessions is not a coding problem, but a management and orchestration problem.1 A single human cannot effectively monitor the raw output of 15 agents simultaneously; therefore, the system must utilize a "Coordinator" agent to act as a filter and scheduler.1

### **The Coordinator-Specialist-Verifier Model**

Effective multi-agent systems typically adopt a three-tier architecture to maintain quality and coherence across the swarm.15

1. **Coordinator Agent (Tier 1\)**: This agent never writes code directly. Its role is to decompose the high-level specification into atomic, independent tasks with clear dependency mapping.1 It assigns these tasks to specialists and manages the "fan-in" merge process once tasks are completed.15  
2. **Specialist Agents (Tier 2\)**: These are the "Implementors." Each specialist is assigned to a specific worktree and a narrow task scope (e.g., "Implement the Stripe webhook handler"). Isolation is critical here; if specialists work in the same directory, they will "stomp" on each other's changes or confuse the AI's context with irrelevant file modifications.14  
3. **Verifier Agent (Tier 3\)**: This agent acts as a quality gate. Before a specialist's work is merged back to the main branch, the Verifier runs the test suite in the isolated worktree and checks the results against the original spec.1 Only upon the Verifier's approval does the Coordinator initiate the merge.15

### **Messaging and State Synchronization**

In a 15-agent swarm, communication cannot rely on natural language chat alone, as it becomes a "context explosion" that degrades agent performance.1 Instead, systems like Overstory and Octobots use structured data stores (SQLite) to manage a "Shared Task Queue".19

| Messaging Primitive | Purpose in Swarm | Data Structure |
| :---- | :---- | :---- |
| TASK\_DISPATCH | Manager sends task and context to a Worker. | JSON Payload in SQLite.19 |
| PROGRESS\_UPDATE | Worker reports percentage completion or blockers. | Event Stream in JSONL.22 |
| VERIFY\_REQUEST | Worker signals readiness for code review/testing. | Entry in FIFO Merge Queue.19 |
| INTEGRATION\_SYNC | Manager notifies Workers of a merge in main. | git reset \--hard Signal.18 |
| ESCALATION | Worker requests human intervention for a blocker. | Push Notification/TUI Alert.19 |

### **Token and Resource Optimization**

Running 15 agents in parallel is resource-intensive. Research shows that multi-agent systems consume significantly more tokens than single-agent interactions.28 To mitigate this, orchestrators must employ "History Condensation" and "Minimal Context" patterns. Rather than sending a 10,000-line document to every agent, the manager should provide only the relevant file paths and a "Shared Playbook" of common patterns.1 This "Process Isolation" at the filesystem level is mirrored by "Context Isolation" at the LLM level, ensuring that each agent stays focused on its atomic task.1

## **Design Specification for "galaxy": A High-Scale AI Orchestrator**

The following section constitutes the functional requirements and design for "galaxy," as requested in the user query. This specification is designed to enable a single user to manage a swarm of 10-15 AI assistants (Gemini/Claude) working in parallel across isolated Git worktrees.

### **Functional Requirements**

1. **Hierarchical Decomposition**: The system shall take a natural language goal and utilize a "Manager" agent to decompose it into a Directed Acyclic Graph (DAG) of sub-tasks.2  
2. **Automated Workspace Provisioning**: For each sub-task, galaxy shall automatically create a Git worktree, checkout a new branch, and symlink necessary environment files (node\_modules, .env, build caches).6  
3. **Heterogeneous Agent Support**: The user shall be able to assign different LLM providers (Gemini, Claude, GPT) to different workers within the same swarm.5  
4. **Asynchronous Message Bus**: Communication between agents and the manager shall be handled via a local SQLite database ("Taskbox") to ensure state persistence and structured signaling.19  
5. **Autonomous Verification**: Each worker must execute a project-defined verify command (e.g., npm test or pytest) within its isolated worktree before reporting completion.3  
6. **Conflict Resolution Engine**: In the event of a merge conflict, galaxy shall spawn a specialized "Conflict Agent" to resolve the discrepancy in a dedicated worktree before final integration.2  
7. **Unified Control Plane**: The user shall interact with a single TUI or Web dashboard that summarizes the status, token cost, and current "thinking" of all 15 sessions simultaneously.20

### **Architectural Components**

#### **The Manager (The Brain)**

The Manager is a high-reasoning agent (e.g., Gemini 1.5 Pro or Claude 3 Opus) that maintains the "Global State." It is responsible for reading the project's AGENTS.md (which defines architecture and conventions) and updating the implementation plan as workers finish their tasks.32 It uses asyncio or a similar event loop to handle the non-blocking execution of 15 sub-processes.18

#### **The Workspace Manager (The Infrastructure)**

This component interacts with the host OS and the Git CLI. It manages the physical directory structure under a .galaxy/worktrees/ directory.10 It is responsible for "Port Isolation," ensuring that if Worker A starts a dev server on port 3001, Worker B is assigned port 3002\.13 It also handles "Submodule Synchronization," ensuring that each new worktree has a properly initialized set of submodules to prevent build failures.15

#### **The Worker Wrapper (The Execution)**

galaxy wraps standard AI CLIs (like Claude Code or Gemini CLI) in a headless session. It redirects their output to the Taskbox and injects "Heartbeat" commands to ensure the agent hasn't entered a hallucination loop.20 Each worker receives a "Context Packet" containing only the files and documentation relevant to its assigned sub-task, minimizing token waste.1

#### **The Integration Engine (The Consolidation)**

As workers signal completion, the Integration Engine performs a sequential merge into a "Staging" branch. It utilizes a "Reviewer Agent" to perform a diff analysis of the changes, ensuring they align with the original plan and don't introduce semantic regressions that automated tests might miss.15

### **Operational Flow of the galaxy System**

The following table illustrates the step-by-step progression of a complex feature implementation using the galaxy swarm.

| Phase | Action | System Response |
| :---- | :---- | :---- |
| **Ingestion** | User provides goal: "Build a full-stack CRM." | Manager analyzes repo and writes PLAN.md with 12 sub-tasks.6 |
| **Dispatch** | Manager identifies independent tasks (DB Schema, Auth, UI Components). | galaxy creates 5 worktrees and spawns 5 Agents (2 Claude, 3 Gemini).14 |
| **Execution** | Workers implement code in isolated directories. | Each worker writes progress to SQLite; Manager monitors logs.19 |
| **Verification** | Worker 1 finishes "Auth" and runs npm test. | Verifier Agent confirms tests passed; signals MERGE\_READY.2 |
| **Integration** | Manager merges "Auth" into main. | Manager signals other workers to rebase if necessary.2 |
| **Reporting** | Swarm completes all tasks. | galaxy generates a "Shift Log" summarizing all changes and costs.34 |

## **Technical Implementation Considerations for High-Scale Swarms**

When scaling to 15 concurrent sessions, the "bottleneck" moves from the human's time to the machine's resources and the LLM's rate limits.

### **Rate Limit and Cost Management**

Running 15 agents simultaneously will likely hit API rate limits for most providers. galaxy must implement a "Token Bucket" or "Leaky Bucket" algorithm to throttle agent requests and prevent "429 Too Many Requests" errors.26 The orchestrator should also include a "Wait-and-Resume" logic that parses rate-limit reset times from API errors and automatically sleeps the relevant worker thread.26

### **Disk Space and I/O Performance**

A 15-agent swarm on a large repository can consume massive amounts of disk space. For example, a developer using worktrees for a multi-agent system reported consuming 172 gigabytes for a single project.1 galaxy must utilize copy-on-write (CoW) filesystems where available or use hard links instead of copies for the initial worktree population to minimize this footprint. Furthermore, if 15 agents are all running intensive build processes (like Webpack or Rust compilation), the orchestrator may need to implement a "Task Scheduler" that limits the number of concurrent high-CPU operations.15

### **Handling Shared Lockfiles and Migrations**

One of the most difficult aspects of parallel development is the management of shared resources like package-lock.json or database migrations.32 If 15 agents all add different npm packages, the resulting merge conflicts are nearly impossible to resolve automatically. galaxy addresses this by designating a "Librarian" sub-agent that is the only entity permitted to modify lockfiles.32 Similarly, database migrations must be serialized; galaxy ensures that only one worker can hold the "Migration Lock" at any given time.32

## **Conclusion: The Path Forward for Agentic Orchestration**

The evidence from current open-source projects and research benchmarks clearly indicates that Git worktrees are the essential substrate for parallel AI development. While a single agent can operate in a single directory, a swarm of 10-15 agents requires the physical and environmental isolation that only worktrees provide.2 Tools like CAID, Overstory, and Parallel Code have laid the groundwork for this transition, but a unified orchestrator like "galaxy"—designed specifically for high-scale, heterogeneous agent swarms—represents the next logical step in the evolution of the software development lifecycle. By shifting the human role from "coder" to "manager," and leveraging the infrastructure of Git to maintain coherence, these systems enable a level of productivity that was previously unattainable in single-threaded environments.1 For developers looking to eliminate the bottleneck of session management, the adoption of a worktree-based orchestrator is not merely an optimization, but a fundamental requirement for the agentic era.

#### **Works cited**

1. What 371 Git Worktrees Taught Me About Multi-Agent AI \- Level Up Coding \- GitConnected, accessed May 7, 2026, [https://levelup.gitconnected.com/what-371-git-worktrees-taught-me-about-multi-agent-ai-36d4d61acfb5](https://levelup.gitconnected.com/what-371-git-worktrees-taught-me-about-multi-agent-ai-36d4d61acfb5)  
2. Effective Strategies for Asynchronous Software Engineering Agents ..., accessed May 7, 2026, [https://openhands.dev/blog/asynchronous-software-engineering-agents](https://openhands.dev/blog/asynchronous-software-engineering-agents)  
3. How to Run a Multi-Agent Coding Workspace (2026) | Augment Code, accessed May 7, 2026, [https://www.augmentcode.com/guides/how-to-run-a-multi-agent-coding-workspace](https://www.augmentcode.com/guides/how-to-run-a-multi-agent-coding-workspace)  
4. Arxiv今日论文| 2026-03-24 \- 闲记算法, accessed May 7, 2026, [http://lonepatient.top/2026/03/24/arxiv\_papers\_2026-03-24.html](http://lonepatient.top/2026/03/24/arxiv_papers_2026-03-24.html)  
5. Changelog \- galaxy, accessed May 7, 2026, [https://www.galaxy.build/changelog](https://www.galaxy.build/changelog)  
6. SaschaHeyer/ai-driven-engineering \- GitHub, accessed May 7, 2026, [https://github.com/SaschaHeyer/ai-driven-engineering](https://github.com/SaschaHeyer/ai-driven-engineering)  
7. Best Git Worktree Tools for AI Coding in 2026 (Compared) \- Nimbalyst, accessed May 7, 2026, [https://nimbalyst.com/blog/best-git-worktree-tools-ai-coding-2026/](https://nimbalyst.com/blog/best-git-worktree-tools-ai-coding-2026/)  
8. Run multiple coding agents safely with git worktrees | by Karl Weinmeister \- Medium, accessed May 7, 2026, [https://medium.com/google-cloud/run-multiple-coding-agents-safely-with-git-worktrees-c2d237dbd6b2](https://medium.com/google-cloud/run-multiple-coding-agents-safely-with-git-worktrees-c2d237dbd6b2)  
9. Native Git Worktree Management: UI, Visual Indicators, and Shared Indexing \- YouTrack, accessed May 7, 2026, [https://youtrack.jetbrains.com/projects/IDEA/issues/IDEA-386301/Native-Git-Worktree-Management-UI-Visual-Indicators-and-Shared-Indexing](https://youtrack.jetbrains.com/projects/IDEA/issues/IDEA-386301/Native-Git-Worktree-Management-UI-Visual-Indicators-and-Shared-Indexing)  
10. AI Agents Need Their Own Desk, and Git Worktrees Give Them One | Towards Data Science, accessed May 7, 2026, [https://towardsdatascience.com/ai-agents-need-their-own-desk-and-git-worktrees-give-it-one/](https://towardsdatascience.com/ai-agents-need-their-own-desk-and-git-worktrees-give-it-one/)  
11. Supercharge Your AI Coding Workflow: A Complete Guide to Git Worktrees with Claude Code \- DEV Community, accessed May 7, 2026, [https://dev.to/bhaidar/supercharge-your-ai-coding-workflow-a-complete-guide-to-git-worktrees-with-claude-code-60m](https://dev.to/bhaidar/supercharge-your-ai-coding-workflow-a-complete-guide-to-git-worktrees-with-claude-code-60m)  
12. Git worktrees for parallel AI coding agents \- Upsun Developer Center, accessed May 7, 2026, [https://developer.upsun.com/posts/ai/git-worktrees-for-parallel-ai-coding-agents](https://developer.upsun.com/posts/ai/git-worktrees-for-parallel-ai-coding-agents)  
13. How to Run Parallel AI Coding Agents With Git Worktrees \- MindStudio, accessed May 7, 2026, [https://www.mindstudio.ai/blog/parallel-ai-coding-agents-git-worktrees](https://www.mindstudio.ai/blog/parallel-ai-coding-agents-git-worktrees)  
14. Git Worktrees for AI Coding: How to Run Multiple Agents Without Conflicts | MindStudio, accessed May 7, 2026, [https://www.mindstudio.ai/blog/git-worktrees-parallel-ai-coding-agents](https://www.mindstudio.ai/blog/git-worktrees-parallel-ai-coding-agents)  
15. How to Use Git Worktrees for Parallel AI Agent Execution | Augment Code, accessed May 7, 2026, [https://www.augmentcode.com/guides/git-worktrees-parallel-ai-agent-execution](https://www.augmentcode.com/guides/git-worktrees-parallel-ai-agent-execution)  
16. Worktrunk is a CLI for Git worktree management, designed for parallel AI agent workflows \- GitHub, accessed May 7, 2026, [https://github.com/max-sixty/worktrunk](https://github.com/max-sixty/worktrunk)  
17. GitHub \- johannesjo/parallel-code: Run Claude Code, Codex, and ..., accessed May 7, 2026, [https://github.com/johannesjo/parallel-code](https://github.com/johannesjo/parallel-code)  
18. Effective Strategies for Asynchronous Software Engineering Agents \- arXiv, accessed May 7, 2026, [https://arxiv.org/html/2603.21489v1](https://arxiv.org/html/2603.21489v1)  
19. GitHub \- jayminwest/overstory: Multi-agent orchestration for AI coding agents — pluggable runtime adapters for Claude Code, Pi, and more, accessed May 7, 2026, [https://github.com/jayminwest/overstory](https://github.com/jayminwest/overstory)  
20. Autonomous AI Agents for Software Development: How We Built a Multi-Agent AI System with Claude Code \- EPAM, accessed May 7, 2026, [https://www.epam.com/insights/ai/blogs/step-by-step-guide-to-building-a-multi-agent-claude-code-ai-development-team](https://www.epam.com/insights/ai/blogs/step-by-step-guide-to-building-a-multi-agent-claude-code-ai-development-team)  
21. AI Weekly Review \- Feb. 23th 2026 \- Upsun Developer, accessed May 7, 2026, [https://developer.upsun.com/posts/ai/aiweekly-2026-02-23](https://developer.upsun.com/posts/ai/aiweekly-2026-02-23)  
22. git-worktree-manager \- crates.io: Rust Package Registry, accessed May 7, 2026, [https://crates.io/crates/git-worktree-manager](https://crates.io/crates/git-worktree-manager)  
23. galaxy for Developers, accessed May 7, 2026, [https://www.galaxy.build/galaxy-for-developers](https://www.galaxy.build/galaxy-for-developers)  
24. How It Works \- galaxy, accessed May 7, 2026, [https://www.galaxy.build/how-it-works](https://www.galaxy.build/how-it-works)  
25. Claude Code Desktop Redesign: Parallel Agents & Routines Explaine \- Eigent AI, accessed May 7, 2026, [https://www.eigent.ai/blog/claude-code-desktop-redesign](https://www.eigent.ai/blog/claude-code-desktop-redesign)  
26. galaxy/CLAUDE.md at main · ArjenSchwarz/galaxy · GitHub, accessed May 7, 2026, [https://github.com/ArjenSchwarz/galaxy/blob/main/CLAUDE.md](https://github.com/ArjenSchwarz/galaxy/blob/main/CLAUDE.md)  
27. Run Multiple AI Coding Agents | Guides \- Warp, accessed May 7, 2026, [https://docs.warp.dev/guides/agent-workflows/how-to-run-multiple-ai-coding-agents](https://docs.warp.dev/guides/agent-workflows/how-to-run-multiple-ai-coding-agents)  
28. Swarm vs. Supervisor: Multi-Agent Architecture Guide \- Augment Code, accessed May 7, 2026, [https://www.augmentcode.com/guides/swarm-vs-supervisor](https://www.augmentcode.com/guides/swarm-vs-supervisor)  
29. MegaAgent: A Large-Scale Autonomous LLM-based Multi-Agent System Without Predefined SOPs | Request PDF \- ResearchGate, accessed May 7, 2026, [https://www.researchgate.net/publication/394271775\_MegaAgent\_A\_Large-Scale\_Autonomous\_LLM-based\_Multi-Agent\_System\_Without\_Predefined\_SOPs](https://www.researchgate.net/publication/394271775_MegaAgent_A_Large-Scale_Autonomous_LLM-based_Multi-Agent_System_Without_Predefined_SOPs)  
30. Dutta2005/galaxy-CLI: A powerful command-line interface AI agent with ease. \- GitHub, accessed May 7, 2026, [https://github.com/Dutta2005/galaxy-CLI](https://github.com/Dutta2005/galaxy-CLI)  
31. Orca \- Your control center for parallel AI agents \- Product Hunt, accessed May 7, 2026, [https://www.producthunt.com/products/orca-5](https://www.producthunt.com/products/orca-5)  
32. Parallel Agentic Development With Git Worktrees: A Practical Playbook | MindStudio, accessed May 7, 2026, [https://www.mindstudio.ai/blog/parallel-agentic-development-git-worktrees](https://www.mindstudio.ai/blog/parallel-agentic-development-git-worktrees)  
33. Git Worktrees for Parallel Development: 3x Throughput with AI Agents \- James Phoenix, accessed May 7, 2026, [https://understandingdata.com/posts/git-worktrees-parallel-dev/](https://understandingdata.com/posts/git-worktrees-parallel-dev/)  
34. Nightshift \- galaxy, accessed May 7, 2026, [https://www.galaxy.build/nightshift](https://www.galaxy.build/nightshift)
