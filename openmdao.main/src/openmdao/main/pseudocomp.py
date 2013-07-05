
import ast
from threading import RLock

from openmdao.main.numpy_fallback import array

from openmdao.main.expreval import ConnectedExprEvaluator, _expr_dict
from openmdao.main.printexpr import transform_expression, print_node
from openmdao.main.attrwrapper import UnitsAttrWrapper

from openmdao.units.units import PhysicalQuantity, UnitsOnlyPQ

_namelock = RLock()
_count = 0

def _get_new_name():
    global _count
    with _namelock:
        name = "_pseudo_%d" % _count
        _count += 1
    return name

def _get_varname(name):
    idx = name.find('[')
    if idx == -1:
        return name
    return name[:idx]

def unit_transform(node, in_units, out_units):
    """Transforms an expression into expr*scaler+adder."""
    inpq = PhysicalQuantity(1.0, in_units)
    outpq = PhysicalQuantity(1.0, out_units)
    try:
        scaler, adder = inpq.unit.conversion_tuple_to(outpq.unit)
    except TypeError:
        raise TypeError("units '%s' are incompatible with assigning units of '%s'" % (inpq.get_unit_name(), outpq.get_unit_name()))
        
    newnode = ast.BinOp(node, ast.Mult(), ast.Num(scaler))
    if adder != 0.0: # do the multiply and the add
        newnode = ast.BinOp(newnode, ast.Add(), 
                            ast.Num(scaler*adder))
    return ast.copy_location(newnode, node)

class DummyExpr(object):
    def __init__(self):
        self.text = ''

    def refs(self):
        return ['']

    def get_metadata(self):
        return [('', {})]
    
def _invert_dict(dct):
    out = {}
    for k,v in dct.items():
        out[v] = k
    return out

