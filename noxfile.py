"""Canonical local and CI quality commands."""

from collections.abc import Iterable
from pathlib import Path

import nox

nox.options.default_venv_backend = "virtualenv"
nox.options.reuse_venv = "yes"
nox.options.sessions = ("dev",)

TASKS = ("format", "lint", "typecheck", "tests", "build")


def install_project(session: nox.Session) -> None:
    """Install the complete development toolchain and project into a session."""
    session.install("-e", ".[dev]")


def resolve_tasks(posargs: list[str], session: nox.Session) -> Iterable[str]:
    """Resolve task names from session positional arguments."""
    if not posargs:
        return TASKS

    requested = tuple(dict.fromkeys(posargs))
    invalid = [name for name in requested if name not in TASKS]
    if invalid:
        valid = ", ".join(TASKS)
        invalid_names = ", ".join(invalid)
        session.error(f"Unknown task(s): {invalid_names}. Valid tasks: {valid}")
    return requested


def run_task(session: nox.Session, task: str) -> None:
    """Run one named quality/build task inside the shared Nox environment."""
    if task == "format":
        session.run("python", "-m", "ruff", "format", ".")
        return
    if task == "lint":
        session.run("python", "-m", "ruff", "check", ".")
        return
    if task == "typecheck":
        session.run("python", "-m", "mypy")
        return
    if task == "tests":
        session.run("python", "-m", "pytest")
        return
    if task == "build":
        session.run("python", "-m", "build")
        wheel = next(Path("dist").glob("*.whl"))
        session.run("python", "-m", "pip", "install", "--force-reinstall", "--no-deps", str(wheel))
        session.run("epub-to-html", "--help")
        return
    session.error(f"Unhandled task: {task}")


@nox.session(name="dev", python="3.12", reuse_venv=True)
def dev(session: nox.Session) -> None:
    """Run one or more project tasks in a single reusable Nox virtual environment.

    Examples:
    - `python -m nox` runs all tasks.
    - `python -m nox -- lint tests` runs only selected tasks.
    """
    install_project(session)
    for task in resolve_tasks(session.posargs, session):
        session.log(f"Running task: {task}")
        run_task(session, task)
