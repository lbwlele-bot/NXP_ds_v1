from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import yaml

from compile_tool import m_sdk
from compile_tool.artifacts import resolve_artifact_inputs
from compile_tool.common import ToolError, hash_file
from compile_tool.legacy_build import parse_legacy_build_script
from compile_tool.manifest import load_manifest
from compile_tool.planner import assess
from compile_tool.public_checklists import (
    materialize_public_manifest,
    normalize_public_checklist,
)
from compile_tool.state import load_state
from tests.test_checklists import ChecklistFixture


def _legacy_script_text(
    make_line: str = "make -j 2>&1 | tee build_log.txt",
    *,
    newline: str = "\n",
    build_type: str = "release",
    generator: str = "Unix Makefiles",
    extra_lines: tuple[str, ...] = (),
    messy_whitespace: bool = False,
    cmake_line: str | None = None,
) -> str:
    if messy_whitespace:
        cleanup = [
            '  if   [ -d  "CMakeFiles" ] ; then   rm   -rf   CMakeFiles ; fi  ',
            'if [ -f "Makefile" ];   then rm -f Makefile; fi',
            'if [ -f "build.ninja" ];then rm -f build.ninja; fi',
            'if [ -f "cmake_install.cmake" ];then rm -f cmake_install.cmake; fi',
            'if [ -f "CMakeCache.txt" ];then rm -f CMakeCache.txt; fi',
        ]
        cmake = (
            '  cmake   -DCMAKE_TOOLCHAIN_FILE="../../tools/cmake_toolchain_files/armgcc.cmake"'
            f'   -G   "{generator}"   -DCMAKE_BUILD_TYPE={build_type}   .  '
        )
    else:
        cleanup = [
            'if [ -d "CMakeFiles" ];then rm -rf CMakeFiles; fi',
            'if [ -f "Makefile" ];then rm -f Makefile; fi',
            'if [ -f "build.ninja" ];then rm -f build.ninja; fi',
            'if [ -f "cmake_install.cmake" ];then rm -f cmake_install.cmake; fi',
            'if [ -f "CMakeCache.txt" ];then rm -f CMakeCache.txt; fi',
        ]
        cmake = (
            'cmake -DCMAKE_TOOLCHAIN_FILE="../../tools/cmake_toolchain_files/armgcc.cmake"'
            f' -G "{generator}" -DCMAKE_BUILD_TYPE={build_type}  .'
        )
    lines = [
        "#!/bin/sh",
        *cleanup,
        cmake if cmake_line is None else cmake_line,
        make_line,
        *extra_lines,
    ]
    return newline.join(lines) + newline


