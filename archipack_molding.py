# -*- coding:utf-8 -*-

# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110- 1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

# ----------------------------------------------------------
# Author: Stephen Leger (s-leger)
#
# ----------------------------------------------------------
# noinspection PyUnresolvedReferences
import bpy
# noinspection PyUnresolvedReferences
from bpy.types import Operator, PropertyGroup, Mesh, Panel
from bpy.props import (
    FloatProperty, BoolProperty, IntProperty, CollectionProperty,
    StringProperty, EnumProperty
    )
from .bmesh_utils import BmeshEdit as bmed
from .panel import Panel as Lofter
from mathutils import Vector, Matrix
from mathutils.geometry import interpolate_bezier
from math import sin, cos, pi, acos, atan2
from .archipack_manipulator import Manipulable, archipack_manipulator
from .archipack_2d import Line, Arc
from .archipack_preset import ArchipackPreset, PresetMenuOperator
from .archipack_object import ArchipackCreateTool, ArchipackObject


class Molding():

    def __init__(self):
        # total distance from start
        self.dist = 0
        self.t_start = 0
        self.t_end = 0
        self.dz = 0
        self.z0 = 0

    def set_offset(self, offset, last=None):
        """
            Offset line and compute intersection point
            between segments
        """
        self.line = self.make_offset(offset, last)

    @property
    def t_diff(self):
        return self.t_end - self.t_start

    def straight_molding(self, a0, length):
        s = self.straight(length).rotate(a0)
        return StraightMolding(s.p, s.v)


class StraightMolding(Molding, Line):
    def __str__(self):
        return "t_start:{} t_end:{} dist:{}".format(self.t_start, self.t_end, self.dist)

    def __init__(self, p, v):
        Molding.__init__(self)
        Line.__init__(self, p, v)



class MoldingSegment():
    def __str__(self):
        return "t_start:{} t_end:{} n_step:{}  t_step:{} i_start:{} i_end:{}".format(
            self.t_start, self.t_end, self.n_step, self.t_step, self.i_start, self.i_end)

    def __init__(self, t_start, t_end, n_step, t_step, i_start, i_end):
        self.t_start = t_start
        self.t_end = t_end
        self.n_step = n_step
        self.t_step = t_step
        self.i_start = i_start
        self.i_end = i_end


