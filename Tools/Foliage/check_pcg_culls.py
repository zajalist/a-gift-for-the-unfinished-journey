"""Fail when a PCG graph has a mesh spawner entry without cull distances (Task V5, Review Focus 4).

    python Tools/Foliage/check_pcg_culls.py PCG_Ecology_Trees [more graphs...]
    python Tools/Foliage/check_pcg_culls.py /Game/Some/Other/Graph

Every PCG mesh spawner descriptor defaults to InstanceStartCullDistance = 0 and
InstanceEndCullDistance = 0, which means "never cull": a spawner left at the default
silently renders its instances map-wide (docs/performance-budget.md, and the
pcg-spawner-cull-distance-default memory). The setting is invisible in the graph view.

The script loads each graph in the live editor (Hayba python_run over raw TCP 52342;
hold the editor gate, Tools/GameFlow/editor_gate.py), walks its nodes and every
subgraph it calls, and reads each spawner descriptor's instance cull distances:

- Static Mesh Spawner (PCGStaticMeshSpawnerSettings): every entry of a Weighted or
  Weighted-By-Category selector, or the By-Attribute selector's template descriptor.
  Start AND end must both be > 0, and start < end.
- Skinned Mesh Spawner (PCGSkinnedMeshSpawnerSettings): its selector's template descriptor. Ruling R24
  sets the near Megaplant trees to start 0, end 7000 cm, so here only the END must
  be > 0 (and start < end); the end is what stops map-wide rendering.

Exit codes: 0 all entries culled, 1 at least one bad entry, 2 nothing to check
(no spawner found, or the graph failed to load), 3 the editor call failed.
Nothing is modified or saved.
"""
import json
import os
import socket
import struct
import sys

PORT = 52342

# Sent to the editor. GRAPHS is rewritten per run. No try/getattr (python_run rules).
EDITOR_SCRIPT = r'''
import json
import unreal
GRAPHS = []

def row(kind, gname, nname, entry, mesh, d):
    return [kind, gname, nname, entry, mesh,
            float(d.get_editor_property('instance_start_cull_distance')),
            float(d.get_editor_property('instance_end_cull_distance')),
            float(d.get_editor_property('instance_min_draw_distance'))]

def mesh_name(m):
    if m is None:
        return 'None'
    return str(m.get_path_name())

def entry_rows(kind, gname, nname, sel):
    rows = []
    if isinstance(sel, unreal.PCGMeshSelectorWeighted):
        i = 0
        for e in sel.get_editor_property('mesh_entries'):
            d = e.get_editor_property('descriptor')
            rows.append(row(kind, gname, nname, 'entry' + str(i), mesh_name(d.get_editor_property(MESH_PROP[kind])), d))
            i += 1
    elif isinstance(sel, unreal.PCGMeshSelectorWeightedByCategory):
        for c in sel.get_editor_property('entries'):
            i = 0
            for e in c.get_editor_property('weighted_mesh_entries'):
                d = e.get_editor_property('descriptor')
                rows.append(row(kind, gname, nname, 'cat' + str(c.get_editor_property('category_entry')) + '.' + str(i),
                                mesh_name(d.get_editor_property(MESH_PROP[kind])), d))
                i += 1
    elif isinstance(sel, unreal.PCGMeshSelectorByAttribute):
        rows.append(row(kind, gname, nname, 'template', 'attr ' + str(sel.get_editor_property('attribute_name')),
                        sel.get_editor_property('template_descriptor')))
    elif isinstance(sel, unreal.PCGSkinnedMeshSelector):
        rows.append(row(kind, gname, nname, 'template', 'attr ' + str(sel.get_editor_property('mesh_attribute').export_text()),
                        sel.get_editor_property('template_descriptor')))
    else:
        rows.append([kind, gname, nname, 'unknown-selector ' + str(sel.get_class().get_name()), '', -1.0, -1.0, 0.0])
    return rows

MESH_PROP = {'static': 'static_mesh', 'skinned': 'skinned_asset'}
out = {'rows': [], 'graphs': [], 'missing': []}
todo = list(GRAPHS)
seen = []
while len(todo) > 0:
    path = todo.pop(0)
    if path in seen:
        continue
    seen.append(path)
    g = unreal.load_asset(path)
    if g is None:
        out['missing'].append(path)
        continue
    out['graphs'].append(path)
    for n in g.get_editor_property('nodes'):
        s = n.get_settings()
        nname = str(n.get_name())
        if isinstance(s, unreal.PCGBaseSubgraphSettings):
            sub = s.get_editor_property('subgraph_instance')
            subg = None
            if sub is not None:
                subg = sub.get_editor_property('graph')
            if subg is not None:
                todo.append(subg.get_path_name().split('.')[0])
        if isinstance(s, unreal.PCGStaticMeshSpawnerSettings):
            out['rows'] += entry_rows('static', path, nname, s.get_editor_property('mesh_selector_parameters'))
        if isinstance(s, unreal.PCGSkinnedMeshSpawnerSettings):
            out['rows'] += entry_rows('skinned', path, nname, s.get_editor_property('mesh_selector_parameters'))
print('CULLS_JSON ' + json.dumps(out))
'''


