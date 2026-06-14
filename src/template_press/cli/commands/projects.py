# Copyright (c) 2025, Steve Morin
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""``press projects`` — list and inspect Py projects.

Reference noun: shows the full best-practice shape (global flags, structured
result → renderer, early validation, typed errors → exit codes).
"""

import click

from template_press.cli.context import AppContext
from template_press.cli.groups import SuggestingGroup
from template_press.cli.options import global_options
from template_press.core.errors import AuthError
from template_press.core.models import ProjectList
from template_press.core.services import ProjectsService


@click.group(name="projects", cls=SuggestingGroup)
def projects_group() -> None:
    """List and inspect Py projects."""


def _service(app: AppContext) -> ProjectsService:
    """Build a projects service or fail with a clear auth error."""
    token = app.config.token
    if not token:
        raise AuthError(
            "No Py token found (never stored in the config file).",
            hint="supply it via --token or $PRESS_TOKEN; `press doctor` checks setup",
        )
    return ProjectsService(token)


@projects_group.command(name="list")
@click.option("--workspace", help="Filter projects by workspace name.")
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=200,
    show_default=True,
    help="Maximum number of projects to retrieve.",
)
@global_options
def list_projects(app: AppContext, workspace: str | None, limit: int) -> None:
    """List projects, optionally filtered by workspace.

    Examples:
        press projects list
        press projects list --workspace "My Workspace" --json
        press projects list -o markdown
    """
    projects = _service(app).list_projects(workspace=workspace, limit=limit)
    app.renderer.render(ProjectList(projects=projects))


@projects_group.command(name="get")
@click.argument("project_id")
@global_options
def get_project(app: AppContext, project_id: str) -> None:
    """Fetch a single project by its ID.

    Examples:
        press projects get 12345
        press projects get 12345 --json
    """
    project = _service(app).get_project(project_id)
    app.renderer.render(ProjectList(projects=[project]))
