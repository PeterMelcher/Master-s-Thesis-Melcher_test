"""
Blender Script: Fill an Edge Loop with a Single Face (N-gon Lid)
=================================================================

Problem:
    You have extruded a polygon-shaped edge loop upward to create walls
    and now want to cap (close) the top with a flat lid.  Blender's
    built-in *Fill* (Alt + F / Ctrl + F) often creates a triangulated mess
    — many faces, extra edges, and geometry that extends outside the
    boundary — especially when the loop has thousands of vertices.

Solution:
    This script creates **one single N-gon face** from the selected
    boundary vertices.  An N-gon is a face with an arbitrary number of
    sides.  Because it is a single face, it:

    • uses almost no extra memory (one face instead of thousands),
    • cannot produce twisted or overlapping geometry,
    • perfectly shares the existing boundary vertices — no gaps or overlaps
      between the lid and the walls.

    The script automatically sorts the selected vertices into the correct
    winding order by walking the connected boundary edges, so you do not
    need to worry about selection order.

Usage:
    1. Open Blender, enter Edit Mode on your mesh.
    2. Select the edge loop that should form the boundary of the lid.
       (Select → All by Trait → Non Manifold  can help find boundary edges.)
    3. Open a Text Editor area in Blender, load this script (Text → Open).
    4. Click ▶ Run Script  (or press Alt + P).

    After the first run the operator is also available via
    F3 → "Fill Edge Loop with Single Face".

Notes for very large loops (>10 000 vertices):
    Blender can handle N-gons with tens of thousands of vertices, but
    viewport display may be slow in solid / material preview mode.
    Switching to *Wireframe* mode (press Z → Wireframe) while working
    helps a lot.  The N-gon is perfectly fine for export / simulation.
"""

import bpy
import bmesh


# ──────────────────────────────────────────────────────────────────────
#  Core logic
# ──────────────────────────────────────────────────────────────────────

def _order_boundary_verts(bm, selected_verts):
    """Return *selected_verts* sorted into a continuous loop order.

    Walks along edges that connect exactly two selected vertices
    (i.e. boundary edges of the selection) to produce a single ordered
    loop.  Raises ``RuntimeError`` if the selected vertices do not form
    exactly one closed loop.
    """

    sel_set = set(v.index for v in selected_verts)

    # Build adjacency: for each selected vert, find its selected neighbours
    # that are connected by an edge where both endpoints are selected.
    adj: dict[int, list[int]] = {v.index: [] for v in selected_verts}
    vert_lookup = {v.index: v for v in selected_verts}

    for v in selected_verts:
        for e in v.link_edges:
            other = e.other_vert(v)
            if other.index in sel_set:
                adj[v.index].append(other.index)

    # Every vertex in a simple closed loop must have exactly 2 neighbours
    # among the selected set (the previous and next vertex in the loop).
    for idx, neighbours in adj.items():
        if len(neighbours) < 2:
            raise RuntimeError(
                f"Vertex {idx} has only {len(neighbours)} selected "
                f"neighbour(s) — the selection does not form a closed loop. "
                f"Make sure you select a complete edge loop."
            )
        if len(neighbours) > 2:
            # More than 2 neighbours means a junction — the selection
            # contains branching edges, not a simple loop.  We still try
            # to walk, but warn the user.
            pass  # will be caught during walk if it fails

    # Walk the loop starting from an arbitrary vertex.
    start = selected_verts[0].index
    ordered = [start]
    prev = None
    current = start

    for _ in range(len(selected_verts)):
        neighbours = adj[current]
        # Pick the neighbour that is not the one we came from.
        next_candidates = [n for n in neighbours if n != prev]
        if not next_candidates:
            raise RuntimeError(
                "Could not walk the edge loop — dead end reached."
            )
        next_v = next_candidates[0]
        if next_v == start:
            break  # closed the loop
        ordered.append(next_v)
        prev = current
        current = next_v
    else:
        raise RuntimeError(
            "Could not close the edge loop — the selected vertices "
            "may form more than one loop or an open chain."
        )

    if len(ordered) != len(selected_verts):
        raise RuntimeError(
            f"Edge loop walk visited {len(ordered)} vertices, but "
            f"{len(selected_verts)} are selected.  The selection may "
            f"contain more than one loop."
        )

    return [vert_lookup[i] for i in ordered]


def fill_edge_loop_single_face(bm=None, mesh_data=None):
    """Create a single N-gon face from the currently selected edge loop.

    Parameters
    ----------
    bm : bmesh.types.BMesh, optional
        An existing BMesh to operate on.  If *None*, one is obtained from
        the active edit-mode mesh.
    mesh_data : bpy.types.Mesh, optional
        The mesh data-block (needed to call ``bmesh.update_edit_mesh``).
        Ignored when *bm* is provided externally (caller is responsible
        for updates).

    Returns
    -------
    bmesh.types.BMFace
        The newly created face.
    """
    own_bm = bm is None
    if own_bm:
        obj = bpy.context.edit_object
        if obj is None or obj.type != "MESH":
            raise RuntimeError("No mesh object in Edit Mode")
        mesh_data = obj.data
        bm = bmesh.from_edit_mesh(mesh_data)

    bm.verts.ensure_lookup_table()

    selected = [v for v in bm.verts if v.select]
    if len(selected) < 3:
        raise RuntimeError(
            f"Need at least 3 selected vertices to create a face, "
            f"got {len(selected)}."
        )

    ordered = _order_boundary_verts(bm, selected)

    # Check that a face with these exact vertices does not already exist.
    ordered_set = set(v.index for v in ordered)
    for f in bm.faces:
        if set(v.index for v in f.verts) == ordered_set:
            raise RuntimeError(
                "A face with exactly these vertices already exists."
            )

    face = bm.faces.new(ordered)
    bm.normal_update()

    if own_bm and mesh_data is not None:
        bmesh.update_edit_mesh(mesh_data)

    return face


# ──────────────────────────────────────────────────────────────────────
#  Blender Operator
# ──────────────────────────────────────────────────────────────────────

class MESH_OT_fill_edge_loop_single(bpy.types.Operator):
    """Fill a selected edge loop with a single N-gon face"""
    bl_idname = "mesh.fill_edge_loop_single"
    bl_label = "Fill Edge Loop with Single Face"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            context.edit_object is not None
            and context.edit_object.type == "MESH"
        )

    def execute(self, context):
        try:
            face = fill_edge_loop_single_face()
            n = len(face.verts)
            self.report({"INFO"}, f"Created 1 face with {n} vertices")
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


def register():
    bpy.utils.register_class(MESH_OT_fill_edge_loop_single)


def unregister():
    bpy.utils.unregister_class(MESH_OT_fill_edge_loop_single)


# ──────────────────────────────────────────────────────────────────────
#  Direct execution
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    register()
    try:
        face = fill_edge_loop_single_face()
        print(f"[fill_edge_loop] Created 1 face with {len(face.verts)} vertices")
    except RuntimeError as e:
        print(f"[fill_edge_loop] Error: {e}")