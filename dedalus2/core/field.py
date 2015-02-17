"""
Class for data fields.

"""

import weakref
from functools import partial
from collections import defaultdict
import numpy as np
from mpi4py import MPI
from scipy import sparse
from scipy.sparse import linalg as splinalg

from .metadata import Metadata
from ..libraries.fftw import fftw_wrappers as fftw
from ..tools.config import config
from ..tools.array import reshape_vector
from ..tools.cache import CachedMethod
from ..tools.exceptions import UndefinedParityError
from ..tools.exceptions import SymbolicParsingError

import logging
logger = logging.getLogger(__name__.split('.')[-1])

# Load config options
permc_spec = config['linear algebra']['permc_spec']
use_umfpack = config['linear algebra'].getboolean('use_umfpack')


class Operand:

    def __getattr__(self, attr):
        # Intercept numpy ufunc calls
        from .operators import UnaryGridFunction
        try:
            ufunc = UnaryGridFunction.supported[attr]
            return partial(UnaryGridFunction, ufunc, self)
        except KeyError:
            raise AttributeError("%r object has no attribute %r" %(self.__class__.__name__, attr))

    ## Idea for alternate ufunc implementation based on changes coming in numpy 1.10
    # def __numpy_ufunc__(self, ufunc, method, i, inputs, **kw):
    #     from .operators import UnaryGridFunction
    #     if ufunc in UnaryGridFunction.supported:
    #         return UnaryGridFunction(ufunc, self, **kw)
    #     else:
    #         return NotImplemented

    def __abs__(self):
        # Call: abs(self)
        from .operators import UnaryGridFunction
        return UnaryGridFunction(np.absolute, self)

    def __neg__(self):
        # Call: -self
        return ((-1) * self)

    def __add__(self, other):
        # Call: self + other
        from .operators import Add
        return Add(self, other)

    def __radd__(self, other):
        # Call: other + self
        from .operators import Add
        return Add(other, self)

    def __sub__(self, other):
        # Call: self - other
        return (self + (-other))

    def __rsub__(self, other):
        # Call: other - self
        return (other + (-self))

    def __mul__(self, other):
        # Call: self * other
        from .operators import Multiply
        return Multiply(self, other)

    def __rmul__(self, other):
        # Call: other * self
        from .operators import Multiply
        return Multiply(other, self)

    def __truediv__(self, other):
        # Call: self / other
        return (self * other**(-1))

    def __rtruediv__(self, other):
        # Call: other / self
        return (other * self**(-1))

    def __pow__(self, other):
        # Call: self ** other
        from .operators import Power
        return Power(self, other)

    def __rpow__(self, other):
        # Call: other ** self
        from .operators import Power
        return Power(other, self)

    @staticmethod
    def parse(string, namespace, domain):
        """Build operand from a string expression."""
        expression = eval(string, namespace)
        return Operand.cast(expression, domain)

    @staticmethod
    def cast(x, domain=None):
        x = Operand.raw_cast(x)
        if domain:
            # Replace empty domains
            if x.domain.dim == 0:
                x.domain = domain
            elif x.domain != domain:
                    raise ValueError("Cannot cast operand to different domain.")
        return x

    @staticmethod
    def raw_cast(x):
        if isinstance(x, Operand):
            return x
        elif np.isscalar(x):
            return Scalar(value=x)
        else:
            raise ValueError("Cannot cast type: {}".format(type(x)))