def evaluate(rows):
    """Return the bad rows. A row is [kind, graph, node, entry, mesh, start_cm, end_cm, min_draw_cm]."""
    bad = []
    for kind, graph, node, entry, mesh, start, end, _min_draw in rows:
        why = []
        if end <= 0:
            why.append('end cull 0 (never culled)')
        if kind == 'static' and start <= 0:
            why.append('start cull 0')
        if kind not in ('static', 'skinned'):
            why.append('unknown spawner kind')
        if start < 0 and end < 0:
            why.append('selector type not understood')
        elif end > 0 and start >= end:
            why.append('start >= end')
        if why:
            bad.append((kind, graph, node, entry, mesh, start, end, '; '.join(why)))
    return bad


def send(script, port=PORT, timeout=120):
    """One Hayba python_run over raw TCP (4-byte big-endian length, then JSON)."""
    env = {"cmd": "python_run", "id": "check_pcg_culls", "params": {"script": script}}
    if os.environ.get("HAYBA_AGENT_ID"):
        env["owner"] = os.environ["HAYBA_AGENT_ID"]       # the gate's lease owner (LANE4, 2026-09-28)
    payload = json.dumps(env).encode("utf-8")
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall(struct.pack(">I", len(payload)) + payload)
        head = b""
        while len(head) < 4:
            head += s.recv(4 - len(head))
        size = struct.unpack(">I", head)[0]
        body = b""
        while len(body) < size:
            body += s.recv(size - len(body))
    return json.loads(body.decode("utf-8"))


def fill(script, name, value):
    """Rewrite the one line that starts with 'NAME = '."""
    lines = script.split("\n")
    hits = [i for i, line in enumerate(lines) if line.startswith(name + " = ")]
    if len(hits) != 1:
        raise ValueError(f"expected one '{name} = ' line, found {len(hits)}")
    lines[hits[0]] = f"{name} = {value!r}"
    return "\n".join(lines)


def collect(graphs):
    """Run the editor half; return the parsed {'rows', 'graphs', 'missing'} dict or raise."""
    reply = send(fill(EDITOR_SCRIPT, "GRAPHS", list(graphs)))
    data = reply.get("data") or {}
    if not reply.get("ok"):
        raise RuntimeError(json.dumps(reply)[:2000])
    for line in (data.get("stdout") or "").splitlines():
        if line.startswith("CULLS_JSON "):
            return json.loads(line[len("CULLS_JSON "):])
    raise RuntimeError("no CULLS_JSON line in: " + (data.get("stdout") or "") + (data.get("stderr") or ""))


def main(argv):
    # A bare name means /Game/SaskartaGaea/PCG/<name>. (From Git Bash, set MSYS_NO_PATHCONV=1
    # for /Game/... paths, or MSYS rewrites them into C:/Program Files/Git/Game/...)
    graphs = [a if a.startswith("/") else "/Game/SaskartaGaea/PCG/" + a for a in argv if not a.startswith("-")]
    if not graphs:
        print(__doc__)
        return 2
    try:
        result = collect(graphs)
    except (OSError, RuntimeError) as exc:
        print(f"EDITOR CALL FAILED: {exc}")
        return 3
    for g in result["missing"]:
        print(f"MISSING graph {g}")
    for kind, graph, node, entry, mesh, start, end, min_draw in result["rows"]:
        print(f"{kind:7s} {graph.rsplit('/', 1)[-1]:20s} {node:34s} {entry:9s} min {min_draw:6.0f} start {start:7.0f} end {end:7.0f}  {mesh}")
    bad = evaluate(result["rows"])
    for b in bad:
        print(f"BAD {b[0]} {b[1]} {b[2]} {b[3]} {b[4]}: {b[7]}")
    if result["missing"] or not result["rows"]:
        print(f"NOTHING CHECKED: {len(result['rows'])} spawner entries in {result['graphs']}")
        return 2
    if bad:
        print(f"FAIL: {len(bad)} of {len(result['rows'])} spawner entries have a missing cull distance")
        return 1
    print(f"OK: {len(result['rows'])} spawner entries, all culled")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
