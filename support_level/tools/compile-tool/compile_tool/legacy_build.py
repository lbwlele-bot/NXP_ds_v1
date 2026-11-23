from __future__ import annotations

import re
import shlex
from typing import Any

from .common import ToolError


# Only the cache entries emitted by the standard MCUXpresso SDK armgcc
# build_<configuration>.sh scripts are accepted.  Everything else is left
# alone so a malformed or custom script cannot turn into a broad delete.
CLEANUP_DIRECTORIES = {"CMakeFiles"}
CLEANUP_FILES = {
    "Makefile",
    "build.ninja",
    "cmake_install.cmake",
    "CMakeCache.txt",
}
SUPPORTED_GENERATORS = {"Unix Makefiles"}
SUPPORTED_CMAKE_DEFINITIONS = {"CMAKE_BUILD_TYPE", "CMAKE_TOOLCHAIN_FILE"}
SHELL_OPERATORS = {
    "|",
    "||",
    "&&",
    ";",
    "&",
    ">",
    ">>",
    "<",
    "2>&1",
    "2>",
    "1>",
    "&>",
}

_CLEANUP_RE = re.compile(
    r"^if\s+\[\s*-(?P<kind>[df])\s+(?P<quote>[\"']?)"
    r"(?P<name>[^\"'\s;]+)(?P=quote)\s*\]\s*;\s*then\s+"
    r"rm\s+(?P<rm_args>.+?)\s*;\s*fi\s*$"
)


def _error(script_label: str, line_number: int, message: str) -> ToolError:
    return ToolError(f"{script_label}: line {line_number}: {message}")


def _words(line: str, script_label: str, line_number: int) -> list[str]:
    try:
        return shlex.split(line, posix=True)
    except ValueError as exc:
        raise _error(
            script_label, line_number, f"cannot parse shell words: {exc}"
        ) from exc


def _reject_shell_syntax(
    words: list[str], script_label: str, line_number: int
) -> None:
    for word in words:
        if word in SHELL_OPERATORS or word.startswith(("2>", "1>", "&>")):
            raise _error(
                script_label,
                line_number,
                f"shell operator or redirection is not supported: {word!r}",
            )
        if any(character in word for character in ("\n", "\r", "`", "$", ";", "|", "&", ">", "<")):
            raise _error(
                script_label,
                line_number,
                f"shell syntax is not supported in script argument: {word!r}",
            )


def _cleanup_entry(
    match: re.Match[str], script_label: str, line_number: int
) -> dict[str, str]:
    kind = match.group("kind")
    name = match.group("name")
    allowed = CLEANUP_DIRECTORIES if kind == "d" else CLEANUP_FILES
    if name not in allowed:
        expected = ", ".join(sorted(allowed))
        raise _error(
            script_label,
            line_number,
            f"unsupported legacy cache cleanup target {name!r}; expected one of {expected}",
        )
    rm_args = match.group("rm_args")
    try:
        rm_words = shlex.split(rm_args, posix=True)
    except ValueError as exc:
        raise _error(
            script_label, line_number, f"cannot parse cleanup command: {exc}"
        ) from exc
    if not rm_words or rm_words[-1] != name:
        raise _error(
            script_label,
            line_number,
            f"cleanup command must target the same entry tested by the if: {name!r}",
        )
    options = rm_words[:-1]
    allowed_options = (
        (["-rf"], ["-fr"], ["-r", "-f"], ["-f", "-r"])
        if kind == "d"
        else (["-f"],)
    )
    if options not in allowed_options:
        raise _error(
            script_label,
            line_number,
            f"unsupported cleanup flags for {name!r}: {' '.join(options)!r}",
        )
    return {
        "kind": "directory" if kind == "d" else "file",
        "name": name,
    }


def _parse_definition(
    definition: str,
    script_label: str,
    line_number: int,
) -> tuple[str, str]:
    key, separator, value = definition.partition("=")
    if not separator:
        raise _error(
            script_label,
            line_number,
            "cmake -D definition must use NAME=value",
        )
    key = key.split(":", 1)[0]
    if not key:
        raise _error(script_label, line_number, "cmake -D definition has no name")
    if key not in SUPPORTED_CMAKE_DEFINITIONS:
        raise _error(
            script_label,
            line_number,
            f"unsupported cmake definition {key!r}; only "
            "CMAKE_BUILD_TYPE and CMAKE_TOOLCHAIN_FILE are supported",
        )
    if not value:
        raise _error(script_label, line_number, f"{key} must not be empty")
    return key, value