class Data(Operand):

    __array_priority__ = 100.

    def __repr__(self):
        return '<{} {}>'.format(self.__class__.__name__, id(self))

    def __str__(self):
        if self.name:
            return self.name
        else:
            return self.__repr__()

    def atoms(self, *types, **kw):
        if isinstance(self, types) or (not types):
            return (self,)
        else:
            return ()

    def has(self, *atoms):
        return (self in atoms)

    def expand(self, *vars):
        """Return self."""
        return self

    def canonical_linear_form(self, *vars):
        """Return self."""
        return self

    def factor(self, *vars):
        if self in vars:
            return defaultdict(int, {self: 1})
        else:
            return defaultdict(int, {1: self})

    def split(self, *vars):
        if self in vars:
            return [self, 0]
        else:
            return [0, self]

    def replace(self, old, new):
        """Replace an object in the expression tree."""
        if self == old:
            return new
        else:
            return self

    def order(self, *ops):
        return 0

    def operator_dict(self, index, vars, **kw):
        if self in vars:
            return defaultdict(int, {self: 1})
        else:
            raise SymbolicParsingError('{} is not one of the specified variables.'.format(str(self)))

    def sym_diff(self, var):
        """Symbolically differentiate with respect to var."""
        if self == var:
            return 1
        else:
            return 0


class Scalar(Data):

    class ScalarMeta:
        """Shortcut class to return scalar metadata for any axis."""
        def __init__(self, scalar=None):
            self.scalar = scalar

        def __getitem__(self, axis):
            if self.scalar and (self.scalar.value == 0):
                parity = 0
            else:
                parity = 1
            return {'constant': True, 'parity': parity, 'scale': None}

    def __init__(self, value=0, name=None, domain=None):
        from .domain import EmptyDomain
        self.name = name
        self.meta = self.ScalarMeta(self)
        self.domain = EmptyDomain()
        self.value = value

    def __eq__(self, other):
        if self.name is None:
            return (self.value == other)
        else:
            return super().__eq__(other)

    def __hash__(self):
        return hash((self.name, self.value))

    def as_ncc_operator(self, **kw):
        """Return self.value."""
        return self.value

    def __str__(self):
        if self.name:
            return self.name
        else:
            return repr(self.value)


class Array(Data):

    def __init__(self, domain, name=None):
        self.domain = domain
        self.name = name
        self.meta = Metadata(domain)

        layout = domain.dist.grid_layout
        scales = domain.dealias

        self.data = np.zeros(shape=layout.local_shape(scales),
                             dtype=layout.dtype)

        for i in range(domain.dim):
            self.meta[i]['scale'] = scales[i]

    def set_scales(self, scales, *, keep_data):
        """Set new transform scales."""
        pass

    def from_global_vector(self, data, axis):
        # Set metadata
        for i in range(self.domain.dim):
            axmeta = self.meta[i]
            if i == axis:
                axmeta['constant'] = False
            else:
                axmeta['constant'] = True
            if 'parity' in axmeta:
                axmeta['parity'] = 1
        # Save local slice
        scales = self.meta[:]['scale']
        local_slice =  self.domain.dist.grid_layout.slices(scales)[axis]
        local_data = data[local_slice]
        local_data = reshape_vector(data[local_slice], dim=self.domain.dim, axis=axis)
        np.copyto(self.data, local_data)

    def from_local_vector(self, data, axis):
        # Set metadata
        for i in range(self.domain.dim):
            axmeta = self.meta[i]
            if i == axis:
                axmeta['constant'] = False
            else:
                axmeta['constant'] = True
            if 'parity' in axmeta:
                axmeta['parity'] = 1
        # Save data
        np.copyto(self.data, data)

    @CachedMethod
    def as_ncc_operator(self, **kw):
        """Cast to field and convert to NCC operator."""
        from .future import FutureField
        ncc = FutureField.cast(self, self.domain)
        ncc = ncc.evaluate()
        if 'name' not in kw:
            kw['name'] = str(self)
        return ncc.as_ncc_operator(**kw)


