"""Shell completion scripts generated from the EPUB-to-HTML argparse parser."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from typing import Any

COMPLETIONS: dict[str, str] = {}


def _actions(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    return [action for action in parser._actions if action.option_strings]


def _choices(action: argparse.Action) -> tuple[str, ...]:
    return tuple(str(value) for value in action.choices or ())


def _long_options(actions: Iterable[argparse.Action]) -> list[str]:
    return [
        option for action in actions for option in action.option_strings if option.startswith("--")
    ]


def _short_options(actions: Iterable[argparse.Action]) -> list[str]:
    return [
        option
        for action in actions
        for option in action.option_strings
        if option.startswith("-") and not option.startswith("--")
    ]


def generate_completions(parser: argparse.ArgumentParser) -> dict[str, str]:
    """Render shell scripts from parser options and choice metadata."""
    actions = _actions(parser)
    long_options = _long_options(actions)
    short_options = _short_options(actions)
    all_options = [*long_options, *short_options]
    value_map = {
        action.option_strings[-1]: _choices(action) for action in actions if _choices(action)
    }
    words = " ".join(all_options)
    bash_cases = "\n".join(
        f'        {option}) COMPREPLY=($(compgen -W "{" ".join(values)}" -- "$current")); return ;;'
        for option, values in value_map.items()
    )
    bash = f'''_epub_to_html_complete() {{
    local current="${{COMP_WORDS[COMP_CWORD]}}"
    local previous="${{COMP_WORDS[COMP_CWORD-1]}}"
    case "$previous" in
{bash_cases}
    esac
    COMPREPLY=($(compgen -W "{words}" -- "$current"))
}}
complete -F _epub_to_html_complete epub-to-html'''

    zsh_lines = [
        "#compdef epub-to-html",
        "_arguments \\",
        "    '1:EPUB file:_files -g \"*.epub\"' \\",
    ]
    for action in actions:
        choices = _choices(action)
        suffix = f":value:({' '.join(choices)})" if choices else ""
        help_text = (action.help or "Option").replace("'", "")
        for option in action.option_strings:
            zsh_lines.append(f"    '{option}[{help_text}]{suffix}' \\")
    zsh = "\n".join(zsh_lines).rstrip(" \\")

    fish_lines = ["complete -c epub-to-html -f -a '*.epub'"]
    for action in actions:
        values = " ".join(_choices(action))
        for option in action.option_strings:
            flag = f"-l {option[2:]}" if option.startswith("--") else f"-s {option[1:]}"
            value_part = f" -xa '{values}'" if values else ""
            fish_lines.append(f"complete -c epub-to-html {flag}{value_part}")
    fish = "\n".join(fish_lines)

    ps_options = ", ".join(repr(option) for option in all_options)
    ps_values = "; ".join(
        f"'{option}' = @({', '.join(repr(value) for value in values)})"
        for option, values in value_map.items()
    )
    powershell = f"""Register-ArgumentCompleter -CommandName epub-to-html -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $options = @({ps_options})
    $values = @{{ {ps_values} }}
    $previous = $commandAst.CommandElements[$commandAst.CommandElements.Count - 2].Value
    if ($values.ContainsKey($previous)) {{ $options = $values[$previous] }}
    $options | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{ [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_) }}
}}"""
    return {"bash": bash, "zsh": zsh, "fish": fish, "powershell": powershell}


def configure_completion_action(parser: argparse.ArgumentParser) -> None:
    """Populate completion output after all parser arguments have been registered."""
    COMPLETIONS.clear()
    COMPLETIONS.update(generate_completions(parser))


class PrintCompletionAction(argparse.Action):
    """Print a generated completion script before positional validation runs."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        _namespace: argparse.Namespace,
        value: str | Sequence[Any] | None,
        _option_string: str | None = None,
    ) -> None:
        del _namespace, _option_string
        configure_completion_action(parser)
        if isinstance(value, str):
            parser.exit(message=COMPLETIONS[value] + "\n")
        parser.error("--print-completion requires a shell name")