class LegacyBuildScriptTests(unittest.TestCase):
    def test_accepts_unbounded_and_explicit_make_jobs(self) -> None:
        for make_line in (
            "make -j 2>&1 | tee build_log.txt",
            "make -j 8 2>&1 | tee build_log.txt",
            "make -j8",
            "make --jobs 8",
            "make --jobs=8",
            "make",
        ):
            with self.subTest(make_line=make_line):
                recipe = parse_legacy_build_script(
                    _legacy_script_text(make_line),
                    expected_configuration="release",
                    script_label="fixture/build_release.sh",
                )
                self.assertEqual(recipe["build_args"], [])
                self.assertEqual(recipe["build_type"], "release")
                self.assertEqual(recipe["generator"], "Unix Makefiles")
                self.assertNotIn("tee", recipe["build_args"])

    def test_accepts_crlf_and_messy_whitespace(self) -> None:
        recipe = parse_legacy_build_script(
            _legacy_script_text(
                "make -j 4 2>&1 | tee build_log.txt",
                newline="\r\n",
                messy_whitespace=True,
            ),
            expected_configuration="release",
            script_label="fixture/build_release.sh",
        )
        self.assertEqual(
            recipe["cleanup"],
            [
                {"kind": "directory", "name": "CMakeFiles"},
                {"kind": "file", "name": "Makefile"},
                {"kind": "file", "name": "build.ninja"},
                {"kind": "file", "name": "cmake_install.cmake"},
                {"kind": "file", "name": "CMakeCache.txt"},
            ],
        )
        self.assertIn("Unix Makefiles", recipe["configure_argv"])
        self.assertIn(
            "-DCMAKE_TOOLCHAIN_FILE=../../tools/cmake_toolchain_files/armgcc.cmake",
            recipe["configure_argv"],
        )

    def test_rejects_extra_executable_line(self) -> None:
        text = _legacy_script_text(
            extra_lines=("cp release/hello.elf /tmp/hello.elf",)
        )
        with self.assertRaisesRegex(
            ToolError,
            r"fixture/build_release\.sh: line 9: unsupported command 'cp'",
        ):
            parse_legacy_build_script(
                text,
                expected_configuration="release",
                script_label="fixture/build_release.sh",
            )

    def test_rejects_unknown_cleanup_target(self) -> None:
        text = _legacy_script_text().replace(
            'if [ -d "CMakeFiles" ];then rm -rf CMakeFiles; fi',
            'if [ -d "src" ];then rm -rf src; fi',
        )
        with self.assertRaisesRegex(ToolError, r"unsupported legacy cache cleanup target 'src'"):
            parse_legacy_build_script(
                text,
                expected_configuration="release",
                script_label="fixture/build_release.sh",
            )

    def test_rejects_unsupported_generator_and_clean_target(self) -> None:
        with self.assertRaisesRegex(ToolError, r"unsupported cmake generator 'Ninja'"):
            parse_legacy_build_script(
                _legacy_script_text(generator="Ninja"),
                expected_configuration="release",
                script_label="fixture/build_release.sh",
            )
        with self.assertRaisesRegex(
            ToolError, r"explicit make target 'clean' is not supported"
        ):
            parse_legacy_build_script(
                _legacy_script_text("make -j8 clean"),
                expected_configuration="release",
                script_label="fixture/build_release.sh",
            )

    def test_rejects_build_type_mismatch(self) -> None:
        with self.assertRaisesRegex(ToolError, r"does not match selected build_configuration"):
            parse_legacy_build_script(
                _legacy_script_text(build_type="debug"),
                expected_configuration="release",
                script_label="fixture/build_release.sh",
            )

    def test_rejects_make_directory_makefile_and_option_groups(self) -> None:
        bad_lines = (
            "make -C../outside -j",
            "make -C ../outside -j",
            "make --directory=../outside -j",
            "make --directory ../outside -j",
            "make -f../outside -j",
            "make -f ../outside -j",
            "make --file=../outside -j",
            "make --file ../outside -j",
            "make --makefile=../outside -j",
            "make -o old -j",
            "make -W new -j",
            "make -n -j",
            "make -t -j",
            "make -q -j",
            "make -I../include -j",
            "make --include-dir=../include -j",
            "make --jobserver-auth=3,4 -j",
            "make --jobserver-fds=3,4 -j",
            "make -kj",
            "make -skj4",
            "make -j all",
            "make -j -s",
        )
        for make_line in bad_lines:
            with self.subTest(make_line=make_line):
                with self.assertRaisesRegex(
                    ToolError, r"fixture/build_release\.sh: line 8:"
                ):
                    parse_legacy_build_script(
                        _legacy_script_text(make_line),
                        expected_configuration="release",
                        script_label="fixture/build_release.sh",
                    )

    def test_rejects_make_control_variable_assignments(self) -> None:
        for assignment in (
            "MAKEFLAGS=-j64",
            "MFLAGS=-j64",
            "GNUMAKEFLAGS=-j64",
            "MAKEFILES=../outside.mk",
            "MAKEOVERRIDES=MAKEFLAGS",
            "MAKELEVEL=1",
            "SHELL=/bin/bash",
            "MAKE=evil",
            "MAKEFLAGS+=-j64",
            '"MAKEFLAGS =-j"',
            '" MAKEFLAGS=-j"',
            '"MAKEFLAGS\t=-j"',
            "MAKEFLAGS:=-j",
            "MAKEFLAGS?=-j",
            "CMAKE_COMMAND=other",
            "AR=other",
        ):
            with self.subTest(assignment=assignment):
                with self.assertRaisesRegex(
                    ToolError, r"fixture/build_release\.sh: line 8:"
                ):
                    parse_legacy_build_script(
                        _legacy_script_text(f"make -j {assignment}"),
                        expected_configuration="release",
                        script_label="fixture/build_release.sh",
                    )

    def test_rejects_unreviewed_make_variable_assignments(self) -> None:
        for assignment in ("V=1", "CFLAGS=-O2", "VERBOSE=1"):
            with self.subTest(assignment=assignment):
                with self.assertRaisesRegex(ToolError, "variable assignment"):
                    parse_legacy_build_script(
                        _legacy_script_text(f"make -j {assignment}"),
                        expected_configuration="release",
                        script_label="fixture/build_release.sh",
                    )

    def test_rejects_cmake_non_configure_modes(self) -> None:
        common = (
            "-DCMAKE_BUILD_TYPE=release "
            "-DCMAKE_TOOLCHAIN_FILE=../toolchain.cmake "
            '-G "Unix Makefiles" .'
        )
        for cmake_line in (
            f"cmake -Pexternal.cmake {common}",
            f"cmake -P external.cmake {common}",
            "cmake --build . -- -j8",
            "cmake --build=.",
            "cmake -E echo hi",
            "cmake -Eecho hi",
        ):
            with self.subTest(cmake_line=cmake_line):
                with self.assertRaisesRegex(
                    ToolError, r"fixture/build_release\.sh: line 7:"
                ):
                    parse_legacy_build_script(
                        _legacy_script_text(cmake_line=cmake_line),
                        expected_configuration="release",
                        script_label="fixture/build_release.sh",
                    )

    def test_rejects_cmake_backend_and_unknown_options(self) -> None:
        prefix = (
            "cmake -DCMAKE_BUILD_TYPE=release "
            "-DCMAKE_TOOLCHAIN_FILE=../toolchain.cmake "
        )
        suffix = ' -G "Unix Makefiles" .'
        for extra in (
            "-DCMAKE_MAKE_PROGRAM=ninja",
            "-DCMAKE_GENERATOR=Ninja",
            "-DCMAKE_C_COMPILER=clang",
            "-DCMAKE_C_FLAGS=-O2",
            "-T ninja",
            "-A x64",
            "-Bbuild",
            "-Ccache.cmake",
            "--toolchain ../toolchain.cmake",
            "--install-prefix /tmp",
            "--fresh",
            "-U CMAKE_BUILD_TYPE",
            "-Wdev",
            "--unknown",
        ):
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(
                    ToolError, r"fixture/build_release\.sh: line 7:"
                ):
                    parse_legacy_build_script(
                        _legacy_script_text(cmake_line=prefix + extra + suffix),
                        expected_configuration="release",
                        script_label="fixture/build_release.sh",
                    )

    def test_requires_explicit_toolchain_and_accepts_explicit_source(self) -> None:
        without_toolchain = (
            'cmake -DCMAKE_BUILD_TYPE=release -G "Unix Makefiles" .'
        )
        with self.assertRaisesRegex(
            ToolError, r"must declare CMAKE_TOOLCHAIN_FILE"
        ):
            parse_legacy_build_script(
                _legacy_script_text(cmake_line=without_toolchain),
                expected_configuration="release",
                script_label="fixture/build_release.sh",
            )
        with_source_option = (
            "cmake -DCMAKE_BUILD_TYPE=release "
            "-DCMAKE_TOOLCHAIN_FILE=../toolchain.cmake "
            '-G "Unix Makefiles" -S .'
        )
        recipe = parse_legacy_build_script(
            _legacy_script_text(cmake_line=with_source_option),
            expected_configuration="release",
            script_label="fixture/build_release.sh",
        )
        self.assertIn("-S", recipe["configure_argv"])