class Field(Data):
    """
    Scalar field over a domain.

    Parameters
    ----------
    domain : domain object
        Problem domain
    name : str, optional
        Field name (default: Python object id)

    Attributes
    ----------
    layout : layout object
        Current layout of field
    data : ndarray
        View of internal buffer in current layout

    """

    # To Do: cache deallocation

    def __init__(self, domain, name=None, allocate=True):

        # Initial attributes
        self.domain = domain
        self.name = name

        # Metadata
        self.meta = Metadata(domain)

        # Set layout and scales to build buffer and data
        self._layout = domain.dist.coeff_layout
        if allocate:
            self.set_scales(1, keep_data=False)
        self.name = name

    @property
    def layout(self):
        return self._layout

    @layout.setter
    def layout(self, layout):
        self._layout = layout
        # Update data view
        scales = self.meta[:]['scale']
        self.data = np.ndarray(shape=layout.local_shape(scales),
                               dtype=layout.dtype,
                               buffer=self.buffer)

    def __getitem__(self, layout):
        """Return data viewed in specified layout."""

        self.require_layout(layout)
        return self.data

    def __setitem__(self, layout, data):
        """Set data viewed in a specified layout."""

        self.layout = self.domain.distributor.get_layout_object(layout)
        np.copyto(self.data, data)

    @staticmethod
    def _create_buffer(buffer_size):
        """Create buffer for Field data."""

        if buffer_size == 0:
            # FFTW doesn't like allocating size-0 arrays
            return np.zeros((0,), dtype=np.float64)
        else:
            # Use FFTW SIMD aligned allocation
            alloc_doubles = buffer_size // 8
            return fftw.create_buffer(alloc_doubles)

    def set_scales(self, scales, *, keep_data):
        """Set new transform scales."""

        new_scales = self.domain.remedy_scales(scales)
        old_scales = self.meta[:]['scale']
        if new_scales == old_scales:
            return

        if keep_data:
            # Forward transform until remaining scales match
            for axis in reversed(range(self.domain.dim)):
                if not self.layout.grid_space[axis]:
                    break
                if old_scales[axis] != new_scales[axis]:
                    self.require_coeff_space(axis)
                    break
            # Reference data
            old_data = self.data

        # Set metadata
        for axis, scale in enumerate(new_scales):
            self.meta[axis]['scale'] = scale
        # Build new buffer
        buffer_size = self.domain.distributor.buffer_size(new_scales)
        self.buffer = self._create_buffer(buffer_size)
        # Reset layout to build new data view
        self.layout = self.layout

        if keep_data:
            np.copyto(self.data, old_data)

    def require_layout(self, layout):
        """Change to specified layout."""

        layout = self.domain.distributor.get_layout_object(layout)

        # Transform to specified layout
        if self.layout.index < layout.index:
            while self.layout.index < layout.index:
                #self.domain.distributor.increment_layout(self)
                self.towards_grid_space()
        elif self.layout.index > layout.index:
            while self.layout.index > layout.index:
                #self.domain.distributor.decrement_layout(self)
                self.towards_coeff_space()

    def towards_grid_space(self):
        """Change to next layout towards grid space."""
        index = self.layout.index
        self.domain.dist.paths[index].increment([self])

    def towards_coeff_space(self):
        """Change to next layout towards coefficient space."""
        index = self.layout.index
        self.domain.dist.paths[index-1].decrement([self])

    def require_grid_space(self, axis=None):
        """Require one axis (default: all axes) to be in grid space."""

        if axis is None:
            while not all(self.layout.grid_space):
                self.towards_grid_space()
        else:
            while not self.layout.grid_space[axis]:
                self.towards_grid_space()

    def require_coeff_space(self, axis=None):
        """Require one axis (default: all axes) to be in coefficient space."""

        if axis is None:
            while any(self.layout.grid_space):
                self.towards_coeff_space()
        else:
            while self.layout.grid_space[axis]:
                self.towards_coeff_space()

    def require_local(self, axis):
        """Require an axis to be local."""

        # Move towards transform path, since the surrounding layouts are local
        if self.layout.grid_space[axis]:
            while not self.layout.local[axis]:
                self.towards_coeff_space()
        else:
            while not self.layout.local[axis]:
                self.towards_grid_space()

    def differentiate(self, basis, out=None):
        """Differentiate field along one basis."""

        # Use differentiation operator
        basis = self.domain.get_basis_object(basis)
        axis = self.domain.bases.index(basis)
        diff_op = basis.Differentiate
        return diff_op(self, out=out).evaluate()

    def integrate(self, *bases, out=None):
        """Integrate field over bases."""

        # Use integration operator
        from .operators import Integrate
        return Integrate(self, *bases, out=out).evaluate()

    def antidifferentiate(self, basis, bc, out=None):
        """
        Antidifferentiate field by setting up a simple linear BVP.

        Parameters
        ----------
        basis : basis-like
            Basis to antidifferentiate along
        bc : (str, object) tuple
            Boundary conditions as (functional, value) tuple.
            `functional` is a string, e.g. "left", "right", "int"
            `value` is a field or scalar
        out : field, optional
            Output field

        """

        # References
        basis = self.domain.get_basis_object(basis)
        domain = self.domain
        bc_type, bc_val = bc

        # Only solve along last basis
        if basis is not domain.bases[-1]:
            raise NotImplementedError()

        # Convert BC value to field
        if np.isscalar(bc_val):
            bc_val = domain.new_field()
            bc_val['g'] = bc[1]
        elif not isinstance(bc_val, Field):
            raise TypeError("bc_val must be field or scalar")

        # Build LHS matrix
        size = basis.coeff_size
        dtype = basis.coeff_dtype
        Pre = basis.Pre
        Diff = basis.Diff
        BC = getattr(basis, bc_type.capitalize())
        try:
            Lm = basis.Match
        except AttributeError:
            Lm = sparse.csr_matrix((size, size), dtype=dtype)

        # Find rows to replace
        BC_rows = BC.nonzero()[0]
        Lm_rows = Lm.nonzero()[0]
        F = sparse.identity(basis.coeff_size, dtype=basis.coeff_dtype, format='dok')
        for i in set().union(BC_rows, Lm_rows):
            F[i, i] = 0
        G = F*Pre
        LHS = G*Diff + BC + Lm

        if not out:
            out = self.domain.new_field()
        out_c = out['c']
        f_c = self['c']
        bc_c = bc_val['c']

        # Solve for each pencil
        for p in np.ndindex(out_c.shape[:-1]):
            rhs = G*f_c[p] + BC*bc_c[p]
            out_c[p] = splinalg.spsolve(LHS, rhs, use_umfpack=use_umfpack, permc_spec=permc_spec)

        return out

    @staticmethod
    def cast(input, domain):
        from .operators import FieldCopy
        from .future import FutureField
        # Cast to operand and check domain
        input = Operand.cast(input, domain=domain)
        if isinstance(input, (Field, FutureField)):
            return input
        else:
            # Cast to FutureField
            return FieldCopy(input, domain)

    @CachedMethod
    def as_ncc_operator(self, cutoff, max_terms, name=None):
        """Convert to operator form representing multiplication as a NCC."""
        if name is None:
            name = str(self)
        domain = self.domain
        for basis in domain.bases:
            if basis.separable:
                if not self.meta[basis.name]['constant']:
                    raise ValueError("{} is non-constant along separable direction '{}'.".format(name, basis.name))
        basis = domain.bases[-1]
        coeffs = np.zeros(basis.coeff_size, dtype=basis.coeff_dtype)
        # Scatter transverse-constant coefficients
        self.require_coeff_space()
        if domain.dist.rank == 0:
            select = (0,) * (domain.dim - 1)
            np.copyto(coeffs, self.data[select])
        domain.dist.comm_cart.Bcast(coeffs, root=0)
        # Build matrix
        n_terms, max_term, matrix = basis.NCC(coeffs, cutoff, max_terms)
        logger.info("Expanded NCC '{}' to mode {} with {} terms.".format(name, max_term, n_terms))
        return matrix