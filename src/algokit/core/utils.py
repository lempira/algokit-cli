import codecs
import platform
import re
import shutil
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shutil import which
from typing import Any

import click
import dotenv

from algokit.core import proc

CLEAR_LINE = "\033[K"
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def extract_version_triple(version_str: str) -> str:
    match = re.search(r"\d+\.\d+\.\d+", version_str)
    if not match:
        raise ValueError("Unable to parse version number")
    return match.group()


def is_minimum_version(system_version: str, minimum_version: str) -> bool:
    system_version_as_tuple = tuple(map(int, system_version.split(".")))
    minimum_version_as_tuple = tuple(map(int, minimum_version.split(".")))
    return system_version_as_tuple >= minimum_version_as_tuple


def is_network_available(host: str = "8.8.8.8", port: int = 53, timeout: float = 3.0) -> bool:
    """
    Check if internet is available by trying to establish a socket connection.
    """

    try:
        socket.setdefaulttimeout(timeout)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def animate(name: str, stop_event: threading.Event) -> None:
    spinner = {
        "interval": 100,
        "frames": SPINNER_FRAMES,
    }

    while not stop_event.is_set():
        for frame in spinner["frames"]:  # type: ignore  # noqa: PGH003
            if stop_event.is_set():
                break
            try:
                text = codecs.decode(frame, "utf-8")
            except Exception:
                text = frame
            output = f"\r{text} {name}"
            sys.stdout.write(output)
            sys.stdout.write(CLEAR_LINE)
            sys.stdout.flush()
            time.sleep(0.001 * spinner["interval"])  # type: ignore  # noqa: PGH003

    sys.stdout.write("\r ")


def run_with_animation(
    target_function: Callable[..., Any], animation_text: str = "Loading", *args: Any, **kwargs: Any
) -> Any:  # noqa: ANN401
    with ThreadPoolExecutor(max_workers=2) as executor:
        stop_event = threading.Event()
        animation_future = executor.submit(animate, animation_text, stop_event)
        function_future = executor.submit(target_function, *args, **kwargs)

        try:
            result = function_future.result()
        except Exception as e:
            stop_event.set()
            animation_future.result()
            raise e
        else:
            stop_event.set()
            animation_future.result()
            return result


def find_valid_pipx_command(error_message: str) -> list[str]:
    for pipx_command in get_candidate_pipx_commands():
        try:
            pipx_version_result = proc.run([*pipx_command, "--version"])
        except OSError:
            pass  # in case of path/permission issues, go to next candidate
        else:
            if pipx_version_result.exit_code == 0:
                return pipx_command
    # If pipx isn't found in global path or python -m pipx then bail out
    #   this is an exceptional circumstance since pipx should always be present with algokit
    #   since it's installed with brew / choco as a dependency, and otherwise is used to install algokit
    raise click.ClickException(error_message)


def get_candidate_pipx_commands() -> Iterator[list[str]]:
    # first try is pipx via PATH
    yield ["pipx"]
    # otherwise try getting an interpreter with pipx installed as a module,
    # this won't work if pipx is installed in its own venv but worth a shot
    for python_path in get_python_paths():
        yield [python_path, "-m", "pipx"]


def get_python_paths() -> Iterator[str]:
    for python_name in ("python3", "python"):
        if python_path := which(python_name):
            yield python_path
    python_base_path = get_base_python_path()
    if python_base_path is not None:
        yield python_base_path


def get_base_python_path() -> str | None:
    this_python: str | None = sys.executable
    if not this_python or this_python.endswith("algokit"):
        # Not: can be empty or None... yikes! unlikely though
        # https://docs.python.org/3.10/library/sys.html#sys.executable
        return None
    # not in venv... not recommended to install algokit this way, but okay
    if sys.prefix == sys.base_prefix:
        return this_python
    this_python_path = Path(this_python)
    # try resolving symlink, this should be default on *nix
    try:
        if this_python_path.is_symlink():
            return str(this_python_path.resolve())
    except (OSError, RuntimeError):
        pass
    # otherwise, try getting an internal value which should be set when running in a .venv
    # this will be the value of `home = <path>` in pyvenv.cfg if it exists
    if base_home := getattr(sys, "_home", None):
        base_home_path = Path(base_home)
        is_windows = platform.system() == "Windows"
        for name in ("python", "python3", f"python3.{sys.version_info.minor}"):
            candidate_path = base_home_path / name
            if is_windows:
                candidate_path = candidate_path.with_suffix(".exe")
            if candidate_path.is_file():
                return str(candidate_path)
    # give up, we tried...
    return this_python


def is_binary_mode() -> bool:
    """
    Check if the current Python interpreter is running in a native binary frozen environment.
    return: True if running in a native binary frozen environment, False otherwise.
    """
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def split_command_string(command: str) -> list[str]:
    """
    Parses a command string into a list of arguments, handling both shell and non-shell commands
    """

    if platform.system() == "Windows":
        import mslex

        return mslex.split(command)
    else:
        import shlex

        return shlex.split(command)


def resolve_command_path(
    command: list[str],
) -> list[str]:
    """
    Encapsulates custom command resolution, promotes reusability

    Args:
        command (list[str]): The command to resolve
        allow_chained_commands (bool): Whether to allow chained commands (e.g. "&&" or "||")

    Returns:
        list[str]: The resolved command
    """

    cmd, *args = command
    # if the command has any path separators or such, don't try and resolve
    if Path(cmd).name != cmd:
        return command
    resolved_cmd = shutil.which(cmd)
    if not resolved_cmd:
        raise click.ClickException(f"Failed to resolve command path, '{cmd}' wasn't found")
    return [resolved_cmd, *args]


def split_and_resolve_command_strings(
    commands: list[str],
) -> list[list[str]]:
    """
    Splits each command in a list of raw command strings and resolves their paths.

    This function takes a list of command strings, splits each command into its constituent
    arguments, and then resolves the path for each command. This is useful for preparing
    commands for execution in a system-agnostic manner.

    Args:
        commands: A list of raw command strings.

    Returns:
        A list of lists, where each inner list contains the resolved command path followed by its arguments.
    """

    return [resolve_command_path(split_command_string(raw_command)) for raw_command in commands]


def load_env_file(path: Path) -> dict[str, str | None]:
    """Load the general .env configuration.

    Args:
        path (Path): Path to the .env file or directory containing the .env file.

    Returns:
        dict[str, str | None]: Dictionary with .env configurations.
    """

    # Check if the path is a file, if yes, use it directly
    if path.is_file():
        env_path = path
    else:
        # Assume the default .env file name in the given directory
        env_path = path / ".env"

    if env_path.exists():
        return dotenv.dotenv_values(env_path, verbose=True)
    return {}