def _parse_configure(
    words: list[str],
    *,
    expected_configuration: str,
    script_label: str,
    line_number: int,
) -> dict[str, Any]:
    _reject_shell_syntax(words, script_label, line_number)

    generator = "Unix Makefiles"
    generator_seen = False
    build_type: str | None = None
    toolchain_file: str | None = None
    positional: list[str] = []
    source_option = False
    index = 1
    while index < len(words):
        token = words[index]
        if token == "-P" or token.startswith("-P"):
            raise _error(
                script_label,
                line_number,
                "cmake -P script mode is not a configure invocation",
            )
        if token == "--build" or token.startswith("--build="):
            raise _error(
                script_label,
                line_number,
                "cmake --build is not a configure invocation",
            )
        if token == "-E" or token.startswith("-E"):
            raise _error(
                script_label,
                line_number,
                "cmake -E command mode is not a configure invocation",
            )
        if token.startswith("--"):
            raise _error(
                script_label,
                line_number,
                f"unsupported cmake option {token!r}",
            )
        if token == "-G":
            if generator_seen:
                raise _error(
                    script_label, line_number, "cmake generator is specified more than once"
                )
            index += 1
            if index >= len(words):
                raise _error(script_label, line_number, "-G requires a generator value")
            generator = words[index]
            generator_seen = True
        elif token.startswith("-G") and token != "-G":
            if generator_seen:
                raise _error(
                    script_label, line_number, "cmake generator is specified more than once"
                )
            generator = token[2:]
            generator_seen = True
        elif token == "-D":
            index += 1
            if index >= len(words):
                raise _error(script_label, line_number, "-D requires a definition")
            key, value = _parse_definition(words[index], script_label, line_number)
            if key == "CMAKE_BUILD_TYPE":
                if build_type is not None and build_type.casefold() != value.casefold():
                    raise _error(
                        script_label,
                        line_number,
                        f"conflicting CMAKE_BUILD_TYPE values: {build_type!r} and {value!r}",
                    )
                build_type = value
            else:
                if toolchain_file is not None and toolchain_file != value:
                    raise _error(
                        script_label,
                        line_number,
                        f"conflicting CMAKE_TOOLCHAIN_FILE values: "
                        f"{toolchain_file!r} and {value!r}",
                    )
                toolchain_file = value
        elif token.startswith("-D") and token != "-D":
            key, value = _parse_definition(token[2:], script_label, line_number)
            if key == "CMAKE_BUILD_TYPE":
                if build_type is not None and build_type.casefold() != value.casefold():
                    raise _error(
                        script_label,
                        line_number,
                        f"conflicting CMAKE_BUILD_TYPE values: {build_type!r} and {value!r}",
                    )
                build_type = value
            else:
                if toolchain_file is not None and toolchain_file != value:
                    raise _error(
                        script_label,
                        line_number,
                        f"conflicting CMAKE_TOOLCHAIN_FILE values: "
                        f"{toolchain_file!r} and {value!r}",
                    )
                toolchain_file = value
        elif token == "-S":
            if source_option:
                raise _error(
                    script_label, line_number, "cmake source directory is specified more than once"
                )
            index += 1
            if index >= len(words):
                raise _error(script_label, line_number, "-S requires a source directory")
            source_option = True
            if words[index] != ".":
                raise _error(
                    script_label,
                    line_number,
                    "legacy build scripts must configure the script directory (source '.')",
                )
        elif token.startswith("-S") and token != "-S":
            if source_option:
                raise _error(
                    script_label, line_number, "cmake source directory is specified more than once"
                )
            source_option = True
            if token[2:] != ".":
                raise _error(
                    script_label,
                    line_number,
                    "legacy build scripts must configure the script directory (source '.')",
                )
        elif token == "-B" or token.startswith("-B"):
            raise _error(
                script_label,
                line_number,
                "an explicit cmake -B build directory is not supported by the legacy recipe",
            )
        elif token.startswith("-"):
            raise _error(
                script_label,
                line_number,
                f"unsupported cmake option {token!r}",
            )
        else:
            positional.append(token)
        index += 1

    if generator not in SUPPORTED_GENERATORS:
        raise _error(
            script_label,
            line_number,
            f"unsupported cmake generator {generator!r}; expected Unix Makefiles",
        )
    if len(positional) > 1 or (positional and positional[0] != "."):
        raise _error(
            script_label,
            line_number,
            "legacy build scripts must configure the script directory (source '.')",
        )
    if source_option and positional:
        raise _error(
            script_label,
            line_number,
            "source directory is supplied by both -S and a positional argument",
        )
    if build_type is None:
        raise _error(
            script_label,
            line_number,
            "cmake configure must declare CMAKE_BUILD_TYPE",
        )
    if toolchain_file is None:
        raise _error(
            script_label,
            line_number,
            "cmake configure must declare CMAKE_TOOLCHAIN_FILE",
        )
    if build_type.casefold() != expected_configuration.casefold():
        raise _error(
            script_label,
            line_number,
            f"CMAKE_BUILD_TYPE {build_type!r} does not match selected "
            f"build_configuration {expected_configuration!r}",
        )
    return {
        "configure_argv": words,
        "generator": generator,
        "build_type": build_type,
    }