class MoldingGenerator():

    def __init__(self, parts):
        self.parts = parts
        self.segs = []
        self.length = 0
        self.user_defined_post = None
        self.user_defined_uvs = None
        self.user_defined_mat = None

    def add_part(self, part):

        if len(self.segs) < 1:
            s = None
        else:
            s = self.segs[-1]

        # start a new molding
        if s is None:
            p = Vector((0, 0))
            v = part.length * Vector((cos(part.a0), sin(part.a0)))
            s = StraightMolding(p, v)
        else:
            s = s.straight_molding(part.a0, part.length)

        # s.dist = self.length
        # self.length += s.length
        self.segs.append(s)
        self.last_type = type

    def set_offset(self, offset):
        # @TODO:
        # re-evaluate length of offset line here
        last = None
        for seg in self.segs:
            seg.set_offset(offset, last)
            last = seg.line

    def make_profile(self, profile, idmat,
            x_offset, z_offset, extend, closed, verts, faces, matids, uvs):

        last = None
        for seg in self.segs:
            seg.line = seg.make_offset(x_offset, last)
            last = seg.line

        n_moldings = len(self.segs) - 1

        if n_moldings < 0:
            return

        sections = []

        f = self.segs[0]
        f_last = self.segs[-1].line
        closed_path = (f.line.p - (f_last.p + f_last.v)).length < 0.0001
        
        # add first section
        if closed_path:            
            n = f_last.sized_normal(1, 1)
        else:
            n = f.line.sized_normal(0, 1)
        
        # n.p = f.lerp(x_offset)
        sections.append((n, f.dz / f.line.length, f.z0))

        for s, f in enumerate(self.segs):
            if f.line.length == 0:
                continue
            n = f.line.sized_normal(1, 1)
            # n.p = f.lerp(x_offset)
            sections.append((n, f.dz / f.line.length, f.z0 + f.dz))

        user_path_verts = len(sections)
        offset = len(verts)
        if user_path_verts > 0:
            user_path_uv_v = []
            n, dz, z0 = sections[-1]
            sections[-1] = (n, dz, z0)
            n_sections = user_path_verts - 1
            n, dz, zl = sections[0]
            p0 = n.p
            v0 = n.v.normalized()
            for s, section in enumerate(sections):
                n, dz, zl = section
                p1 = n.p
                if s > 0:
                    user_path_uv_v.append((p1 - p0).length)
                if s < n_sections:
                    v1 = sections[s + 1][0].v.normalized()
                elif closed_path:
                    break
                dir = (v0 + v1).normalized()
                scale = min(10, 1 / cos(0.5 * acos(min(1, max(-1, v0 * v1)))))
                for p in profile:
                    # x, y = n.p + scale * (x_offset + p.x) * dir
                    x, y = n.p + scale * p.x * dir
                    z = zl + p.y + z_offset
                    verts.append((x, y, z))
                p0 = p1
                v0 = v1
            if closed_path:
                user_path_verts -= 1
            # build faces using Panel
            lofter = Lofter(
                # closed_shape, index, x, y, idmat
                closed,
                [i for i in range(len(profile))],
                [p.x for p in profile],
                [p.y for p in profile],
                [idmat for i in range(len(profile))],
                closed_path=closed_path,
                user_path_uv_v=user_path_uv_v,
                user_path_verts=user_path_verts
                )
            faces += lofter.faces(1, offset=offset, path_type='USER_DEFINED')
            matids += lofter.mat(1, idmat, idmat, path_type='USER_DEFINED')
            v = Vector((0, 0))
            uvs += lofter.uv(1, v, v, v, v, 0, v, 0, 0, path_type='USER_DEFINED')
            
    def update_manipulators(self):
        """
           
        """
        for i, f in enumerate(self.segs):
            
            manipulators = self.parts[i].manipulators
            p0 = f.line.p0.to_3d()
            p1 = f.line.p1.to_3d()
            # angle from last to current segment
            if i > 0:
                v0 = self.segs[i - 1].line.straight(-1, 1).v.to_3d()
                v1 = f.line.straight(1, 0).v.to_3d()
                manipulators[0].set_pts([p0, v0, v1])

            # segment length
            manipulators[1].type_key = 'SIZE'
            manipulators[1].prop1_name = "length"
            manipulators[1].set_pts([p0, p1, (1, 0, 0)])

            # snap manipulator, dont change index !
            manipulators[2].set_pts([p0, p1, (1, 0, 0)])

           

def update(self, context):
    self.update(context)


def update_manipulators(self, context):
    self.update(context, manipulable_refresh=True)


def update_path(self, context):
    self.update_path(context)


