"""Shell completion scripts for the EPUB-to-HTML CLI."""

from __future__ import annotations

import argparse

from cli_constants import ALL_OPTIONS, SHORT_OPTIONS, _COMPLETION_WORDS

COMPLETIONS = {
    "bash": f'''_epub_to_html_complete() {{
    local current="${{COMP_WORDS[COMP_CWORD]}}"
    local previous="${{COMP_WORDS[COMP_CWORD-1]}}"
    case "$previous" in
        --strategy) COMPREPLY=($(compgen -W "embed extract" -- "$current")); return ;;
        --newline) COMPREPLY=($(compgen -W "lf crlf" -- "$current")); return ;;
        --print-completion) COMPREPLY=($(compgen -W "bash zsh fish powershell" -- "$current")); return ;;
        --output|--css|--report-json|--images-dir-name|--reader-max-width|--reader-font-family|--deadline-seconds|--max-*) return ;;
    esac
    COMPREPLY=($(compgen -W "{_COMPLETION_WORDS}" -- "$current"))
}}
complete -F _epub_to_html_complete epub-to-html''',
    "zsh": """#compdef epub-to-html
_arguments \\
    '1:EPUB file:_files -g "*.epub"' \\
    '(-h --help)'{-h,--help}'[Show help and exit]' \\
    '(-s --strategy)'{-s,--strategy}'[Image strategy]:strategy:(embed extract)' \\
    '(-w --wrap)'{-w,--wrap}'[Wrap output]' \\
    '(-c --css)'{-c,--css}'[Trusted stylesheet]:file:_files' \\
    '--help[Show help and exit]' '--version[Show version and exit]' \\
    '--print-completion[Print completion script]:shell:(bash zsh fish powershell)' \\
    '(-o --output)-o[Output HTML path]:path:_files' \\
    '--output[Output HTML path]:path:_files' \\
    '--strategy[Image strategy]:strategy:(embed extract)' '--wrap[Wrap output]' \\
    '--css[Trusted stylesheet]:file:_files' '--remove-toc[Remove TOC]' '--remove-cover[Remove cover]' \\
    '--images-dir-name[Extracted image directory]:name:' '--chunked[Stream staged output]' \\
    '--safe-mode[Sanitize active content]' '--navigation[Add generated navigation]' \\
    '--reader-max-width[Wrapped reading width]:width:' '--reader-font-family[Wrapped font]:font:' \\
    '--force[Replace existing output]' '--deadline-seconds[Conversion deadline]:seconds:' \\
    '--fail-on-warning[Reject warnings]' '--no-validate-output[Skip output validation]' \\
    '--stable-mime-types[Use stable MIME types]' '--newline[Output line ending]:line ending:(lf crlf)' \\
    '--report-json[Write JSON report]:file:_files' '--no-progress[Disable progress]' \\
    '--force-progress[Show progress without TTY]' '--verbose[Show traceback]' \\
    '--max-archive-entries[Maximum ZIP members]:number:' '--max-compressed-bytes[Maximum compressed bytes]:number:' \\
    '--max-expanded-bytes[Maximum expanded bytes]:number:' '--max-entry-bytes[Maximum member bytes]:number:' \\
    '--max-compression-ratio[Maximum compression ratio]:number:' '--max-documents[Maximum documents]:number:' \\
    '--max-images[Maximum images]:number:' '--max-output-bytes[Maximum output bytes]:number:' """,
    "fish": "\n".join(
        [
            "complete -c epub-to-html -f -a '*.epub'",
            *[f"complete -c epub-to-html -l {option[2:]}" for option in ALL_OPTIONS],
            "complete -c epub-to-html -s h -d 'Show help and exit'",
            "complete -c epub-to-html -s o -r -d 'Output HTML path'",
            "complete -c epub-to-html -s s -xa 'embed extract' -d 'Image strategy'",
            "complete -c epub-to-html -s w -d 'Wrap output'",
            "complete -c epub-to-html -s c -r -d 'Trusted stylesheet'",
            "complete -c epub-to-html -l strategy -xa 'embed extract'",
            "complete -c epub-to-html -l newline -xa 'lf crlf'",
            "complete -c epub-to-html -l print-completion -xa 'bash zsh fish powershell'",
        ]
    ),
    "powershell": f"""Register-ArgumentCompleter -CommandName epub-to-html -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)
    $options = @({", ".join(repr(option) for option in (*ALL_OPTIONS, *SHORT_OPTIONS))})
    $values = @{{ '--strategy' = @('embed', 'extract'); '--newline' = @('lf', 'crlf'); '--print-completion' = @('bash', 'zsh', 'fish', 'powershell') }}
    $previous = $commandAst.CommandElements[$commandAst.CommandElements.Count - 2].Value
    if ($values.ContainsKey($previous)) {{ $options = $values[$previous] }}
    $options | Where-Object {{ $_ -like "$wordToComplete*" }} | ForEach-Object {{ [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_) }}
}}""",
}


class PrintCompletionAction(argparse.Action):
    """Print a small static completion script before positional validation runs."""

    def __call__(
        self,
        parser,
        _namespace,
        value: str | None,
        _option_string: str | None = None,
    ) -> None:
        del _namespace, _option_string
        if isinstance(value, str):
            parser.exit(message=COMPLETIONS[value] + "\n")
        parser.error("--print-completion requires a shell name")
