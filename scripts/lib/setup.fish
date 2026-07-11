set -q __setup_done; and return
set -g __setup_done

# Each caller passes the programs it needs (e.g. `flock`, `perl`); jj is always
# required — the project root below comes from it. No hard-coded fetches.
set -l deps_ok
for program in jj $argv
    if not command -q $program
        echo >&2 "setup.fish: missing needed program $program"
        set -e deps_ok
    end
end
set -q deps_ok; or return 1

# The project root is the CWD's jj workspace root — NOT this script copy's
# location. One toolkit copy (a repo-local install or a plugin's bin/ on PATH)
# then serves every workspace: the target repo, the lock, and the ticket paths
# all follow where you RUN the command, so there is no wrong-copy failure mode.
set -g project_dir (command jj workspace root --ignore-working-copy 2>/dev/null)
if test -z "$project_dir"
    echo >&2 "setup.fish: not inside a jj workspace."
    return 1
end
set -g project_dir (path resolve $project_dir)

# Sibling toolkit scripts and libs live next to THIS file, wherever that is.
set -g lib_dir (path resolve (status dirname))
set -g scripts_dir (path dirname $lib_dir)