class archipack_molding_part(PropertyGroup):
    type = EnumProperty(
            items=(
                ('S_SEG', 'Straight', '', 0),
                ),
            default='S_SEG'
            )
    length = FloatProperty(
            name="Length",
            min=0.01,
            default=2.0,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    a0 = FloatProperty(
            name="Start angle",
            min=-2 * pi,
            max=2 * pi,
            default=0,
            subtype='ANGLE', unit='ROTATION',
            update=update
            )
    dz = FloatProperty(
            name="delta z",
            default=0,
            unit='LENGTH', subtype='DISTANCE'
            )

    manipulators = CollectionProperty(type=archipack_manipulator)

    def find_datablock_in_selection(self, context):
        """
            find witch selected object this instance belongs to
            provide support for "copy to selected"
        """
        selected = [o for o in context.selected_objects]
        for o in selected:
            props = archipack_molding.datablock(o)
            if props is not None:
                for part in props.parts:
                    if part == self:
                        return props
        return None

    def update(self, context, manipulable_refresh=False):
        props = self.find_datablock_in_selection(context)
        if props is not None:
            props.update(context, manipulable_refresh)

    def draw(self, layout, context, index):
        box = layout.box()
        row = box.row()
        row = box.row()
        row.prop(self, "length")
        row = box.row()
        row.prop(self, "a0")


class archipack_molding(ArchipackObject, Manipulable, PropertyGroup):

    parts = CollectionProperty(type=archipack_molding_part)
    user_defined_path = StringProperty(
            name="User defined",
            update=update_path
            )
    user_path_reverse = BoolProperty(
            name="Reverse",
            default=False,
            update=update_path
            )
    user_defined_spline = IntProperty(
            name="Spline index",
            min=0,
            default=0,
            update=update_path
            )
    user_defined_resolution = IntProperty(
            name="Resolution",
            min=1,
            max=128,
            default=12, update=update_path
            )
    n_parts = IntProperty(
            name="Parts",
            min=1,
            default=1, update=update_manipulators
            )
    x_offset = FloatProperty(
            name="Offset",
            default=0.0, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    profil = EnumProperty(
            name="Profil",
            items=(
                ('SQUARE', 'Square', '', 0),
                ('CIRCLE', 'Circle', '', 1),
                ('COMPLEX', 'Circle over square', '', 2)
                ),
            default='SQUARE',
            update=update
            )
    profil_x = FloatProperty(
            name="Width",
            min=0.001,
            default=0.02, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    profil_y = FloatProperty(
            name="Height",
            min=0.001,
            default=0.1, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    profil_radius = FloatProperty(
            name="Radius",
            min=0.001,
            default=0.02, precision=2, step=1,
            unit='LENGTH', subtype='DISTANCE',
            update=update
            )
    closed = BoolProperty(
        default=True, 
        options={'SKIP_SAVE'}
        )
    # UI layout related
    parts_expand = BoolProperty(
            default=False
            )
    
    # Flag to prevent mesh update while making bulk changes over variables
    # use :
    # .auto_update = False
    # bulk changes
    # .auto_update = True
    auto_update = BoolProperty(
            options={'SKIP_SAVE'},
            default=True,
            update=update_manipulators
            )

    def setup_manipulators(self):

        if len(self.manipulators) == 0:
            s = self.manipulators.add()
            s.prop1_name = "width"
            s = self.manipulators.add()
            s.prop1_name = "height"
            s.normal = Vector((0, 1, 0))

        for i in range(self.n_parts):
            p = self.parts[i]
            n_manips = len(p.manipulators)
            if n_manips == 0:
                s = p.manipulators.add()
                s.type_key = "ANGLE"
                s.prop1_name = "a0"
                s = p.manipulators.add()
                s.type_key = "SIZE"
                s.prop1_name = "length"
                s = p.manipulators.add()
                # s.type_key = 'SNAP_POINT'
                s.type_key = 'WALL_SNAP'
                s.prop1_name = str(i)
                s.prop2_name = 'profil_y'

    def update_parts(self):

        # remove parts
        for i in range(len(self.parts), self.n_parts, -1):
            self.parts.remove(i - 1)

        # add parts
        for i in range(len(self.parts), self.n_parts):
            self.parts.add()

        self.setup_manipulators()

    def interpolate_bezier(self, pts, wM, p0, p1, resolution):
        # straight segment, worth testing here
        # since this can lower points count by a resolution factor
        # use normalized to handle non linear t
        if resolution == 0:
            pts.append(wM * p0.co.to_3d())
        else:
            v = (p1.co - p0.co).normalized()
            d1 = (p0.handle_right - p0.co).normalized()
            d2 = (p1.co - p1.handle_left).normalized()
            if d1 == v and d2 == v:
                pts.append(wM * p0.co.to_3d())
            else:
                seg = interpolate_bezier(wM * p0.co,
                    wM * p0.handle_right,
                    wM * p1.handle_left,
                    wM * p1.co,
                    resolution + 1)
                for i in range(resolution):
                    pts.append(seg[i].to_3d())

    def from_spline(self, context, wM, resolution, spline):

        o = self.find_in_selection(context)

        if o is None:
            return

        pts = []
        if spline.type == 'POLY':
            pts = [wM * p.co.to_3d() for p in spline.points]
            if spline.use_cyclic_u:
                pts.append(pts[0])
        elif spline.type == 'BEZIER':
            points = spline.bezier_points
            for i in range(1, len(points)):
                p0 = points[i - 1]
                p1 = points[i]
                self.interpolate_bezier(pts, wM, p0, p1, resolution)
            if spline.use_cyclic_u:
                p0 = points[-1]
                p1 = points[0]
                self.interpolate_bezier(pts, wM, p0, p1, resolution)
                pts.append(pts[0])
            else:
                pts.append(wM * points[-1].co)

        auto_update = self.auto_update
        self.auto_update = False

        self.n_parts = len(pts) - 1
        self.update_parts()

        if len(pts) < 1:
            return

        if self.user_path_reverse:
            pts = list(reversed(pts))

        o.matrix_world = Matrix.Translation(pts[0].copy())

        p0 = pts.pop(0)
        a0 = 0
        for i, p1 in enumerate(pts):
            dp = p1 - p0
            da = atan2(dp.y, dp.x) - a0
            if da > pi:
                da -= 2 * pi
            if da < -pi:
                da += 2 * pi
            p = self.parts[i]
            p.length = dp.to_2d().length
            p.dz = dp.z
            p.a0 = da
            a0 += da
            p0 = p1

        self.auto_update = auto_update

    def update_path(self, context):
        path = context.scene.objects.get(self.user_defined_path)
        if path is not None and path.type == 'CURVE':
            splines = path.data.splines
            if len(splines) > self.user_defined_spline:
                self.from_spline(
                    context,
                    path.matrix_world,
                    self.user_defined_resolution,
                    splines[self.user_defined_spline])

    def get_generator(self):
        g = MoldingGenerator(self.parts)
        for part in self.parts:
            # type, radius, da, length
            g.add_part(part)

        g.set_offset(self.x_offset)
        g.update_manipulators()
        return g

    def update(self, context, manipulable_refresh=False):

        o = self.find_in_selection(context, self.auto_update)

        if o is None:
            return

        # clean up manipulators before any data model change
        if manipulable_refresh:
            self.manipulable_disable(context)

        self.update_parts()

        verts = []
        faces = []
        matids = []
        uvs = []

        g = self.get_generator()

        # reset user def posts

        if self.profil == 'COMPLEX':
            sx = self.profil_x
            sy = self.profil_y
            molding = [Vector((sx * x, sy * y)) for x, y in [
            (-0.28, 1.83), (-0.355, 1.77), (-0.415, 1.695), (-0.46, 1.605), (-0.49, 1.51), (-0.5, 1.415),
            (-0.49, 1.315), (-0.46, 1.225), (-0.415, 1.135), (-0.355, 1.06), (-0.28, 1.0), (-0.255, 0.925),
            (-0.33, 0.855), (-0.5, 0.855), (-0.5, 0.0), (0.5, 0.0), (0.5, 0.855), (0.33, 0.855), (0.255, 0.925),
            (0.28, 1.0), (0.355, 1.06), (0.415, 1.135), (0.46, 1.225), (0.49, 1.315), (0.5, 1.415),
            (0.49, 1.51), (0.46, 1.605), (0.415, 1.695), (0.355, 1.77), (0.28, 1.83), (0.19, 1.875),
            (0.1, 1.905), (0.0, 1.915), (-0.095, 1.905), (-0.19, 1.875)]]

        elif self.profil == 'SQUARE':
            x = self.profil_x
            y = self.profil_y
            molding = [Vector((0, y)), Vector((0, 0)), Vector((x, 0)), Vector((x, y))]

        elif self.profil == 'CIRCLE':
            x = self.profil_x
            y = self.profil_y
            r = min(self.profil_radius, x, y)
            segs = 6
            da = pi / (2 * segs)
            molding = [Vector((0, y)), Vector((0, 0)), Vector((x, 0))]
            molding.extend([Vector((x + r * (cos(a * da) - 1), y + r * (sin(a * da) - 1))) for a in range(segs + 1)])
            
        g.make_profile(molding, 0, self.x_offset,
            0, 0, True, verts, faces, matids, uvs)

        bmed.buildmesh(context, o, verts, faces, matids=matids, uvs=uvs, weld=True, clean=True)

        # enable manipulators rebuild
        if manipulable_refresh:
            self.manipulable_refresh = True

        # restore context
        self.restore_context(context)

    def manipulable_setup(self, context):
        """
            NOTE:
            this one assume context.active_object is the instance this
            data belongs to, failing to do so will result in wrong
            manipulators set on active object
        """
        self.manipulable_disable(context)

        o = context.active_object

        self.setup_manipulators()

        for i, part in enumerate(self.parts):
            if i >= self.n_parts:
                break

            if i > 0:
                # start angle
                self.manip_stack.append(part.manipulators[0].setup(context, o, part))

            # length / radius + angle
            self.manip_stack.append(part.manipulators[1].setup(context, o, part))

            # snap point
            self.manip_stack.append(part.manipulators[2].setup(context, o, self))

        for m in self.manipulators:
            self.manip_stack.append(m.setup(context, o, self))


class ARCHIPACK_PT_molding(Panel):
    bl_idname = "ARCHIPACK_PT_molding"
    bl_label = "Molding"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ArchiPack'

    @classmethod
    def poll(cls, context):
        return archipack_molding.filter(context.active_object)

    def draw(self, context):
        prop = archipack_molding.datablock(context.active_object)
        if prop is None:
            return
        scene = context.scene
        layout = self.layout
        row = layout.row(align=True)
        row.operator('archipack.manipulate', icon='HAND')
        box = layout.box()
        # box.label(text="Styles")
        row = box.row(align=True)
        row.operator("archipack.molding_preset_menu", text=bpy.types.ARCHIPACK_OT_molding_preset_menu.bl_label)
        row.operator("archipack.molding_preset", text="", icon='ZOOMIN')
        row.operator("archipack.molding_preset", text="", icon='ZOOMOUT').remove_active = True
        box = layout.box()
        row = box.row(align=True)
        row.operator("archipack.molding_curve_update", text="", icon='FILE_REFRESH')
        row.prop_search(prop, "user_defined_path", scene, "objects", text="", icon='OUTLINER_OB_CURVE')

        if prop.user_defined_path is not "":
            box.prop(prop, 'user_defined_spline')
            box.prop(prop, 'user_defined_resolution')
            box.prop(prop, 'user_path_reverse')

        box.prop(prop, 'x_offset')
        box = layout.box()
        row = box.row()
        if prop.parts_expand:
            row.prop(prop, 'parts_expand', icon="TRIA_DOWN", icon_only=True, text="Parts", emboss=False)
            box.prop(prop, 'n_parts')
            for i, part in enumerate(prop.parts):
                part.draw(layout, context, i)
        else:
            row.prop(prop, 'parts_expand', icon="TRIA_RIGHT", icon_only=True, text="Parts", emboss=False)

        box = layout.box()
        row = box.row(align=True)
        box.prop(prop, 'profil')
        box.prop(prop, 'profil_x')
        box.prop(prop, 'profil_y')
        if prop.profil == 'CIRCLE':
            box.prop(prop, 'profil_radius')


# ------------------------------------------------------------------
# Define operator class to create object
# ------------------------------------------------------------------


class ARCHIPACK_OT_molding(ArchipackCreateTool, Operator):
    bl_idname = "archipack.molding"
    bl_label = "Molding"
    bl_description = "Molding"
    bl_category = 'Archipack'
    bl_options = {'REGISTER', 'UNDO'}

    def create(self, context):
        m = bpy.data.meshes.new("Molding")
        o = bpy.data.objects.new("Molding", m)
        d = m.archipack_molding.add()
        # make manipulators selectable
        d.manipulable_selectable = True
        context.scene.objects.link(o)
        o.select = True
        context.scene.objects.active = o
        self.load_preset(d)
        self.add_material(o)
        return o

    def execute(self, context):
        if context.mode == "OBJECT":
            bpy.ops.object.select_all(action="DESELECT")
            o = self.create(context)
            o.location = bpy.context.scene.cursor_location
            o.select = True
            context.scene.objects.active = o
            self.manipulate()
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Archipack: Option only valid in Object mode")
            return {'CANCELLED'}


# ------------------------------------------------------------------
# Define operator class to create object
# ------------------------------------------------------------------


class ARCHIPACK_OT_molding_curve_update(Operator):
    bl_idname = "archipack.molding_curve_update"
    bl_label = "Molding curve update"
    bl_description = "Update molding data from curve"
    bl_category = 'Archipack'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return archipack_molding.filter(context.active_object)

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label("Use Properties panel (N) to define parms", icon='INFO')

    def execute(self, context):
        if context.mode == "OBJECT":
            d = archipack_molding.datablock(context.active_object)
            d.update_path(context)
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Archipack: Option only valid in Object mode")
            return {'CANCELLED'}


class ARCHIPACK_OT_molding_from_curve(ArchipackCreateTool, Operator):
    bl_idname = "archipack.molding_from_curve"
    bl_label = "Molding curve"
    bl_description = "Create a molding from a curve"
    bl_category = 'Archipack'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return context.active_object is not None and context.active_object.type == 'CURVE'

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label("Use Properties panel (N) to define parms", icon='INFO')

    def create(self, context):
        o = None
        curve = context.active_object
        for i, spline in enumerate(curve.data.splines):
            bpy.ops.archipack.molding('INVOKE_DEFAULT', auto_manipulate=False)
            o = context.active_object
            d = archipack_molding.datablock(o)
            d.auto_update = False
            d.user_defined_spline = i
            d.user_defined_path = curve.name
            d.auto_update = True
        return o

    def execute(self, context):
        if context.mode == "OBJECT":
            bpy.ops.object.select_all(action="DESELECT")
            o = self.create(context)
            if o is not None:
                o.select = True
                context.scene.objects.active = o
            # self.manipulate()
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Archipack: Option only valid in Object mode")
            return {'CANCELLED'}


class ARCHIPACK_OT_molding_from_wall(ArchipackCreateTool, Operator):
    bl_idname = "archipack.molding_from_wall"
    bl_label = "->Floor"
    bl_description = "Create molding from a wall"
    bl_category = 'Archipack'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        o = context.active_object
        return o is not None and o.data is not None and 'archipack_wall2' in o.data

    def molding_from_wall(self, context, w, wd):
        """
         Create flooring from surrounding wall
         Use slab cutters, windows and doors, T childs walls
        """
        # wall is either a single or collection of polygons
        io, wall = wd.as_geom(context, w, 'FLOOR_MOLDINGS', [], [], [])
        ref = w.parent
        # find slab holes if any
        o = None
        # MultiLineString
        if wall.type_id == 5:
            lines = wall.geoms
        else:
            lines = [wall]
        for i, line in enumerate(lines):
            boundary = io._to_curve(line, "{}-boundary".format(w.name), '2D')
            bpy.ops.archipack.molding(auto_manipulate=False, filepath=self.filepath)
            o = context.active_object
            o.matrix_world = w.matrix_world.copy()
            if ref is not None:
                o.parent = ref
            d = archipack_molding.datablock(o)
            d.auto_update = False
            d.user_defined_path = boundary.name
            d.user_defined_spline = i
            d.auto_update = True
            self.delete_object(context, boundary)
            d.user_defined_path = ""
            o.select = True
            context.scene.objects.active = o
        return o

    def create(self, context):
        wall = context.active_object
        wd = wall.data.archipack_wall2[0]
        o = self.molding_from_wall(context, wall, wd)
        return o

    # -----------------------------------------------------
    # Execute
    # -----------------------------------------------------
    def execute(self, context):
        if context.mode == "OBJECT":
            bpy.ops.object.select_all(action="DESELECT")
            o = self.create(context)
            if o is None:
                return {'FINISHED'}
            o.select = True
            context.scene.objects.active = o
            # if self.auto_manipulate:
            #    bpy.ops.archipack.manipulate('INVOKE_DEFAULT')
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "Archipack: Option only valid in Object mode")
            return {'CANCELLED'}
            
# ------------------------------------------------------------------
# Define operator class to load / save presets
# ------------------------------------------------------------------


class ARCHIPACK_OT_molding_preset_menu(PresetMenuOperator, Operator):
    bl_description = "Show Molding Presets"
    bl_idname = "archipack.molding_preset_menu"
    bl_label = "Molding Styles"
    preset_subdir = "archipack_molding"


class ARCHIPACK_OT_molding_preset(ArchipackPreset, Operator):
    """Add a Molding Preset"""
    bl_idname = "archipack.molding_preset"
    bl_label = "Add Molding Style"
    preset_menu = "ARCHIPACK_OT_molding_preset_menu"

    @property
    def blacklist(self):
        return ['manipulators', 'n_parts', 'parts', 'user_defined_path', 'user_defined_spline']


def register():
    bpy.utils.register_class(archipack_molding_part)
    bpy.utils.register_class(archipack_molding)
    Mesh.archipack_molding = CollectionProperty(type=archipack_molding)
    bpy.utils.register_class(ARCHIPACK_OT_molding_preset_menu)
    bpy.utils.register_class(ARCHIPACK_PT_molding)
    bpy.utils.register_class(ARCHIPACK_OT_molding)
    bpy.utils.register_class(ARCHIPACK_OT_molding_preset)
    bpy.utils.register_class(ARCHIPACK_OT_molding_from_curve)
    bpy.utils.register_class(ARCHIPACK_OT_molding_from_wall)
    bpy.utils.register_class(ARCHIPACK_OT_molding_curve_update)
    

def unregister():
    bpy.utils.unregister_class(archipack_molding_part)
    bpy.utils.unregister_class(archipack_molding)
    del Mesh.archipack_molding
    bpy.utils.unregister_class(ARCHIPACK_OT_molding_preset_menu)
    bpy.utils.unregister_class(ARCHIPACK_PT_molding)
    bpy.utils.unregister_class(ARCHIPACK_OT_molding)
    bpy.utils.unregister_class(ARCHIPACK_OT_molding_preset)
    bpy.utils.unregister_class(ARCHIPACK_OT_molding_from_curve)
    bpy.utils.unregister_class(ARCHIPACK_OT_molding_from_wall)
    bpy.utils.unregister_class(ARCHIPACK_OT_molding_curve_update)
    