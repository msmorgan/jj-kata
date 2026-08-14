from __future__ import annotations

CURRENT_ALIASES = (
    'revset-aliases."other_workspaces()"="working_copies()~@"',
    'revset-aliases."not_default()"="@~default@"',
    (
        'revset-aliases."only_if(condition,revisions)"='
        '"revisions&descendants(ancestors(condition))"'
    ),
    (
        'revset-aliases."immutable_heads()"="builtin_immutable_heads()|'
        'only_if(not_default(),other_workspaces())"'
    ),
)
LEGACY_ALIASES = (
    'revset-aliases."all_if_any(rev)"="descendants(ancestors(rev))"',
    (
        'revset-aliases."immutable_heads()"="builtin_immutable_heads()|'
        '((working_copies()~@)&all_if_any(default@~@))"'
    ),
)


def boundaries_installed(repo_config: str) -> bool:
    """Report whether a repository's jj config carries a jj-sensei boundary policy.

    Lifecycle refusal and session orientation must agree on this, so both read the
    same matcher: a hook that reported a guard Kata then rejects, or stayed quiet
    about one Kata will reject, would be worse than saying nothing at all.
    """
    compact = "".join(repo_config.split())
    return all(alias in compact for alias in CURRENT_ALIASES) or all(
        alias in compact for alias in LEGACY_ALIASES
    )
