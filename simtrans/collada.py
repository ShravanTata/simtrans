# -*- coding:utf-8 -*-

"""Reader and writer for collada format

:Organization:
 AIST

Requirements
------------
* numpy
* lxml xml parser
* pycollada

Examples
--------

Read collada model data given the file path

>>> r = ColladaReader()
>>> m = r.read('package://atlas_description/meshes/head.dae')

"""

from __future__ import absolute_import
from . import model
import warnings
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    from .thirdparty import transformations as tf
import os
import collada
import numpy
import uuid
import lxml
from StringIO import StringIO


class ColladaReader(object):
    '''
    Collada reader class
    '''
    def __init__(self):
        self._basepath = None
        self._assethandler = None
        self._materials = {}

    def read(self, f, assethandler=None, submesh=None):
        '''
        Read collada model data given the file path
        '''
        self._basepath = os.path.dirname(f)
        self._assethandler = assethandler
        try:
            d = collada.Collada(f)
        except:
            # workaround for pycollada's handling of xml comments
            xdoc = lxml.etree.parse(f)
            for c in xdoc.xpath('//comment()'):
                p = c.getparent()
                p.remove(c)
            try:
                d = collada.Collada(StringIO(lxml.etree.tostring(xdoc)))
            except:
                print "error while processing %s" % f
                raise
        for m in d.materials:
            mm = model.MaterialModel()
            mm.name = m.id
            if type(m.effect.diffuse) == collada.material.Map:
                fname = os.path.abspath(os.path.join(self._basepath, m.effect.diffuse.sampler.surface.image.path))
                if not os.path.exists(fname):
                    if fname.count('/meshes/') > 0:
                        fname = fname.replace('/meshes/', '/materials/textures/')
                if self._assethandler:
                    mm.texture = self._assethandler(fname)
                else:
                    mm.texture = fname
            self._materials[mm.name] = mm
        m = model.MeshTransformData()
        unitmeter = d.assetInfo.unitmeter
        m.matrix = tf.scale_matrix(unitmeter)
        m.children = []
        rootnodes = d.scene.nodes
        if submesh is not None:
            for n in d.scene.nodes:
                f = self.findchild(n, submesh)
                if f is not None:
                    rootnodes = [f]
                    break
        for n in rootnodes:
            cm = self.convertchild(n)
            if cm is not None:
                m.children.append(cm)
        return m

    def findchild(self, d, name):
        if type(d) not in [collada.scene.Node, collada.scene.NodeNode]:
            return None
        try:
            if d.xmlnode.attrib['name'] == name:
                return d
        except KeyError:
            pass
        for c in d.children:
            f = self.findchild(c, name)
            if f is not None:
                return f
        return None

    def convertchild(self, d):
        m = None
        if type(d) in [collada.scene.Node, collada.scene.NodeNode]:
            m = model.MeshTransformData()
            m.matrix = d.matrix
            m.children = []
            for c in d.children:
                m.children.append(self.convertchild(c))
        elif type(d) == collada.scene.GeometryNode:
            m = model.MeshTransformData()
            materialmap = {}
            for mm in d.materials:
                materialmap[mm.symbol] = self._materials[mm.target.id]
            for p in d.geometry.primitives:
                sm = model.MeshData()
                sm.vertex = p.vertex
                if len(p.vertex_index.shape) == 2:
                    sm.vertex_index = p.vertex_index
                else:
                    sm.vertex_index = numpy.array(p.vertex_index).reshape(len(p.vertex_index)/3, 3)
                if p.normal is not None:
                    sm.normal = p.normal
                    if len(p.normal_index.shape) == 2:
                        sm.normal_index = p.normal_index
                    else:
                        sm.normal_index = numpy.array(p.normal_index).reshape(len(p.normal_index)/3, 3)
                if len(p.texcoordset) > 0:
                    sm.uvmap = p.texcoordset[0]
                    if len(p.texcoord_indexset[0].shape) == 2:
                        sm.uvmap_index = p.texcoord_indexset[0]
                    else:
                        sm.uvmap_index = numpy.array(p.texcoord_indexset[0]).reshape(len(p.texcoord_indexset[0])/3, 3)
                try:
                    sm.material = materialmap[p.material]
                except KeyError:
                    sm.material = model.MaterialModel()
                m.children.append(sm)
        return m


class ColladaWriter(object):
    '''
    Collada writer class
    '''
    def __init__(self):
        self._mesh = None
        self._matnode = None

    def write(self, m, f):
        '''
        Write simulation model in collada format
        '''
        # we use pycollada to generate the dae file
        self._mesh = collada.Collada()

        # create effect and material
        if m.data.material:
            effect = collada.material.Effect("effect0", [], "phong",
                                             double_sided=True,
                                             diffuse=m.data.material.diffuse,
                                             specular=m.data.material.specular)
        else:
            effect = collada.material.Effect("effect0", [], "phong",
                                             double_sided=True,
                                             diffuse=(0.8,0.8,0.8),
                                             specular=(1,1,1))
        mat = collada.material.Material("material0", "mymaterial", effect)
        self._mesh.effects.append(effect)
        self._mesh.materials.append(mat)
        self._matnode = collada.scene.MaterialNode("materialref", mat, inputs=[])

        # convert shapes recursively
        node = collada.scene.Node("root", children=[self.convertchild(m.data)])

        # create scene graph
        myscene = collada.scene.Scene("myscene", [node])
        self._mesh.scenes.append(myscene)
        self._mesh.scene = myscene
        self._mesh.write(f)

    def convertchild(self, m):
        if type(m) == model.MeshTransformData:
            children = []
            name = 'node-' + str(uuid.uuid1()).replace('-', '')
            for c in m.children:
                cn = self.convertchild(c)
                if cn:
                    children.append(cn)
            node = collada.scene.Node(name, children=children)
            return node
        elif type(m) == model.MeshData:
            name = 'shape-' + str(uuid.uuid1()).replace('-', '')
            vertexname = name + '-vertex'
            normalname = name + '-normal'
            sources = []
            input_list = collada.source.InputList()
            sources.append(collada.source.FloatSource(vertexname, m.vertex.reshape(1, m.vertex.size), ('X', 'Y', 'Z')))
            indices = m.vertex_index.reshape(1, m.vertex_index.size)
            input_list.addInput(0, 'VERTEX', '#' + vertexname)
            if m.normal is not None:
                sources.append(collada.source.FloatSource(normalname, m.normal.reshape(1, m.normal.size), ('X', 'Y', 'Z')))
                indices = numpy.vstack([indices, m.normal_index.reshape(1, m.normal_index.size)])
                input_list.addInput(1, 'NORMAL', '#' + normalname)
            geom = collada.geometry.Geometry(self._mesh, 'geometry0', name, sources, double_sided=True)
            # create triangles
            triset = geom.createTriangleSet(indices.T.reshape(1, indices.size), input_list, 'materialref')
            geom.primitives.append(triset)
            self._mesh.geometries.append(geom)
            node = collada.scene.GeometryNode(geom, [self._matnode])
            return node
        return None