class MSdkChecklistTests(unittest.TestCase):
    def _compiler(self, root: Path, version: str = "14.3") -> Path:
        compiler = root / "toolchain" / "bin" / "arm-none-eabi-gcc"
        compiler.parent.mkdir(parents=True)
        compiler.write_text(f"#!/bin/sh\nprintf 'arm-none-eabi-gcc {version}\\n'\n")
        compiler.chmod(0o755)
        return compiler

    def _legacy_archive(
        self,
        root: Path,
        *,
        second_core: bool = False,
        make_line: str = "make -j 2>&1 | tee build_log.txt",
        newline: str = "\n",
        extra_lines: tuple[str, ...] = (),
        messy_whitespace: bool = False,
        cmake_line: str | None = None,
    ) -> Path:
        source = root / "archive-source"
        cores = ["cm7", "cm7b"] if second_core else ["cm7"]
        for core in cores:
            project = source / "boards" / "fixture" / "demo_apps" / "hello_world" / core / "armgcc"
            project.mkdir(parents=True)
            (project / "CMakeLists.txt").write_text(
                f"set(MCUX_SDK_PROJECT_NAME hello_world_{core}.elf)\n"
                "ADD_CUSTOM_COMMAND(TARGET demo POST_BUILD COMMAND tool "
                "${EXECUTABLE_OUTPUT_PATH}/hello_world.bin)\n"
            )
            (project / "keep.c").write_text("/* user source must survive cleanup */\n")
            (project / "build_release.sh").write_text(
                _legacy_script_text(
                    make_line,
                    newline=newline,
                    extra_lines=extra_lines,
                    messy_whitespace=messy_whitespace,
                    cmake_line=cmake_line,
                )
            )
        prebuilt = source / "boards" / "fixture" / "demo_apps" / "hello_world"
        (prebuilt / "hello_world.bin").write_bytes(b"vendor-default-bin")
        archive = root / "SDK_25_09_00_FIXTURE.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            for path in sorted(source.rglob("*")):
                handle.add(path, arcname=path.relative_to(source))
        return archive

    @contextmanager
    def _fake_build_tools(self, root: Path):
        tools = root / "fake-build-tools"
        tools.mkdir(parents=True, exist_ok=True)
        cmake = tools / "cmake"
        cmake.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "log = os.environ.get('FAKE_CMAKE_LOG')\n"
            "if log:\n"
            "    with open(log, 'a', encoding='utf-8') as handle:\n"
            "        handle.write(' '.join(args) + '\\n')\n"
            "if os.environ.get('FAKE_CMAKE_FAIL') == '1':\n"
            "    print('fake cmake configure failure', file=sys.stderr)\n"
            "    sys.exit(7)\n"
            "if os.environ.get('CMAKE_GENERATOR') != 'Unix Makefiles':\n"
            "    print('fake cmake: inherited generator environment', file=sys.stderr)\n"
            "    sys.exit(11)\n"
            "if os.environ.get('CMAKE_MAKE_PROGRAM') != 'make':\n"
            "    print('fake cmake: inherited make program environment', file=sys.stderr)\n"
            "    sys.exit(12)\n"
            "build_type = None\n"
            "generator = None\n"
            "index = 0\n"
            "while index < len(args):\n"
            "    arg = args[index]\n"
            "    definition = None\n"
            "    if arg == '-D':\n"
            "        index += 1\n"
            "        definition = args[index]\n"
            "    elif arg.startswith('-D'):\n"
            "        definition = arg[2:]\n"
            "    if definition is not None:\n"
            "        key, separator, value = definition.partition('=')\n"
            "        if separator and key.split(':', 1)[0] == 'CMAKE_BUILD_TYPE':\n"
            "            build_type = value\n"
            "    elif arg == '-G':\n"
            "        index += 1\n"
            "        generator = args[index]\n"
            "    index += 1\n"
            "if not build_type:\n"
            "    print('fake cmake: missing CMAKE_BUILD_TYPE', file=sys.stderr)\n"
            "    sys.exit(9)\n"
            "if generator not in (None, 'Unix Makefiles'):\n"
            "    print('fake cmake: unexpected generator ' + generator, file=sys.stderr)\n"
            "    sys.exit(10)\n"
            "pathlib.Path(build_type).mkdir(parents=True, exist_ok=True)\n"
            "pathlib.Path('CMakeFiles').mkdir(exist_ok=True)\n"
            "pathlib.Path('Makefile').write_text('# fake generated makefile\\n')\n"
            "pathlib.Path('CMakeCache.txt').write_text(\n"
            "    'CMAKE_BUILD_TYPE:STRING=' + build_type + '\\n'\n"
            ")\n"
            "print('fake cmake configured ' + build_type)\n"
        )
        cmake.chmod(0o755)
        make = tools / "make"
        make.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, re, sys\n"
            "args = sys.argv[1:]\n"
            "log = os.environ.get('FAKE_MAKE_LOG')\n"
            "if log:\n"
            "    with open(log, 'a', encoding='utf-8') as handle:\n"
            "        handle.write(' '.join(args) + '\\n')\n"
            "for name in ('MAKEFLAGS', 'MFLAGS', 'GNUMAKEFLAGS', 'MAKEFILES'):\n"
            "    if os.environ.get(name):\n"
            "        print('fake make: inherited ' + name, file=sys.stderr)\n"
            "        sys.exit(95)\n"
            "if any(arg in ('-j', '--jobs') for arg in args):\n"
            "    print('fake make: unbounded job count', file=sys.stderr)\n"
            "    sys.exit(90)\n"
            "jobs = [arg for arg in args if re.fullmatch(r'-j\\d+', arg)]\n"
            "if len(jobs) != 1:\n"
            "    print('fake make: expected exactly one finite -jN', file=sys.stderr)\n"
            "    sys.exit(91)\n"
            "if int(jobs[0][2:]) < 1:\n"
            "    print('fake make: job count must be positive', file=sys.stderr)\n"
            "    sys.exit(92)\n"
            "if os.environ.get('FAKE_MAKE_FAIL') == '1':\n"
            "    print('fake make build failure', file=sys.stderr)\n"
            "    sys.exit(8)\n"
            "cache = pathlib.Path('CMakeCache.txt')\n"
            "if not cache.is_file():\n"
            "    print('fake make: CMakeCache.txt is missing', file=sys.stderr)\n"
            "    sys.exit(93)\n"
            "build_type = None\n"
            "for line in cache.read_text().splitlines():\n"
            "    if line.startswith('CMAKE_BUILD_TYPE:'):\n"
            "        build_type = line.split('=', 1)[1]\n"
            "cmake_text = pathlib.Path('CMakeLists.txt').read_text()\n"
            "elf_match = re.search(r'MCUX_SDK_PROJECT_NAME\\s+([^\\s\\)]+[.]elf)', cmake_text)\n"
            "bin_matches = re.findall(r'[/}]([A-Za-z0-9_.+-]+[.]bin)\\b', cmake_text)\n"
            "if elf_match is None or not bin_matches or not build_type:\n"
            "    print('fake make: cannot resolve outputs', file=sys.stderr)\n"
            "    sys.exit(94)\n"
            "core = pathlib.Path.cwd().parent.name\n"
            "out = pathlib.Path(build_type)\n"
            "out.mkdir(exist_ok=True)\n"
            "(out / elf_match.group(1)).write_bytes(\n"
            "    b'\\x7fELF' + ('-' + core + '-' + build_type).encode()\n"
            ")\n"
            "(out / bin_matches[-1]).write_bytes(\n"
            "    ('BIN-' + core + '-' + build_type).encode()\n"
            ")\n"
            "print('fake make built ' + core + ' ' + build_type)\n"
        )
        make.chmod(0o755)
        with patch.dict(
            os.environ,
            {"PATH": str(tools) + os.pathsep + os.environ.get("PATH", "")},
        ):
            yield tools

    def _west_archive(self, root: Path, release: str = "25.12.00") -> Path:
        archive = root / f"SDK_{release.replace('.', '_')}_FIXTURE.zip"
        example = {
            "hello_world": {
                "boards": {"fixture@cm7": ["+armgcc@debug", "+armgcc@release"]}
            }
        }
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr(".west/config", "[manifest]\npath = manifests\nfile = west.yml\n")
            handle.writestr("manifests/west.yml", "manifest:\n  projects: []\n")
            handle.writestr("mcuxsdk/scripts/west_commands/build.py", "# fixture\n")
            handle.writestr(
                "mcuxsdk/scripts/west_commands.yml",
                "west-commands:\n  - file: scripts/west_commands/build.py\n",
            )
            handle.writestr(
                "mcuxsdk/examples/demo_apps/hello_world/example.yml",
                yaml.safe_dump(example, sort_keys=False),
            )
            handle.writestr(
                "mcuxsdk/examples/demo_apps/hello_world/CMakeLists.txt",
                "project(hello_world LANGUAGES C ASM)\n",
            )
        return archive

    def _catalog(
        self,
        root: Path,
        archive: Path,
        *,
        release: str = "25.09.00",
        cores: dict[str, str] | None = None,
        compiler_constraint: str | None = None,
    ) -> Path:
        catalog = root / "packages" / "PACKAGES.yaml"
        catalog.parent.mkdir(parents=True)
        copied = catalog.parent / archive.name
        copied.write_bytes(archive.read_bytes())
        package = {
            "archive": copied.name,
            "sha256": hash_file(copied),
            "sdk_release": release,
            "soc": "imxfixture",
            "boards": {
                "fixture": {"core_roles": cores or {"cm7": "m7"}}
            },
        }
        if compiler_constraint:
            package["compiler_version_contains"] = compiler_constraint
        catalog.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "kind": "m_freertos_sdk_package_catalog",
                    "packages": {"SDK_FIXTURE": package},
                },
                sort_keys=False,
            )
        )
        return catalog

    def _case(self, root: Path) -> Path:
        case = root / "support_level" / "work" / "m-sdk-case"
        (case / "records" / "compile" / "m_freertos_sdk").mkdir(parents=True)
        return case

    def _checklist(
        self,
        case: Path,
        compiler: Path,
        jobs: dict,
        *,
        scope: list[str] | None = None,
        sdk: dict | None = None,
        parallelism: object = None,
    ) -> Path:
        path = case / "records" / "compile" / "m_freertos_sdk" / "compile.yaml"
        payload = {
            "schema_version": 1,
            "kind": "m_freertos_sdk_compile_checklist",
            "target": "m_freertos_sdk",
            "case_root": str(case),
            "sdk": sdk or {"package": "SDK_FIXTURE", "compiler": str(compiler)},
            "jobs": jobs,
            "intent": {
                "scope": list(jobs) if scope is None else scope,
                "reason": "fixture M SDK producer validation",
            },
        }
        if parallelism is not None:
            payload["parallelism"] = parallelism
        path.write_text(yaml.safe_dump(payload, sort_keys=False))
        return path

    @staticmethod
    def _source_job(core: str = "cm7", role: str = "m7") -> dict:
        return {
            "mode": "source_build",
            "soc": "imxfixture",
            "board": "fixture",
            "core": core,
            "core_role": role,
            "application": "demo_apps/hello_world",
            "build_configuration": "release",
        }

    def test_backend_cutoff_is_exact(self) -> None:
        self.assertEqual(m_sdk.select_backend("2.9.0"), "legacy")
        self.assertEqual(m_sdk.select_backend("25.09.00"), "legacy")
        self.assertEqual(m_sdk.select_backend("25.12.00"), "west")
        self.assertEqual(m_sdk.select_backend("26.06.00"), "west")
        with self.assertRaisesRegex(ToolError, "2510/2511"):
            m_sdk.select_backend("25.10.00")
        with self.assertRaisesRegex(ToolError, "unsupported M SDK release format"):
            m_sdk.select_backend("release-latest")

    def test_missing_selected_package_requests_user_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            catalog_archive = catalog.parent / archive.name
            catalog_archive.unlink()
            compiler = self._compiler(root)
            case = self._case(root)
            checklist = self._checklist(case, compiler, {"m7": self._source_job()})
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with self.assertRaisesRegex(ToolError, "STATUS: USER_INPUT_REQUIRED"):
                    m_sdk.normalize_m_sdk_checklist(checklist)

    def test_unrelated_missing_catalog_package_does_not_block_selected_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            raw = yaml.safe_load(catalog.read_text())
            raw["packages"]["SDK_MISSING_UNUSED"] = {
                **raw["packages"]["SDK_FIXTURE"],
                "archive": "missing-unused.zip",
            }
            catalog.write_text(yaml.safe_dump(raw, sort_keys=False))
            compiler = self._compiler(root)
            case = self._case(root)
            checklist = self._checklist(case, compiler, {"m7": self._source_job()})
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                normalized = m_sdk.normalize_m_sdk_checklist(checklist)
            self.assertEqual(normalized["package"]["id"], "SDK_FIXTURE")

    def test_user_provided_unregistered_sdk_builds_without_catalog_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            supplied = case / "inputs" / "sdk" / "customer-sdk.tar.gz"
            supplied.parent.mkdir(parents=True)
            supplied.write_bytes(archive.read_bytes())
            checklist = self._checklist(
                case,
                compiler,
                {"m7": self._source_job()},
                sdk={
                    "package": "CUSTOMER_SDK_25_09",
                    "archive": str(supplied.relative_to(case)),
                    "sdk_release": "25.09.00",
                    "trust_reason": "user downloaded this package from NXP",
                    "compiler": str(compiler),
                },
            )
            with patch.object(m_sdk, "CATALOG_PATH", catalog), self._fake_build_tools(root):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(m_sdk.prepare_m_sdk_checklist(checklist), 0)
                    self.assertEqual(m_sdk.run_m_sdk_checklist(checklist), 0)
                normalized = m_sdk.normalize_m_sdk_checklist(checklist)
                manifest = m_sdk.materialize_m_sdk_manifest(normalized)
                state = load_state(manifest)["components"]["m7"]
            self.assertEqual(normalized["package"]["assurance"], "user_attested")
            self.assertEqual(
                state["origin"]["details"]["package_assurance"], "user_attested"
            )

    def test_legacy_source_build_exports_sibling_elf_and_bin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            checklist_path = self._checklist(case, compiler, {"m7": self._source_job()})
            with patch.object(m_sdk, "CATALOG_PATH", catalog), self._fake_build_tools(root):
                prepared_output = io.StringIO()
                with redirect_stdout(prepared_output):
                    self.assertEqual(m_sdk.prepare_m_sdk_checklist(checklist_path), 0)
                self.assertIn("受控 backend：legacy", prepared_output.getvalue())
                self.assertIn("软件状态：PENDING_SOURCE_ACQUISITION", prepared_output.getvalue())
                self.assertIn("build_release.sh", prepared_output.getvalue())
                self.assertIn("有效构建并发：2", prepared_output.getvalue())
                self.assertIn("cmake -DCMAKE_TOOLCHAIN_FILE", prepared_output.getvalue())
                self.assertIn("make -j2", prepared_output.getvalue())
                self.assertNotIn("| tee", prepared_output.getvalue())
                request = yaml.safe_load(
                    (checklist_path.parent / ".compile-tool-request.yaml").read_text()
                )
                self.assertEqual(
                    [step["name"] for step in request["compile"]["units"][0]["steps"]],
                    [
                        "clean-m7",
                        "configure-m7",
                        "build-m7",
                        "publish-m7-elf",
                        "publish-m7-bin",
                    ],
                )
                steps = request["compile"]["units"][0]["steps"]
                configure_env = steps[1]["env"]
                build_env = steps[2]["env"]
                self.assertEqual(configure_env["CMAKE_GENERATOR"], "Unix Makefiles")
                self.assertEqual(configure_env["CMAKE_MAKE_PROGRAM"], "make")
                for name in (
                    "MAKEFLAGS",
                    "MFLAGS",
                    "GNUMAKEFLAGS",
                    "MAKEFILES",
                    "MAKEOVERRIDES",
                ):
                    self.assertEqual(build_env[name], "")
                self.assertEqual(build_env["MAKELEVEL"], "0")
                with patch.dict(
                    os.environ,
                    {
                        "MAKEFLAGS": "-j64",
                        "MFLAGS": "-j64",
                        "GNUMAKEFLAGS": "-j64",
                        "MAKEFILES": "../outside.mk",
                        "CMAKE_GENERATOR": "Ninja",
                        "CMAKE_MAKE_PROGRAM": "ninja",
                    },
                ):
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(m_sdk.run_m_sdk_checklist(checklist_path), 0)
                manifest = m_sdk.materialize_m_sdk_manifest(
                    m_sdk.normalize_m_sdk_checklist(checklist_path)
                )
                self.assertEqual(assess(manifest)["state_summary"], "MATCHED")
                self.assertTrue((case / "artifacts/m_freertos_sdk/m7/m7.elf").is_file())
                self.assertTrue((case / "artifacts/m_freertos_sdk/m7/m7.bin").is_file())
                self.assertEqual(
                    len(list((case / "sources/m_freertos_sdk").rglob("keep.c"))), 1
                )
                source_script = next(
                    (case / "sources/m_freertos_sdk").rglob("build_release.sh")
                )
                self.assertEqual(source_script.read_text(), _legacy_script_text())
                state = load_state(manifest)["components"]["m7"]
                self.assertEqual(state["origin"]["mode"], "source_build")
                self.assertEqual(state["origin"]["assurance"], "locally_built")
                self.assertEqual(
                    state["configuration"]["values"]["parallelism"], "2"
                )
                self.assertNotIn("parallelism", manifest["exports"]["m7.elf"]["identity"])

    def test_legacy_crlf_script_with_explicit_jobs_uses_checklist_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(
                root,
                make_line="make -j 8 2>&1 | tee build_log.txt",
                newline="\r\n",
                messy_whitespace=True,
            )
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            checklist = self._checklist(
                case, compiler, {"m7": self._source_job()}, parallelism=3
            )
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                prepared = io.StringIO()
                with redirect_stdout(prepared):
                    m_sdk.prepare_m_sdk_checklist(checklist)
            rendered = prepared.getvalue()
            self.assertIn("有效构建并发：3", rendered)
            self.assertIn("Unix Makefiles", rendered)
            self.assertIn("make -j3", rendered)
            self.assertNotIn("| tee", rendered)
            self.assertNotIn("-j 8", rendered)

    def test_unknown_legacy_script_line_is_rejected_before_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(
                root, extra_lines=("cp release/hello_world_cm7.elf /tmp/copied.elf",)
            )
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            checklist = self._checklist(case, compiler, {"m7": self._source_job()})
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with self.assertRaisesRegex(
                    ToolError,
                    r"build_release\.sh: line 9: unsupported command 'cp'",
                ):
                    m_sdk.normalize_m_sdk_checklist(checklist)
            self.assertFalse(
                (checklist.parent / ".compile-tool-prepared.yaml").exists()
            )

    def test_legacy_script_rejects_unsafe_make_and_cmake_shapes(self) -> None:
        cases = (
            {"make_line": "make -kj"},
            {"make_line": "make -C../outside -j"},
            {"make_line": "make --file=../outside -j"},
            {
                "cmake_line": (
                    'cmake -Pexternal.cmake -DCMAKE_BUILD_TYPE=release '
                    '-DCMAKE_TOOLCHAIN_FILE=../toolchain.cmake '
                    '-G "Unix Makefiles" .'
                )
            },
        )
        for case_kwargs in cases:
            with self.subTest(case=case_kwargs):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    archive = self._legacy_archive(root, **case_kwargs)
                    catalog = self._catalog(root, archive)
                    compiler = self._compiler(root)
                    case = self._case(root)
                    checklist = self._checklist(
                        case, compiler, {"m7": self._source_job()}
                    )
                    with patch.object(m_sdk, "CATALOG_PATH", catalog):
                        with self.assertRaisesRegex(
                            ToolError, r"build_release\.sh: line [78]:"
                        ):
                            m_sdk.normalize_m_sdk_checklist(checklist)
                    self.assertFalse(
                        (checklist.parent / ".compile-tool-prepared.yaml").exists()
                    )

    def test_parallelism_defaults_and_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            for value in (0, -1, 1.5, "2", True):
                with self.subTest(value=value):
                    checklist = self._checklist(
                        case, compiler, {"m7": self._source_job()}, parallelism=value
                    )
                    with patch.object(m_sdk, "CATALOG_PATH", catalog):
                        with self.assertRaisesRegex(
                            ToolError, "parallelism must be a positive integer"
                        ):
                            m_sdk.normalize_m_sdk_checklist(checklist)
            checklist = self._checklist(
                case, compiler, {"m7": self._source_job()}, parallelism=4
            )
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                self.assertEqual(
                    m_sdk.normalize_m_sdk_checklist(checklist)["parallelism"], 4
                )
            checklist = self._checklist(
                case, compiler, {"m7": self._source_job()}
            )
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                self.assertEqual(
                    m_sdk.normalize_m_sdk_checklist(checklist)["parallelism"], 2
                )

    def test_prepare_shows_effective_parallelism_and_change_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            checklist_path = self._checklist(
                case, compiler, {"m7": self._source_job()}, parallelism=2
            )
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                prepared = io.StringIO()
                with redirect_stdout(prepared):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                self.assertIn("有效构建并发：2", prepared.getvalue())
                request = yaml.safe_load(
                    (checklist_path.parent / ".compile-tool-request.yaml").read_text()
                )
                self.assertEqual(
                    [step["name"] for step in request["compile"]["units"][0]["steps"]],
                    [
                        "clean-m7",
                        "configure-m7",
                        "build-m7",
                        "publish-m7-elf",
                        "publish-m7-bin",
                    ],
                )
                self.assertIn(
                    "make -j2",
                    request["compile"]["units"][0]["steps"][2]["command"],
                )
                self.assertNotIn(
                    "| tee",
                    "\n".join(
                        step["command"]
                        for step in request["compile"]["units"][0]["steps"]
                    ),
                )
                self.assertIn("m7", request["decision"]["destructive"])

                raw = yaml.safe_load(checklist_path.read_text())
                raw["parallelism"] = 4
                checklist_path.write_text(yaml.safe_dump(raw, sort_keys=False))
                with self.assertRaisesRegex(
                    ToolError, "changed after prepare; run prepare again"
                ):
                    m_sdk.run_m_sdk_checklist(checklist_path)

                prepared = io.StringIO()
                with redirect_stdout(prepared):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                self.assertIn("有效构建并发：4", prepared.getvalue())
                request = yaml.safe_load(
                    (checklist_path.parent / ".compile-tool-request.yaml").read_text()
                )
                self.assertIn(
                    "make -j4",
                    request["compile"]["units"][0]["steps"][2]["command"],
                )

    def test_old_prepare_contract_is_invalidated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            checklist_path = self._checklist(
                case, compiler, {"m7": self._source_job()}
            )
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                prepared_path = checklist_path.parent / ".compile-tool-prepared.yaml"
                prepared = yaml.safe_load(prepared_path.read_text())
                prepared.pop("contract_version")
                prepared_path.write_text(yaml.safe_dump(prepared, sort_keys=False))
                with self.assertRaisesRegex(
                    ToolError, "changed after prepare; run prepare again"
                ):
                    m_sdk.run_m_sdk_checklist(checklist_path)

    def test_configure_or_build_failure_does_not_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            checklist_path = self._checklist(
                case, compiler, {"m7": self._source_job()}
            )
            artifact = case / "artifacts/m_freertos_sdk/m7/m7.elf"
            with patch.object(m_sdk, "CATALOG_PATH", catalog), self._fake_build_tools(root):
                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                with patch.dict(os.environ, {"FAKE_CMAKE_FAIL": "1"}):
                    with redirect_stdout(io.StringIO()):
                        configure_result = m_sdk.run_m_sdk_checklist(checklist_path)
                self.assertNotEqual(configure_result, 0)
                self.assertFalse(artifact.exists())

                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                with patch.dict(os.environ, {"FAKE_MAKE_FAIL": "1"}):
                    with redirect_stdout(io.StringIO()):
                        build_result = m_sdk.run_m_sdk_checklist(checklist_path)
                self.assertNotEqual(build_result, 0)
                self.assertFalse(artifact.exists())

                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                    self.assertEqual(m_sdk.run_m_sdk_checklist(checklist_path), 0)
                published = artifact.read_bytes()
                self.assertTrue(published)

                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                with patch.dict(os.environ, {"FAKE_CMAKE_FAIL": "1"}):
                    with redirect_stdout(io.StringIO()):
                        failed_configure = m_sdk.run_m_sdk_checklist(checklist_path)
                self.assertNotEqual(failed_configure, 0)
                self.assertEqual(artifact.read_bytes(), published)

                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                with patch.dict(os.environ, {"FAKE_MAKE_FAIL": "1"}):
                    with redirect_stdout(io.StringIO()):
                        failed_again = m_sdk.run_m_sdk_checklist(checklist_path)
                self.assertNotEqual(failed_again, 0)
                self.assertEqual(artifact.read_bytes(), published)

    def test_vendor_prebuilt_bin_is_imported_without_fake_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive, compiler_constraint="14.3")
            compiler = self._compiler(root)
            case = self._case(root)
            job = self._source_job()
            job["mode"] = "prebuilt_import"
            job["provenance"] = {
                "kind": "vendor_package",
                "artifacts": {
                    "bin": {
                        "member": "boards/fixture/demo_apps/hello_world/hello_world.bin"
                    }
                },
            }
            checklist_path = self._checklist(case, compiler, {"default_m7": job})
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                prepared = io.StringIO()
                with redirect_stdout(prepared):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                self.assertIn("有效构建并发：不适用", prepared.getvalue())
                self.assertNotIn("有效构建并发：2", prepared.getvalue())
                with redirect_stdout(io.StringIO()):
                    m_sdk.run_m_sdk_checklist(checklist_path)
                normalized = m_sdk.normalize_m_sdk_checklist(checklist_path)
                manifest = m_sdk.materialize_m_sdk_manifest(normalized)
                state = load_state(manifest)["components"]["default_m7"]
                self.assertEqual(state["kind"], "import")
                self.assertEqual(state["origin"]["mode"], "prebuilt_import")
                self.assertEqual(state["origin"]["assurance"], "catalog_verified")
                self.assertNotIn("parallelism", state["configuration"]["values"])
                request = yaml.safe_load(
                    (checklist_path.parent / ".compile-tool-request.yaml").read_text()
                )
                self.assertEqual(len(request["compile"]["units"]), 1)
                self.assertEqual(request["compile"]["units"][0]["action"], "import")
                self.assertEqual(request["compile"]["units"][0]["steps"][0]["env"], {})
                self.assertTrue(
                    request["compile"]["units"][0]["steps"][0]["command"].startswith(
                        "/usr/bin/install -D -m 0644 "
                    )
                )
                self.assertEqual(
                    (case / "artifacts/m_freertos_sdk/default_m7/default_m7.bin").read_bytes(),
                    b"vendor-default-bin",
                )
                self.assertNotIn("default_m7.elf", manifest["exports"])

    def test_user_supplied_requires_hash_and_records_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            supplied = case / "inputs" / "trusted.bin"
            supplied.parent.mkdir(parents=True)
            supplied.write_bytes(b"user-trusted-bin")
            job = self._source_job()
            job["mode"] = "prebuilt_import"
            job["provenance"] = {
                "kind": "user_supplied",
                "trust_reason": "user selected a known matching payload",
                "artifacts": {
                    "bin": {"path": str(supplied), "sha256": hash_file(supplied)}
                },
            }
            checklist_path = self._checklist(case, compiler, {"trusted": job})
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                    m_sdk.run_m_sdk_checklist(checklist_path)
                manifest = m_sdk.materialize_m_sdk_manifest(
                    m_sdk.normalize_m_sdk_checklist(checklist_path)
                )
                origin = load_state(manifest)["components"]["trusted"]["origin"]
                self.assertEqual(origin["assurance"], "user_attested")
                supplied.write_bytes(b"changed")
                with self.assertRaisesRegex(ToolError, "hash mismatch"):
                    m_sdk.normalize_m_sdk_checklist(checklist_path)

    def test_west_layout_generates_controlled_command_and_rejects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._west_archive(root)
            catalog = self._catalog(root, archive, release="25.12.00")
            compiler = self._compiler(root)
            case = self._case(root)
            checklist_path = self._checklist(case, compiler, {"m7": self._source_job()})
            with patch.object(m_sdk, "CATALOG_PATH", catalog), patch(
                "compile_tool.m_sdk.shutil.which", return_value="/usr/bin/west"
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                rendered = output.getvalue()
                self.assertIn("受控 backend：west", rendered)
                self.assertIn("有效构建并发：不适用", rendered)
                self.assertNotIn("有效构建并发：2", rendered)
                self.assertIn("west build -b fixture", rendered)
                self.assertIn("-p always", rendered)
                self.assertIn("--config release", rendered)
                self.assertIn("-Dcore_id=cm7", rendered)
                self.assertIn("hello_world_cm7.elf", rendered)
                manifest = load_manifest(checklist_path.parent / "manifest.yaml")
                self.assertNotIn(
                    "parallelism", manifest["components"]["m7"]["configuration"]["values"]
                )

            bad_catalog = self._catalog(root / "bad", archive, release="25.09.00")
            with patch.object(m_sdk, "CATALOG_PATH", bad_catalog):
                with self.assertRaisesRegex(ToolError, "legacy backend.*West layout"):
                    m_sdk.normalize_m_sdk_checklist(checklist_path)

    def test_jobs_outside_scope_must_have_reusable_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root, second_core=True)
            catalog = self._catalog(
                root, archive, cores={"cm7": "m70", "cm7b": "m71"}
            )
            compiler = self._compiler(root)
            case = self._case(root)
            jobs = {
                "m70": self._source_job("cm7", "m70"),
                "m71": self._source_job("cm7b", "m71"),
            }
            checklist_path = self._checklist(case, compiler, jobs, scope=["m70"])
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with self.assertRaisesRegex(ToolError, "every package-backed job"):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)

    def test_jobs_keep_independent_state_and_execution_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive, cores={"cm7": "m70"})
            compiler = self._compiler(root)
            case = self._case(root)

            def vendor_job() -> dict:
                job = self._source_job("cm7", "m70")
                job["mode"] = "prebuilt_import"
                job["provenance"] = {
                    "kind": "vendor_package",
                    "artifacts": {
                        "bin": {
                            "member": "boards/fixture/demo_apps/hello_world/hello_world.bin"
                        }
                    },
                }
                return job

            jobs = {"m70_a": vendor_job(), "m70_b": vendor_job()}
            checklist_path = self._checklist(case, compiler, jobs)
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                    m_sdk.run_m_sdk_checklist(checklist_path)
                manifest = materialize_public_manifest(
                    normalize_public_checklist(checklist_path)
                )
                first_state = load_state(manifest)["components"]
                untouched_hash = first_state["m70_b"]["outputs"][0]["sha256"]
                (case / "artifacts/m_freertos_sdk/m70_a/m70_a.bin").write_bytes(
                    b"tampered"
                )
                checklist_path = self._checklist(
                    case, compiler, jobs, scope=["m70_a"]
                )
                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                request = yaml.safe_load(
                    (checklist_path.parent / ".compile-tool-request.yaml").read_text()
                )
                self.assertEqual(
                    [unit["component"] for unit in request["compile"]["units"]],
                    ["m70_a"],
                )
                with redirect_stdout(io.StringIO()):
                    m_sdk.run_m_sdk_checklist(checklist_path)
                final_state = load_state(
                    materialize_public_manifest(normalize_public_checklist(checklist_path))
                )["components"]
                self.assertEqual(
                    final_state["m70_b"]["outputs"][0]["sha256"], untouched_hash
                )

    def test_raw_fields_bad_catalog_hash_and_non_elf_import_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            checklist_path = self._checklist(case, compiler, {"m7": self._source_job()})
            raw = yaml.safe_load(checklist_path.read_text())
            raw["jobs"]["m7"]["command"] = "make arbitrary"
            checklist_path.write_text(yaml.safe_dump(raw, sort_keys=False))
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with self.assertRaisesRegex(ToolError, "unsupported fields: command"):
                    m_sdk.normalize_m_sdk_checklist(checklist_path)

            checklist_path = self._checklist(case, compiler, {"m7": self._source_job()})
            catalog_raw = yaml.safe_load(catalog.read_text())
            catalog_raw["packages"]["SDK_FIXTURE"]["sha256"] = "sha256:" + "0" * 64
            catalog.write_text(yaml.safe_dump(catalog_raw, sort_keys=False))
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with self.assertRaisesRegex(ToolError, "package hash mismatch"):
                    m_sdk.normalize_m_sdk_checklist(checklist_path)

            catalog = self._catalog(root / "restored", archive)
            bogus_elf = case / "inputs" / "bogus.elf"
            bogus_elf.parent.mkdir(parents=True, exist_ok=True)
            bogus_elf.write_bytes(b"not-an-elf")
            job = self._source_job()
            job["mode"] = "prebuilt_import"
            job["provenance"] = {
                "kind": "user_supplied",
                "trust_reason": "negative type validation fixture",
                "artifacts": {
                    "elf": {"path": str(bogus_elf), "sha256": hash_file(bogus_elf)}
                },
            }
            checklist_path = self._checklist(case, compiler, {"bogus": job})
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                with self.assertRaisesRegex(ToolError, "invalid ELF magic"):
                    with redirect_stdout(io.StringIO()):
                        m_sdk.run_m_sdk_checklist(checklist_path)

    def test_public_m_producer_artifact_resolves_for_downstream_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = self._legacy_archive(root)
            catalog = self._catalog(root, archive)
            compiler = self._compiler(root)
            case = self._case(root)
            job = self._source_job()
            job["mode"] = "prebuilt_import"
            job["provenance"] = {
                "kind": "vendor_package",
                "artifacts": {
                    "bin": {
                        "member": "boards/fixture/demo_apps/hello_world/hello_world.bin"
                    }
                },
            }
            checklist_path = self._checklist(case, compiler, {"default_m7": job})
            with patch.object(m_sdk, "CATALOG_PATH", catalog):
                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(checklist_path)
                    m_sdk.run_m_sdk_checklist(checklist_path)
                producer = materialize_public_manifest(
                    normalize_public_checklist(checklist_path)
                )
                consumer = {
                    "case": producer["case"],
                    "case_root": producer["case_root"],
                    "target": "imx-mkimage-fixture",
                    "profile": {"hash": "sha256:consumer-fixture"},
                    "hash": "sha256:consumer-manifest-fixture",
                    "parameters": {
                        "soc": {"value": "imxfixture"},
                        "m_role": {"value": "m7"},
                    },
                    "project_profile": {
                        "artifact_inputs": {
                            "m_payload": {
                                "type": "nxp.mcore.bin",
                                "parameter_matches": {
                                    "soc": "soc",
                                    "core_role": "m_role",
                                },
                            }
                        }
                    },
                    "artifact_inputs": {
                        "m_payload": {
                            "slot": "m_payload",
                            "manifest": producer["path"],
                            "artifact": "default_m7.bin",
                        }
                    },
                }
                resolved = resolve_artifact_inputs(consumer)["m_payload"]
                self.assertEqual(resolved["type"], "nxp.mcore.bin")
                self.assertEqual(resolved["identity"]["core_role"], "m7")
                self.assertEqual(
                    resolved["producer_origin"]["assurance"], "catalog_verified"
                )
                Path(resolved["path"]).write_bytes(b"replaced")
                with self.assertRaisesRegex(ToolError, "content differs"):
                    resolve_artifact_inputs(consumer)

    def test_mkimage_prepare_resolves_public_m_producer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = ChecklistFixture(root)
            archive = self._legacy_archive(root / "m-sdk")
            catalog = self._catalog(root / "m-sdk", archive)
            compiler = self._compiler(root / "m-sdk")

            profile_path = fixture.projects / "imx-mkimage" / "COMPILE_PROFILE.yaml"
            profile = yaml.safe_load(profile_path.read_text())
            profile["artifact_inputs"]["m_payload"] = {
                "type": "nxp.mcore.bin",
                "multiple": True,
                "parameter_matches": {},
            }
            profile["file_inputs"].pop("m_payload")
            profile_path.write_text(yaml.safe_dump(profile, sort_keys=False))

            m_checklist = (
                fixture.case_root
                / "records"
                / "compile"
                / "m_freertos_sdk"
                / "compile.yaml"
            )
            m_checklist.parent.mkdir(parents=True)
            m_job = self._source_job()
            m_job["mode"] = "prebuilt_import"
            m_job["provenance"] = {
                "kind": "vendor_package",
                "artifacts": {
                    "bin": {
                        "member": "boards/fixture/demo_apps/hello_world/hello_world.bin"
                    }
                },
            }
            m_checklist.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "kind": "m_freertos_sdk_compile_checklist",
                        "target": "m_freertos_sdk",
                        "case_root": str(fixture.case_root),
                        "sdk": {
                            "package": "SDK_FIXTURE",
                            "compiler": str(compiler),
                        },
                        "jobs": {"default_m7": m_job},
                        "intent": {
                            "scope": ["default_m7"],
                            "reason": "mkimage dependency resolution fixture",
                        },
                    },
                    sort_keys=False,
                )
            )

            first_patch, second_patch = fixture.patches()
            with first_patch, second_patch, patch.object(m_sdk, "CATALOG_PATH", catalog):
                oei = fixture.oei_checklist()
                with redirect_stdout(io.StringIO()):
                    m_sdk.prepare_m_sdk_checklist(m_checklist)
                    m_sdk.run_m_sdk_checklist(m_checklist)
                    from compile_tool.checklists import prepare_checklist, run_checklist

                    prepare_checklist(oei)
                    run_checklist(oei)

                mkimage = fixture.mkimage_checklist()
                mk_data = yaml.safe_load(mkimage.read_text())
                mk_data["inputs"]["artifacts"].append(
                    {
                        "name": "m7",
                        "slot": "m_payload",
                        "checklist": str(m_checklist.relative_to(fixture.case_root)),
                        "artifact": "default_m7.bin",
                        "stage_to": "inputs/m7.bin",
                    }
                )
                mkimage.write_text(yaml.safe_dump(mk_data, sort_keys=False))
                prepared = io.StringIO()
                with redirect_stdout(prepared):
                    self.assertEqual(prepare_checklist(mkimage), 0)
                self.assertIn("stage-m7", prepared.getvalue())
                consumer_manifest = load_manifest(mkimage.parent / "manifest.yaml")
                self.assertEqual(
                    resolve_artifact_inputs(consumer_manifest)["m7"]["type"],
                    "nxp.mcore.bin",
                )


if __name__ == "__main__":
    unittest.main()
