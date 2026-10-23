Add an issue orchestration agent on top of the existing system.

The purpose of this agent is to manage project issues in the issues directory
and spawn lead agents as sub tasks to work on those issues. Issues ready to work
on are in the todo directory. They should be worked on in order. WHen an issue
is handed to a lead agent it should be moved to the inprogress folder.

The amount of subagent nesting will need to increase. I think opencode allows
1 level by default but this will need to increase to 2.
