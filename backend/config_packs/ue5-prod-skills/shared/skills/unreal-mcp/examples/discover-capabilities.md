# Discover Actions And Toolsets

## Decision Flow

1. `ue_ping` to prove the connected bridge is alive.
2. If a known typed Action already owns the operation, call it directly.
3. Otherwise `ue_actions_search` with a narrow task phrase, inspect a bounded candidate set, then call `ue_actions_schema` for the selected Action.
4. If Actions do not cover the domain, call `list_toolsets`, select the relevant Toolset, and call `describe_toolset` for exact tools and schemas.
5. Choose the narrowest typed capability. Do not fall through to console commands, generic property writes, ProgrammaticToolset, or Python without a proven need.

Record the chosen capability, exact schema, write/destructive flags, target identity, readback call, and save/test gate before mutation.