def _parse_make(
    words: list[str],
    *,
    script_label: str,
    line_number: int,
) -> dict[str, Any]:
    remaining = list(words[1:])

    # The standard scripts append ``2>&1 | tee build_log.txt``.  The tool
    # intentionally drops that pipeline: the configure and build steps return
    # their own exit codes and must not be masked by tee.
    if "|" in remaining:
        pipe = remaining.index("|")
        pipeline = remaining[pipe + 1 :]
        remaining = remaining[:pipe]
        if not (
            len(pipeline) == 2
            and pipeline[0] == "tee"
            and pipeline[1] in {"build_log.txt", "./build_log.txt"}
        ):
            raise _error(
                script_label,
                line_number,
                "only the standard '| tee build_log.txt' build log pipeline is supported",
            )
    remaining = [word for word in remaining if word != "2>&1"]
    _reject_shell_syntax(remaining, script_label, line_number)

    build_args: list[str] = []
    index = 0
    while index < len(remaining):
        token = remaining[index]
        if token.startswith("--"):
            if token == "--jobs":
                index += 1
                if index < len(remaining) and remaining[index].isdigit():
                    index += 1
                continue
            if token.startswith("--jobs="):
                value = token.split("=", 1)[1]
                if not value.isdigit():
                    raise _error(
                        script_label,
                        line_number,
                        f"make job count must be a positive integer: {token!r}",
                    )
                index += 1
                continue
            raise _error(
                script_label,
                line_number,
                f"unsupported make option {token!r}; the legacy recipe only "
                "accepts -j/--jobs concurrency options",
            )
        if token.startswith("-") and token != "-":
            if token == "-j":
                index += 1
                if index < len(remaining) and remaining[index].isdigit():
                    index += 1
                continue
            if re.fullmatch(r"-j\d+", token):
                index += 1
                continue
            raise _error(
                script_label,
                line_number,
                f"unsupported make option {token!r}; the legacy recipe only "
                "accepts -j/--jobs concurrency options",
            )
        if token == "-":
            raise _error(
                script_label,
                line_number,
                "make stdin target/option '-' is not supported",
            )
        if "=" not in token:
            raise _error(
                script_label,
                line_number,
                f"explicit make target {token!r} is not supported; the "
                "supported legacy recipe builds the default target",
            )
        # Make accepts whitespace and multiple assignment operators.  A
        # variable-name denylist cannot establish safe build semantics;
        # standard supported recipes need no command-line assignments.
        raise _error(
            script_label,
            line_number,
            f"make variable assignment {token!r} is not supported by the "
            "legacy recipe; review custom build semantics explicitly",
        )

    return {"build_args": build_args}


def parse_legacy_build_script(
    text: str,
    *,
    expected_configuration: str,
    script_label: str,
) -> dict[str, Any]:
    """Parse the supported subset of an MCUXpresso SDK legacy build script.

    The original shell script is never executed.  Only the known cache
    cleanup, one cmake configure invocation, and one make build invocation are
    accepted.  Anything else fails closed with the script path and line number.
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("\ufeff"):
        normalized = normalized[1:]

    cleanup: list[dict[str, str]] = []
    configure: dict[str, Any] | None = None
    build: dict[str, Any] | None = None

    for line_number, raw_line in enumerate(normalized.split("\n"), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        cleanup_match = _CLEANUP_RE.fullmatch(line)
        if cleanup_match is not None:
            if configure is not None or build is not None:
                raise _error(
                    script_label,
                    line_number,
                    "cache cleanup must appear before the configure/build commands",
                )
            cleanup.append(_cleanup_entry(cleanup_match, script_label, line_number))
            continue

        words = _words(line, script_label, line_number)
        if not words:
            continue
        if words[0] == "cmake":
            if configure is not None:
                raise _error(
                    script_label,
                    line_number,
                    "multiple cmake configure invocations are not supported",
                )
            if build is not None:
                raise _error(
                    script_label,
                    line_number,
                    "cmake configure must appear before the make build",
                )
            configure = _parse_configure(
                words,
                expected_configuration=expected_configuration,
                script_label=script_label,
                line_number=line_number,
            )
        elif words[0] == "make":
            if build is not None:
                raise _error(
                    script_label,
                    line_number,
                    "multiple make build invocations are not supported",
                )
            if configure is None:
                raise _error(
                    script_label,
                    line_number,
                    "make build must appear after the cmake configure",
                )
            build = _parse_make(
                words,
                script_label=script_label,
                line_number=line_number,
            )
        else:
            raise _error(
                script_label,
                line_number,
                f"unsupported command {words[0]!r}; the legacy recipe only accepts "
                "known cache cleanup, one cmake configure, and one make build",
            )

    if configure is None:
        raise ToolError(
            f"{script_label}: no supported cmake configure invocation was found"
        )
    if build is None:
        raise ToolError(f"{script_label}: no supported make build invocation was found")

    return {
        "cleanup": cleanup,
        "configure_argv": configure["configure_argv"],
        "generator": configure["generator"],
        "build_type": configure["build_type"],
        "build_args": build["build_args"],
    }
