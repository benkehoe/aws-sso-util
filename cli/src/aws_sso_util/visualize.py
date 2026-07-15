# Copyright 2026 Sai Kiran Meda
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import pkgutil

TEMPLATE_RESOURCE = "access_graph_template.html"

_DATA_PLACEHOLDER = "const DATA = /*DATA*/[];"
_DATE_PLACEHOLDER = "/*DATE*/"


def _escape_for_script_tag(serialized):
    # The JSON is inlined inside a <script> element, so a value containing
    # "</script>" (or the JS line separators JSON.stringify leaves unescaped)
    # must not be able to break out of it. Names come from the identity store
    # and account settings, which end users can influence.
    return (
        serialized
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def assignment_to_row(assignment):
    """Reduce an Assignment namedtuple to the row shape the template expects.

    The template consumes [principal_type, principal_name, permission_set_name,
    target_id, target_name]. Name fields fall back to their identifiers when
    lookups were disabled or failed.
    """
    return [
        assignment.principal_type,
        assignment.principal_name or assignment.principal_id,
        assignment.permission_set_name or assignment.permission_set_arn,
        assignment.target_id,
        assignment.target_name or assignment.target_id,
    ]


def render_access_graph(assignments, generated_at=None):
    """Render the self-contained access graph HTML for the given assignments.

    assignments is an iterable of Assignment namedtuples (or anything with the
    same attributes). Returns the HTML document as a string. The output is
    fully self-contained: no external scripts, styles, or network calls.
    """
    rows = [assignment_to_row(a) for a in assignments]
    data = _escape_for_script_tag(json.dumps(rows, separators=(",", ":")))

    template_bytes = pkgutil.get_data(__package__, TEMPLATE_RESOURCE)
    if template_bytes is None:
        raise RuntimeError("Template resource {} not found in package {}".format(
            TEMPLATE_RESOURCE, __package__))
    template = template_bytes.decode("utf-8")

    if _DATA_PLACEHOLDER not in template:
        raise RuntimeError("Data placeholder missing from template")

    if generated_at is None:
        generated_at = datetime.date.today().isoformat()

    html = template.replace(_DATA_PLACEHOLDER, "const DATA = " + data + ";")
    html = html.replace(_DATE_PLACEHOLDER, generated_at)
    return html


def write_access_graph(assignments, filename, generated_at=None):
    """Render the access graph and write it to filename. Returns the row count."""
    assignments = list(assignments)
    html = render_access_graph(assignments, generated_at=generated_at)
    with open(filename, "w", encoding="utf-8") as fp:
        fp.write(html)
    return len(assignments)