class PseudoComponent(object):
    """A 'fake' component that is constructed from an ExprEvaluator.
    This fake component can be added to a dependency graph and executed
    along with 'real' components.
    """

    def __init__(self, parent, srcexpr, destexpr=None):
        if destexpr is None:
            destexpr = DummyExpr()
        self.name = _get_new_name()
        self._mapping = {}
        self._meta = {}
        self._valid = False
        self._parent = parent
        self._inputs = []

        varmap = {}
        for name, meta in srcexpr.get_metadata():
            self._meta[name] = meta

        for i,ref in enumerate(srcexpr.refs()):
            in_name = 'in%d' % i
            self._inputs.append(in_name)
            self._mapping[ref] = in_name
            varmap[_get_varname(ref)] = in_name
            setattr(self, in_name, None)

        self._outdest = destexpr.text

        refs = list(destexpr.refs())
        if refs:
            if len(refs) == 1:
                setattr(self, 'out0', None)
            else:
                raise RuntimeError("output of PseudoComponent must reference only one variable")

        # attach metadata to local var names
        newmeta = {}
        for key, val in self._meta.items():
            newmeta[varmap[key]] = val
            
        for name, meta in destexpr.get_metadata():
            self._meta[name] = meta
            
        newmeta['out0'] = self._meta[_get_varname(refs[0])]
        self._meta = newmeta

        xformed_src = transform_expression(srcexpr.text, self._mapping)
        xformed_dest = transform_expression(destexpr.text, { destexpr.text: 'out0'})

        out_units = self._meta['out0'].get('units')
        if out_units is not None:
            # evaluate the src expression using UnitsOnlyPQ objects

            tmpdict = {}

            # First, replace values with UnitsOnlyPQ objects
            for inp in self._inputs:
                units = self._meta[inp].get('units')
                if units:
                    tmpdict[inp] = UnitsOnlyPQ(0., units)
                else:
                    tmpdict[inp] = 0.

            pq = eval(xformed_src, _expr_dict, tmpdict)
            self._srcunits = pq.unit

            unitnode = ast.parse(xformed_src)
            try:
                unitxform = unit_transform(unitnode, self._srcunits, out_units)
            except Exception as err:
                raise TypeError("Can't connect '%s' to '%s': %s" % (srcexpr.text, 
                                                                    destexpr.text, err))
            unit_src = print_node(unitxform)
            xformed_src = unit_src
        else:
            self._srcunits = None

        self._srcexpr = ConnectedExprEvaluator(xformed_src, scope=self)
        self._destexpr = ConnectedExprEvaluator(xformed_dest, scope=self)

        # this is just the equation string (for debugging)
        if destexpr and destexpr.text:
            out = destexpr.text
        else:
            out = 'out0'
        self._eqn = "%s = %s" % (out, transform_expression(self._srcexpr.text, _invert_dict(self._mapping)))

    def get_pathname(self, rel_to_scope=None):
        """ Return full pathname to this object, relative to scope
        *rel_to_scope*. If *rel_to_scope* is *None*, return the full pathname.
        """
        return '.'.join([self._parent.get_pathname(rel_to_scope), self.name])

    def list_connections(self, is_hidden=False):
        """list all of the inputs and outputs of this comp. If is_hidden
        is True, list the connections that a user would see if this
        PseudoComponent is hidden.
        """
        if is_hidden:
            if self._outdest:
                return [(src, self._outdest) for src in self._mapping.keys()]
            else:
                return []
        else:
            conns = [(src, '.'.join([self.name, dest])) 
                         for src, dest in self._mapping.items()]
            if self._outdest:
                conns.append(('.'.join([self.name, 'out0']), self._outdest))
        return conns

    def make_connections(self):
        """Connect all of the inputs and outputs of this comp to
        the appropriate nodes in the dependency graph.
        """
        for src, dest in self.list_connections():
            self._parent._connect(src, dest)

    def remove_connections(self):
        """Disconnect all of the inputs and outputs of this comp
        from other nodes in the dependency graph.
        """
        for src, dest in self.list_connections():
            self._parent.disconnect(src, dest)

    def invalidate_deps(self, varnames=None, force=False):
        self._valid = False

    def connect(self, src, dest):
        self._valid = False

    def run(self, ffd_order=0, case_id=''):
        if not self._valid:
            self._parent.update_inputs(self.name, None)

        src = self._srcexpr.evaluate()
        if isinstance(src, PhysicalQuantity):
            units = self._meta['out0'].get('units')
            if units is not None:
                src = src.in_units_of(units).value
            else:
                src = src.value
        self._destexpr.set(src)
        self._valid = True

    def update_outputs(self, names):
        self.run()

    def get(self, name, index=None):
        if index is not None:
            raise RuntimeError("index not supported in PseudoComponent.get")
        return getattr(self, name)

    def set(self, path, value, index=None, src=None, force=False):
        if index is not None:
            raise ValueError("index not supported in PseudoComponent.set")
        if isinstance(value, UnitsAttrWrapper):
            setattr(self, path, value.pq.value)
        elif isinstance(value, PhysicalQuantity):
            setattr(self, path, value.value)
        else:
            setattr(self, path, value)

    def get_wrapped_attr(self, name, index=None):
        if index is not None:
            raise RuntimeError("pseudocomponent attr accessed using an index")
        #return create_attr_wrapper(getattr(self, name), self._meta[name])
        return getattr(self, name)

    def get_metadata(self, traitpath, metaname=None):
        """Retrieve the metadata associated with the trait found using
        traitpath.  If metaname is None, return the entire metadata dictionary
        for the specified trait. Otherwise, just return the specified piece
        of metadata.  If the specified piece of metadata is not part of
        the trait, None is returned.
        """
        if metaname is None:
            return {}
        return None

    def get_valid(self, names):
        return [self._valid]*len(names)

    def is_valid(self):
        return self._valid

    def set_itername(self, itername):
        self._itername = itername

    def calc_derivatives(self, first=False, second=False, savebase=False):
        if first:
            self.linearize()
        if second:
            raise RuntimeError("2nd derivatives not supported in pseudocomponent %s" % self.name)

    def linearize(self):
        """Calculate analytical first derivatives."""
        grad = self._srcexpr.evaluate_gradient()
        self.J = array([[grad[n] for n in self._inputs]])

    def provideJ(self):
        return tuple(self._inputs), ('out0',), self.J