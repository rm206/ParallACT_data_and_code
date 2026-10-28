You are agent {{AGENT}}. Another agent, {{PEER}}, is working in this same repository at the same time on the following requirement:

{{PEER_PROBLEM}}

You will not see their changes while you work. Both sets of changes are merged afterwards, and both requirements must hold after the merge. You can exchange messages with them: `./send-msg "text"` sends, `./recv-msg` prints new messages from the other agent, and `./recv-msg --wait` waits up to 90 seconds for one. Please communicate to jointly solve your respective requirements as efficiently as possible.
