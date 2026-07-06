"""Automatic rendering of RFC 7952 ``comment`` annotations
(proteus-configuration-metadata.yang) without any comment hooks in the
Jinja templates.

FRR only has whole-line comments -- a line whose first non-whitespace
character is '!' or '#' (frr/lib/command.c cmd_make_strvec,
frr/vtysh/vtysh.c vtysh_read_file); there are NO inline comments -- so
every comment renders as full '!' line(s) immediately before the
annotated element's first config line, indentation-matched.

Mechanism: `render_with_comments(template, **context)` wraps every
dataclass node of the bindings tree in a tracking proxy before handing
it to the template, then consumes the template as a stream
(``template.generate``) instead of ``render()``. Whenever a proxy is
created for a node (a container/list entry entering the render) or a
leaf member is read, any ``comment`` annotation in the node's
``_yang_metadata`` store (see the generated bindings' ``annotate()``)
is queued -- once per (node, member) per render -- and flushed as
``! ...`` lines above the next completed output line. Jinja evaluates
guards and interpolations in document order, interleaved with output,
so the queue drains right where the annotated element renders.

Comment splitting matches helpers.comment_lines: one '!' line per
non-empty line of the comment value; whitespace-only comments render
nothing. (Kept inline here rather than imported -- helpers.py imports
`unwrap` from this module, so this module must not import helpers.)

Node comments are recorded at WRAP time, i.e. the moment a template
fetches the node (`{% set af = instance.afi_safis[...] %}`, a `{% for
%}` over a YANG list, ...), not at first field access: that places a
container's comment above its block header line even when the header
text itself reads nothing from the node (e.g. the literal
`address-family ipv4 unicast` lines).

Known precision limits (scope is always right, the exact line within a
group may not be):

- Jinja macros buffer their entire output as one string
  (session_lines / af_lines / the filters and evpn macros), so every
  comment recorded during one macro call attaches to that call's first
  output line.
- Subtree scans that walk proxies (`selectattr(...)`) record node
  comments they pass over; once-per-render de-duplication plus
  document order absorbs this for the shapes the templates use
  (peer-groups/neighbors render before the per-AF scans).
- A comment on a node whose output line is suppressed by an unrelated
  condition attaches to the next rendered line.

Scanning helpers that sweep whole subtrees (has_config and friends in
helpers.py) must `unwrap()` their argument and walk the raw objects --
both so `dataclasses.fields()` works and so the sweep doesn't queue
false comments. Value helpers (asn_text, rd_text, ...) deliberately
keep receiving proxies: their accesses happen while the target line is
being built, which is exactly where a leaf comment belongs.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import jinja2


def _is_node(value: object) -> bool:
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


class Recorder:
    """Per-render queue of pending comment lines.

    Keys mirror the bindings' ``_yang_metadata`` addressing: ``None``
    for the node's own annotation, ``"field"`` for a leaf member,
    ``("field", i)`` for a leaf-list entry. Each (node, key) fires at
    most once per render.
    """

    def __init__(self) -> None:
        self.pending: list[str] = []
        self._emitted: set[tuple[int, object]] = set()

    def record(self, obj: object, key: object) -> None:
        token = (id(obj), key)
        if token in self._emitted:
            return
        store = getattr(obj, "_yang_metadata", None) or {}
        comment = (store.get(key) or {}).get("comment")
        if comment is None or not str(comment).strip():
            return
        self._emitted.add(token)
        self.pending.extend(
            line.rstrip()
            for line in str(comment).splitlines()
            if line.strip()
        )

    def take(self) -> list[str]:
        taken, self.pending = self.pending, []
        return taken


class NodeProxy:
    """Wraps one generated dataclass node; attribute access records
    leaf-member comments and returns wrapped children. Scalars pass
    through raw, so string/number operations in templates and value
    helpers are unaffected."""

    __slots__ = ("_obj", "_rec")

    def __init__(self, obj: object, rec: Recorder) -> None:
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_rec", rec)

    def __getattr__(self, name: str) -> Any:
        obj, rec = self._obj, self._rec
        value = getattr(obj, name)  # AttributeError -> Jinja Undefined
        rec.record(obj, name)  # leaf-member comment (no-op otherwise)
        return wrap(value, rec, owner=obj, field=name)

    def __getitem__(self, name: str) -> Any:
        # Templates address dynamic fields as `node[field_var]`.
        return self.__getattr__(name)

    def __contains__(self, name: str) -> bool:
        return hasattr(self._obj, name)

    def __bool__(self) -> bool:
        return bool(self._obj)

    def __eq__(self, other: object) -> bool:
        return self._obj == unwrap(other)

    def __repr__(self) -> str:
        return repr(self._obj)


class ListProxy:
    """Wraps a YANG list (entries are nodes) or leaf-list (entries are
    scalars); iteration/indexing wraps entries and, for leaf-lists,
    records per-entry comments (RFC 7952 addresses leaf-list
    annotations per entry, never whole-list)."""

    __slots__ = ("_obj", "_rec", "_owner", "_field")

    def __init__(
        self, obj: list, rec: Recorder, owner: object, field: str | None
    ) -> None:
        self._obj = obj
        self._rec = rec
        self._owner = owner
        self._field = field

    def _entry(self, index: int) -> Any:
        item = self._obj[index]
        if self._owner is not None and not _is_node(item):
            self._rec.record(self._owner, (self._field, index))
        return wrap(item, self._rec)

    def __iter__(self):
        return (self._entry(i) for i in range(len(self._obj)))

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self._entry(i) for i in range(*index.indices(len(self._obj)))]
        return self._entry(index)

    def __len__(self) -> int:
        return len(self._obj)

    def __bool__(self) -> bool:
        return bool(self._obj)

    def __add__(self, other) -> list:
        return list(self) + list(other)

    def __radd__(self, other) -> list:
        return list(other) + list(self)

    def __eq__(self, other: object) -> bool:
        return self._obj == unwrap(other)

    def __repr__(self) -> str:
        return repr(self._obj)


def wrap(
    value: Any,
    rec: Recorder,
    *,
    owner: object | None = None,
    field: str | None = None,
) -> Any:
    """Wrap a bindings value for tracked rendering; scalars pass
    through. Wrapping a node records its own comment (wrap-time node
    recording, see the module docstring)."""
    if _is_node(value):
        rec.record(value, None)
        return NodeProxy(value, rec)
    if isinstance(value, list):
        return ListProxy(value, rec, owner, field)
    return value


def unwrap(value: Any) -> Any:
    """The raw bindings object behind a proxy; non-proxies pass
    through. Subtree-scanning helpers must call this first."""
    if isinstance(value, (NodeProxy, ListProxy)):
        return value._obj
    return value


def render_with_comments(template: jinja2.Template, **context: Any) -> str:
    """Render `template` like ``template.render(**context)`` but with
    every dataclass in `context` wrapped for comment tracking, flushing
    queued comments as indentation-matched ``! ...`` lines above the
    output line being produced when they fired."""
    rec = Recorder()
    wrapped = {key: wrap(value, rec) for key, value in context.items()}
    out: list[str] = []
    line = ""
    for chunk in template.generate(**wrapped):
        for piece in chunk.splitlines(keepends=True):
            line += piece
            if line.endswith("\n"):
                indent = line[: len(line) - len(line.lstrip())].rstrip("\n")
                out.extend(f"{indent}! {c}\n" for c in rec.take())
                out.append(line)
                line = ""
    if line:
        indent = line[: len(line) - len(line.lstrip())]
        out.extend(f"{indent}! {c}\n" for c in rec.take())
        out.append(line)
    out.extend(f"! {c}\n" for c in rec.take())
    return "".join(out)
