"""
Abstract and built-in classes defining deferred operations on fields.

"""

from collections import defaultdict
from functools import partial, reduce
import numpy as np
from scipy import sparse
from numbers import Number
from inspect import isclass

from .domain import Subdomain
from .field import Operand, Array, Field
from .future import Future, FutureArray, FutureField
from ..tools.array import reshape_vector, apply_matrix, add_sparse, axindex, axslice
from ..tools.cache import CachedAttribute
from ..tools.dispatch import MultiClass
from ..tools.exceptions import NonlinearOperatorError
from ..tools.exceptions import SymbolicParsingError
from ..tools.exceptions import UndefinedParityError
from ..tools.general import unify, unify_attributes


# Use simple decorator to track parseable operators
parseables = {}
prefixes = {}

def parseable(*names):
    def register_op(op):
        for name in names:
            parseables[name] = op
        return op
    return register_op

def prefix(*names):
    def register_op(op):
        for name in names:
            prefixes[name] = op
        return op
    return register_op





class Cast(FutureField, metaclass=MultiClass):
    """
    Cast to field.

    Parameters
    ----------
    input : Number or Operand
    domain : Domain object

    """

    @classmethod
    def _check_args(cls, input, domain):
        return isinstance(input, cls.argtype)

    @property
    def base(self):
        return Cast


class CastNumber(Cast):
    """Cast number to field."""

    argtype = Number

    def __init__(self, input, domain, out=None):
        self.args = [input, domain]
        self.original_args = tuple(self.args)
        self.out = out
        self.bases = (None,) * domain.dim
        self.domain = domain
        self.subdomain = Subdomain.from_bases(self.domain, self.bases)
        self._grid_layout = self.domain.dist.grid_layout
        self._coeff_layout = self.domain.dist.coeff_layout
        self.last_id = None
        self.scales = self.subdomain.dealias

    def __str__(self):
        return str(self.number)

    def __eq__(self, other):
        # Compare by value
        return (self.number == other)

    @property
    def number(self):
        return self.args[0]

    def split(self, *vars):
        """Split into expressions containing and not containing specified operands/operators."""
        return (0, self.number)

    def replace(self, old, new):
        """Replace specified operand/operator."""
        return self.number

    def sym_diff(self, var):
        """Symbolically differentiate with respect to specified operand."""
        return 0

    def expand(self, *vars):
        """Expand expression over specified variables."""
        return self.number

    # def simplify(self, *vars):
    #     """Simplify expression, except subtrees containing specified variables."""
    #     return self.number

    def require_linearity(self, *vars, name=None):
        """Require expression to be linear in specified variables."""
        raise NonlinearOperatorError("{} is not linear in the specified variables.".format(name if name else str(self)))

    def separability(self, *vars):
        """Determine separable dimensions of expression as a linear operator on specified variables."""
        raise NonlinearOperatorError("{} is not one of the specified variables.".format(str(self)))

    def build_ncc_matrices(self, separability, vars, **kw):
        """Precompute non-constant coefficients and build multiplication matrices."""
        raise NonlinearOperatorError("{} is not one of the specified variables.".format(str(self)))

    def expression_matrices(self, subproblem, vars):
        """Build expression matrices for a specific subproblem and variables."""
        raise NonlinearOperatorError("{} is not one of the specified variables.".format(str(self)))

    def check_conditions(self):
        """Check that arguments are in a proper layout."""
        # No conditions
        return True

    def enforce_conditions(self):
        """Require arguments to be in a proper layout."""
        # No conditions
        pass

    def operate(self, out):
        """Perform operation."""
        # Copy data
        np.copyto(out.data, self.number)


class CastOperand(Cast):
    """Cast operand to field."""

    argtype = Operand

    def __new__(cls, input, domain):
        # Make sure domains match
        if input.domain is not domain:
            raise ValueError()
        else:
            return input




# class FieldCopy(FutureField):
#     """Operator making a new field copy of data."""

#     name = 'FieldCopy'

#     @classmethod
#     def _preprocess_args(cls, arg, domain, **kw):
#         arg = Operand.cast(arg, domain=domain)
#         return (arg,), kw

#     @classmethod
#     def _check_args(cls, *args, **kw):
#         match = (isinstance(args[i], types) for i,types in cls.argtypes.items())
#         return all(match)

#     def __init__(self, arg, **kw):
#         super().__init__(arg, **kw)
#         self.kw = {'domain': arg.domain}

#     def _build_bases(self, arg0):
#         return arg0.bases

#     def __str__(self):
#         return str(self.args[0])

#     def check_conditions(self):
#         return True

#     def base(self):
#         return FieldCopy

#     def sym_diff(self, var):
#         """Symbolically differentiate with respect to var."""
#         return self.args[0].sym_diff(var)



# class FieldCopyArray(FieldCopy):

#     argtypes = {0: (Array, FutureArray)}

#     def operate(self, out):
#         # Copy in grid layout
#         out.set_layout(self._grid_layout)
#         np.copyto(out.data, self.args[0].data)


# class FieldCopyField(FieldCopy):

#     argtypes = {0: (Field, FutureField)}

#     def operate(self, out):
#         arg0, = self.args
#         # Copy in current layout
#         out.set_layout(arg0.layout)
#         np.copyto(out.data, arg0.data)







class NonlinearOperator(Future):

    def split(self, *vars):
        """Split into expressions containing and not containing specified operands/operators."""
        if self.has(*vars):
            return (self, 0)
        else:
            return (0, self)

    def expand(self, *vars):
        """Expand expression over specified variables."""
        return self

    def require_linearity(self, *vars, name=None):
        """Require expression to be linear in specified variables."""
        raise NonlinearOperatorError("{} is a non-linear function of the specified variables.".format(name if name else str(self)))

    def separability(self, *vars):
        """Determine separable dimensions of expression as a linear operator on specified variables."""
        raise NonlinearOperatorError("{} is a non-linear function of the specified variables.".format(str(self)))

    def build_ncc_matrices(self, separability, vars, **kw):
        """Precompute non-constant coefficients and build multiplication matrices."""
        raise NonlinearOperatorError("{} is a non-linear function of the specified variables.".format(str(self)))

    def expression_matrices(self, subproblem, vars):
        """Build expression matrices for a specific subproblem and variables."""
        raise NonlinearOperatorError("{} is a non-linear function of the specified variables.".format(str(self)))


class Power(NonlinearOperator, metaclass=MultiClass):

    name = 'Pow'
    str_op = '**'

    def _build_bases(self, arg0, arg1):
        return arg0.bases

    @classmethod
    def _preprocess_args(cls, *args, **kw):
        domain = unify_attributes(args, 'domain', require=False)
        args = tuple(Operand.cast(arg, domain) for arg in args)
        return args, kw

    @classmethod
    def _check_args(cls, *args, **kw):
        match = (isinstance(args[i], types) for i,types in cls.argtypes.items())
        arg1_constant = all(b is None for b in args[1].bases)
        return (all(match) and arg1_constant)

    @property
    def base(self):
        return Power

    def sym_diff(self, var):
        """Symbolically differentiate with respect to specified operand."""
        base, power = self.args
        return power * base**(power-1) * base.sym_diff(var)


class PowerFieldConstant(Power, FutureField):

    argtypes = {0: (Field, FutureField),
                1: (Field, FutureField)}

    def __new__(cls, arg0, arg1, *args, **kw):
        if (arg1.name is None) and (arg1.value == 0):
            return 1
        elif (arg1.name is None) and (arg1.value == 1):
            return arg0
        else:
            return object.__new__(cls)

    def __init__(self, arg0, arg1, out=None):
        super().__init__(arg0, arg1, out=out)
        for axis, b0 in enumerate(arg0.bases):
            if b0 is not None:
                self.require_grid_axis = axis
                break
        else:
            self.require_grid_axis = None

    def check_conditions(self):
        layout0 = self.args[0].layout
        layout1 = self.args[1].layout
        # Fields must be in grid layout
        if self.require_grid_axis is not None:
            axis = self.require_grid_axis
            return (layout0.grid_space[axis] and (layout0 is layout1))
        else:
            return (layout0 is layout1)

    def enforce_conditions(self):
        arg0, arg1 = self.args
        if self.require_grid_axis is not None:
            axis = self.require_grid_axis
            arg0.require_grid_space(axis=axis)
        arg1.require_layout(arg0.layout)

    def operate(self, out):
        arg0, arg1 = self.args
        # Multiply in grid layout
        out.set_layout(arg0.layout)
        if out.data.size:
            np.power(arg0.data, arg1.data, out.data)


# class PowerArrayScalar(PowerDataScalar, FutureArray):

#     argtypes = {0: (Array, FutureArray),
#                 1: Number}

#     def check_conditions(self):
#         return True

#     def operate(self, out):
#         arg0, arg1 = self.args
#         np.power(arg0.data, arg1.value, out.data)


# class PowerFieldNumber(PowerDataScalar, FutureField):

#     argtypes = {0: (Field, FutureField),
#                 1: Number}

#     def check_conditions(self):
#         # Field must be in grid layout
#         return (self.args[0].layout is self._grid_layout)

#     def operate(self, out):
#         arg0, arg1 = self.args
#         # Raise in grid layout
#         arg0.require_grid_space()
#         out.set_layout(self._grid_layout)
#         np.power(arg0.data, arg1.value, out.data)




class GeneralFunction(NonlinearOperator, FutureField):
    """
    Operator wrapping a general python function.

    Parameters
    ----------
    domain : domain object
        Domain
    layout : layout object or identifier
        Layout of function output
    func : function
        Function producing field data
    args : list
        Arguments to pass to func
    kw : dict
        Keywords to pass to func
    out : field, optional
        Output field (default: new field)

    Notes
    -----
    On evaluation, this wrapper evaluates the provided funciton with the given
    arguments and keywords, and takes the output to be data in the specified
    layout, i.e.

        out[layout] = func(*args, **kw)

    """

    def __init__(self, domain, layout, func, args=[], kw={}, out=None,):

        # Required attributes
        self.args = list(args)
        self.original_args = list(args)
        self.domain = domain
        self.out = out
        self.last_id = None
        # Additional attributes
        self.layout = domain.distributor.get_layout_object(layout)
        self.func = func
        self.kw = kw
        self._field_arg_indices = [i for (i,arg) in enumerate(self.args) if is_fieldlike(arg)]
        try:
            self.name = func.__name__
        except AttributeError:
            self.name = str(func)
        self.build_metadata()

    def build_metadata(self):
        self.constant = np.array([False] * self.domain.dim)

    def check_conditions(self):
        # Fields must be in proper layout
        for i in self._field_arg_indices:
            if self.args[i].layout is not self.layout:
                return False
        return True

    def operate(self, out):
        # Apply func in proper layout
        for i in self._field_arg_indices:
            self.args[i].require_layout(self.layout)
        out.set_layout(self.layout)
        np.copyto(out.data, self.func(*self.args, **self.kw))


class UnaryGridFunction(NonlinearOperator, metaclass=MultiClass):

    arity = 1
    supported = {ufunc.__name__: ufunc for ufunc in
        (np.absolute, np.sign, np.conj, np.exp, np.exp2, np.log, np.log2,
         np.log10, np.sqrt, np.square, np.sin, np.cos, np.tan, np.arcsin,
         np.arccos, np.arctan, np.sinh, np.cosh, np.tanh, np.arcsinh,
         np.arccosh, np.arctanh)}
    aliased = {'abs':np.absolute, 'conj':np.conjugate}
    # Add ufuncs and shortcuts to parseables
    parseables.update(supported)
    parseables.update(aliased)

    @classmethod
    def _preprocess_args(self, func, arg, **kw):
        #arg = Operand.cast(arg)
        return (func, arg), kw

    @classmethod
    def _check_args(cls, *args, **kw):
        match = (isinstance(args[i], types) for i,types in cls.argtypes.items())
        return all(match)

    def __init__(self, func, arg, **kw):
        #arg = Operand.cast(arg)
        super().__init__(arg, **kw)
        self.func = func

    @property
    def name(self):
        return self.func.__name__

    @property
    def base(self):
        return UnaryGridFunction

    def _build_bases(self, arg0):
        bases = arg0.bases
        if all(basis is None for basis in bases):
            bases = arg0.domain
        return bases

    def meta_constant(self, axis):
        # Preserves constancy
        return self.args[0].meta[axis]['constant']

    def meta_parity(self, axis):
        # Preserving constancy -> even parity
        if self.args[0].meta[axis]['constant']:
            return 1
        elif self.args[0].meta[axis]['parity'] == 1:
            return 1
        else:
            raise UndefinedParityError("Unknown action of {} on odd parity.".format(self._name))

    def sym_diff(self, var):
        """Symbolically differentiate with respect to specified operand."""
        diff_map = {np.absolute: lambda x: np.sign(x),
                    np.sign: lambda x: 0,
                    np.exp: lambda x: np.exp(x),
                    np.exp2: lambda x: np.exp2(x) * np.log(2),
                    np.log: lambda x: x**(-1),
                    np.log2: lambda x: (x * np.log(2))**(-1),
                    np.log10: lambda x: (x * np.log(10))**(-1),
                    np.sqrt: lambda x: (1/2) * x**(-1/2),
                    np.square: lambda x: 2*x,
                    np.sin: lambda x: np.cos(x),
                    np.cos: lambda x: -np.sin(x),
                    np.tan: lambda x: np.cos(x)**(-2),
                    np.arcsin: lambda x: (1 - x**2)**(-1/2),
                    np.arccos: lambda x: -(1 - x**2)**(-1/2),
                    np.arctan: lambda x: (1 + x**2)**(-1),
                    np.sinh: lambda x: np.cosh(x),
                    np.cosh: lambda x: np.sinh(x),
                    np.tanh: lambda x: np.cosh(x)**(-2),
                    np.arcsinh: lambda x: (x**2 + 1)**(-1/2),
                    np.arccosh: lambda x: (x**2 - 1)**(-1/2),
                    np.arctanh: lambda x: (1 - x**2)**(-1)}
        arg = self.args[0]
        arg_diff = arg.sym_diff(var)
        return diff_map[self.func](arg) * arg_diff


# class UnaryGridFunctionScalar(UnaryGridFunction, FutureScalar):

#     argtypes = {1: (Scalar, FutureScalar)}

#     def check_conditions(self):
#         return True

#     def operate(self, out):
#         out.value = self.func(self.args[0].value)


class UnaryGridFunctionArray(UnaryGridFunction, FutureArray):

    argtypes = {1: (Array, FutureArray)}

    def check_conditions(self):
        return True

    def operate(self, out):
        self.func(self.args[0].data, out=out.data)


class UnaryGridFunctionField(UnaryGridFunction, FutureField):

    argtypes = {1: (Field, FutureField)}

    def check_conditions(self):
        # Field must be in grid layout
        return (self.args[0].layout is self._grid_layout)

    def operate(self, out):
        # References
        arg0, = self.args
        # Evaluate in grid layout
        arg0.require_grid_space()
        out.set_layout(self._grid_layout)
        self.func(arg0.data, out=out.data)








class LinearOperator(FutureField):
    """
    Base class for linear operators.
    First argument is expected to be the operand.
    """

    @property
    def operand(self):
        # Set as a property rather than an attribute so it correctly updates during evaluation
        return self.args[0]

    def new_operand(self, operand):
        """Call operator with new operand."""
        args = list(self.args)
        args[0] = operand
        return self.base(*args)

    def split(self, *vars):
        """Split into expressions containing and not containing specified operands/operators."""
        # Check for matching operator
        if self.base in vars:
            return (self, 0)
        # Distribute over split operand
        else:
            return tuple(self.new_operand(arg) for arg in self.operand.split(*vars))

    def sym_diff(self, var):
        """Symbolically differentiate with respect to specified operand."""
        # Differentiate argument
        return self.new_operand(self.operand.sym_diff(var))

    def expand(self, *vars):
        """Expand expression over specified variables."""
        from .arithmetic import Add, Multiply
        if self.has(*vars):
            # Expand operand
            operand = self.operand.expand(*vars)
            # Distribute over linear operators
            if isinstance(operand, LinearOperator):
                return self._expand_linop(operand, vars)
            # Distribute over addition
            elif isinstance(operand, Add):
                return self._expand_add(operand, vars)
            # Distribute over multiplication
            elif isinstance(operand, Multiply):
                return self._expand_multiply(operand, vars)
            # Apply to expanded operand
            else:
                return self.new_operand(operand)
        else:
            return self

    def _expand_linop(self, operand, vars):
        """Expand over linear operators."""
        # By default, perform no further expansion
        return self.new_operand(operand)

    def _expand_add(self, operand, vars):
        """Expand over addition."""
        # There are no sums of sums since addition is flattened
        # Apply to arguments and re-expand to cover sums of products
        return sum((self.new_operand(arg) for arg in operand.args)).expand(*vars)

    def _expand_multiply(self, operand, vars):
        """Expand over multiplication."""
        # There are no products of products since multiplication is flattened
        # There are no products of relevant sums since operand has been expanded
        # By default, perform no further expansion
        return self.new_operand(operand)

    def require_linearity(self, *vars, name=None):
        """Require expression to be linear in specified variables."""
        # Require operand to be linear
        self.operand.require_linearity(*vars, name=name)

    def build_ncc_matrices(self, separability, vars, **kw):
        """Precompute non-constant coefficients and build multiplication matrices."""
        # Build operand matrices
        self.operand.build_ncc_matrices(separability, vars, **kw)

    def expression_matrices(self, subproblem, vars):
        """Build expression matrices for a specific subproblem and variables."""
        # Build operand matrices
        operand_mats = self.operand.expression_matrices(subproblem, vars)
        # Apply operator matrix
        operator_mat = self.subproblem_matrix(subproblem)
        return {var: operator_mat @ operand_mats[var] for var in operand_mats}

    def subproblem_matrix(subproblem):
        """Build operator matrix for a specific subproblem."""
        raise NotImplementedError()


class LinearSubspaceOperator(LinearOperator):
    """
    Base class for linear operators acting within a single space.
    The second argument is expected to be the relevant space.
    """

    def __init__(self, *args, **kw):
        self.space = args[1]
        self.axis = self.space.axis
        self.basis = args[0].bases[self.axis]
        super().__init__(*args, **kw)

    def _build_bases(self, operand, space, *args):
        """Build output bases."""
        input_basis = operand.bases[space.axis]
        # Replace operand basis for relevant space
        bases = list(operand.bases)
        bases[space.axis] = self.output_basis(space, input_basis)
        return tuple(bases)

    def output_basis(self, space, input_basis):
        """Determine output basis."""
        raise NotImplementedError()

    def separability(self, *vars):
        """Determine separable dimensions of expression as a linear operator on specified variables."""
        # Start from operand separability
        separability = self.operand.separability(*vars).copy()
        if not self.separable:
            separability[self.axis] = False
        return separability

    def subproblem_matrix(self, subproblem):
        """Build operator matrix for a specific subproblem."""
        # Build identity matrices for each axis
        group_shape = subproblem.group_shape(self.subdomain)
        factors = [sparse.identity(n, format='csr') for n in group_shape]
        # Substitute group portion of subspace matrix
        if self.separable:
            argslice = subproblem.global_slices(self.operand.subdomain)[self.axis]
            outslice = subproblem.global_slices(self.subdomain)[self.axis]
            factors[self.axis] = self.subspace_matrix[outslice, argslice]
        else:
            factors[self.axis] = self.subspace_matrix
        return reduce(sparse.kron, factors, 1).tocsr()

    @CachedAttribute
    def subspace_matrix(self):
        """Build matrix operating on global subspace data."""
        return self._subspace_matrix(self.space, self.basis, *self.args[2:])

    @classmethod
    def _subspace_matrix(cls, space, basis, *args):
        dtype = space.domain.dtype
        N = space.coeff_size
        # Build matrix entry by entry over nonzero bands
        M = sparse.lil_matrix((N, N), dtype=dtype)
        for i in range(N):
            for b in cls.bands:
                j = i + b
                if (0 <= j < N):
                    Mij = cls._subspace_entry(i, j, space, basis, *args)
                    if Mij:
                        M[i,j] = Mij
        return M.tocsr()

    @staticmethod
    def _subspace_entry(i, j, space, basis, *args):
        raise NotImplementedError()

    def check_conditions(self):
        """Check that arguments are in a proper layout."""
        is_coeff = not self.operand.layout.grid_space[self.axis]
        is_local = self.operand.layout.local[self.axis]
        # Require coefficient space along operator axis
        # Require locality along operator axis if non-separable
        if self.separable:
            return is_coeff
        else:
            return (is_coeff and is_local)

    def enforce_conditions(self):
        """Require arguments to be in a proper layout."""
        # Require coefficient space along operator axis
        self.operand.require_coeff_space(self.axis)
        # Require locality along operator axis if non-separable
        if not self.separable:
            self.operand.require_local(self.axis)

    def operate(self, out):
        """Perform operation."""
        operand = arg = self.operand
        layout = operand.layout
        axis = self.axis
        matrix = self.subspace_matrix
        # Set output layout
        out.set_layout(layout)
        # Restrict subspace matrix to local elements if separable
        if self.separable:
            arg_elements = arg.local_elements()[axis]
            out_elements = out.local_elements()[axis]
            matrix = matrix[arg_elements[:,None], out_elements[None,:]]
        # Apply matrix
        apply_matrix(matrix, operand.data, axis, out=out.data)


class LinearSubspaceFunctional(LinearSubspaceOperator):
    """Base class for linear functionals acting within a single space."""

    separable = False

    def output_basis(self, space, input_basis):
        """Determine output basis."""
        return None

    @classmethod
    def _subspace_matrix(cls, space, basis, *args):
        dtype = space.domain.dtype
        N = space.coeff_size
        # Build row entry by entry
        M = sparse.lil_matrix((1, N), dtype=dtype)
        for j in range(N):
            Mij = cls._subspace_entry(j, space, basis, *args)
            if Mij:
                M[0,j] = Mij
        return M.tocsr()

    @staticmethod
    def _subspace_entry(j, space, basis, *args):
        raise NotImplementedError()


class TimeDerivative(LinearOperator):
    """Class for representing time derivative while parsing."""

    name = 'dt'

    def __new__(cls, arg):
        if isinstance(arg, (Number, Cast)):
            return 0
        else:
            return object.__new__(cls)

    def _build_bases(self, operand):
        """Build output bases."""
        return operand.bases

    @property
    def base(self):
        return TimeDerivative

    def _expand_linop(self, operand, vars):
        """Expand over linear operator."""
        # Halt expansion when hitting another time derivative
        if isinstance(operand, TimeDerivative):
            return self.new_operand(operand)
        # Commute operators and re-expand to continue propagating
        else:
            return operand.new_operand(self.new_operand(operand.operand).expand(*vars))

    def _expand_multiply(self, operand, vars):
        """Expand over multiplication."""
        args = operand.args
        # Apply product rule to factors
        partial_diff = lambda i: np.prod([self.new_operand(arg) if i==j else arg for j,arg in enumerate(args)])
        out = sum((partial_diff(i) for i in range(len(args))))
        # Re-expand to continue propagating
        return out.expand(*vars)

    def separability(self, *vars):
        """Determine separable dimensions of expression as a linear operator on specified variables."""
        return self.operand.separability(*vars).copy()






@parseable('interpolate', 'interp')
def interpolate(arg, **positions):
    # Identify domain
    domain = unify_attributes((arg,)+tuple(positions), 'domain', require=False)
    # Apply iteratively
    for space, position in positions.items():
        space = domain.get_space_object(space)
        arg = Interpolate(arg, space, position)
    return arg


class Interpolate(LinearSubspaceFunctional, metaclass=MultiClass):
    """
    Interpolation along one dimension.

    Parameters
    ----------
    operand : number or Operand object
    space : Space object
    position : 'left', 'center', 'right', or float

    """

    @classmethod
    def _check_args(cls, operand, space, position, out=None):
        # Dispatch by operand basis
        if isinstance(operand, Operand):
            if isinstance(operand.get_basis(space), cls.input_basis_type):
                return True
        return False

    def __init__(self, operand, space, position, out=None):
        self.position = position
        super().__init__(operand, space, position, out=out)

    def _expand_multiply(self, operand, vars):
        """Expand over multiplication."""
        # Apply to each factor
        return np.prod([self.new_operand(arg) for arg in operand.args])

    @property
    def base(self):
        return Interpolate


class InterpolateConstant(Interpolate):
    """Constant interpolation."""

    @classmethod
    def _check_args(cls, operand, space, position, out=None):
        # Dispatch for numbers or constant bases
        if isinstance(operand, Number):
            return True
        if isinstance(operand, Operand):
            if operand.get_basis(space) is None:
                return True
        return False

    def __new__(cls, operand, space, position, out=None):
        return operand


@parseable('integrate', 'integ')
def integrate(arg, *spaces):
    # Identify domain
    domain = unify_attributes((arg,)+spaces, 'domain', require=False)
    # Apply iteratively
    for space in spaces:
        space = domain.get_space_object(space)
        arg = Integrate(arg, space)
    return arg


class Integrate(LinearSubspaceFunctional, metaclass=MultiClass):
    """
    Integration along one dimension.

    Parameters
    ----------
    operand : number or Operand object
    space : Space object

    """

    @classmethod
    def _check_args(cls, operand, space, out=None):
        # Dispatch by operand basis
        if isinstance(operand, Operand):
            if isinstance(operand.get_basis(space), cls.input_basis_type):
                return True
        return False

    @property
    def base(self):
        return Integrate


class IntegrateConstant(Integrate):
    """Constant integration."""

    @classmethod
    def _check_args(cls, operand, space, out=None):
        # Dispatch for numbers or constant bases
        if isinstance(operand, Number):
            return True
        if isinstance(operand, Operand):
            if operand.get_basis(space) is None:
                return True
        return False

    def __new__(cls, operand, space, out=None):
        return (space.COV.problem_length * operand)


# CHECK NEW
@parseable('filter', 'f')
def filter(arg, **modes):
    # Identify domain
    domain = unify_attributes((arg,)+tuple(modes), 'domain', require=False)
    # Apply iteratively
    for space, mode in modes.items():
        space = domain.get_space_object(space)
        arg = Filter(arg, space, mode)
    return arg


class Filter(LinearSubspaceFunctional):

    def __new__(cls, arg, space, mode):
        if isinstance(arg, Number) or (arg.get_basis(space) is None):
            if mode == 0:
                return arg
            else:
                return 0
        elif space not in arg.subdomain:
            raise ValueError("Invalid space.")
        else:
            return object.__new__(cls)

    def __init__(self, arg, space, mode):
        # Wrap initialization to define keywords
        super().__init__(arg, space, mode)

    @property
    def base(self):
        return Filter

    @staticmethod
    def _subspace_entry(j, space, basis, mode):
        """F(j,m) = δ(j,m)"""
        if j == mode:
            return 1
        else:
            return 0


@prefix('d')
@parseable('differentiate', 'diff', 'd')
def differentiate(arg, *spaces, **space_kw):
    # Parse space/order keywords into space list
    for space, order in space_kw.items():
        spaces += (space,) * order
    # Identify domain
    domain = unify_attributes((arg,)+spaces, 'domain', require=False)
    # Apply iteratively
    for space in spaces:
        space = domain.get_space_object(space)
        arg = Differentiate(arg, space)
    return arg


class Differentiate(LinearSubspaceOperator, metaclass=MultiClass):
    """
    Differentiation along one dimension.

    Parameters
    ----------
    operand : number or Operand object
    space : Space object

    """

    def __str__(self):
        return 'd{!s}({!s})'.format(self.space.name, self.operand)

    @classmethod
    def _check_args(cls, operand, space, out=None):
        # Dispatch by operand basis
        if isinstance(operand, Operand):
            if isinstance(operand.get_basis(space), cls.input_basis_type):
                return True
        return False

    def _expand_multiply(self, operand, vars):
        """Expand over multiplication."""
        args = operand.args
        # Apply product rule to factors
        partial_diff = lambda i: np.prod([self.new_operand(arg) if i==j else arg for j,arg in enumerate(args)])
        return sum((partial_diff(i) for i in range(len(args))))

    @property
    def base(self):
        return Differentiate


class DifferentiateConstant(Differentiate):
    """Constant differentiation."""

    @classmethod
    def _check_args(cls, operand, space, out=None):
        # Dispatch for numbers of constant bases
        if isinstance(operand, Number):
            return True
        if isinstance(operand, Operand):
            if operand.get_basis(space) is None:
                return True
        return False

    def __new__(cls, operand, space, out=None):
        return 0


@prefix('H')
@parseable('hilbert_transform', 'hilbert', 'H')
def hilbert_transform(arg, *spaces, **space_kw):
    # Parse space/order keywords into space list
    for space, order in space_kw.items():
        spaces += (space,) * order
    # Identify domain
    domain = unify_attributes((arg,)+spaces, 'domain', require=False)
    # Apply iteratively
    for space in spaces:
        space = domain.get_space_object(space)
        arg = HilbertTransform(arg, space)
    return arg


class HilbertTransform(LinearSubspaceOperator, metaclass=MultiClass):
    """
    Hilbert transform along one dimension.

    Parameters
    ----------
    operand : number or Operand object
    space : Space object

    """

    @classmethod
    def _check_args(cls, operand, space, out=None):
        # Dispatch by operand basis
        if isinstance(operand, Operand):
            if isinstance(operand.get_basis(space), cls.input_basis_type):
                return True
        return False

    @property
    def base(self):
        return HilbertTransform


class HilbertTransformConstant(HilbertTransform):
    """Constant Hilbert transform."""

    @classmethod
    def _check_args(cls, operand, space, out=None):
        # Dispatch for numbers of constant bases
        if isinstance(operand, Number):
            return True
        if isinstance(operand, Operand):
            if operand.get_basis(space) is None:
                return True
        return False

    def __new__(cls, operand, space, out=None):
        return 0


def convert(arg, bases):
    # Drop Nones
    bases = [b for b in bases if b is not None]
    # if not bases:
    #     return arg
    # # Cast to operand
    # domain = unify_attributes(bases, 'domain', require=False)
    # arg = Field.cast(arg, domain=domain)

    # Apply iteratively
    for basis in bases:
        arg = Convert(arg, basis.space, basis)
    return arg


class Convert(LinearSubspaceOperator, metaclass=MultiClass):
    """
    Convert bases along one dimension.

    Parameters
    ----------
    operand : Operand object
    output_basis : Basis object

    """

    # @classmethod
    # def _preprocess_args(cls, operand, space, output_basis, out=None):
    #     operand = Cast(operand, space.domain)
    #     return (operand, space, output_basis), {'out': out}

    @classmethod
    def _check_args(cls, operand, space, output_basis, out=None):
        # Dispatch by operand and output basis
        # Require same space, different bases, and correct types
        if isinstance(operand, Operand):
            input_basis = operand.get_basis(space)
            if input_basis == output_basis:
                return False
            if not isinstance(input_basis, cls.input_basis_type):
                return False
            if not isinstance(output_basis, cls.output_basis_type):
                return False
            return True
        return False

    def __str__(self):
        return str(self.operand)

    @property
    def base(self):
        return Convert

    def output_basis(self, space, input_basis):
        """Determine output basis."""
        return self.args[2]

    def split(self, *vars):
        """Split into expressions containing and not containing specified operands/operators."""
        # Split operand, skipping conversion
        return self.operand.split(*vars)

    def replace(self, old, new):
        """Replace specified operand/operator."""
        # Replace operand, skipping conversion
        return self.operand.replace(old, new)

    def sym_diff(self, var):
        """Symbolically differentiate with respect to specified operand."""
        # Differentiate operand, skipping conversion
        return self.operand.sym_diff(var)

    def expand(self, *vars):
        """Expand expression over specified variables."""
        # Expand operand, skipping conversion
        return self.operand.expand(*vars)

    # def simplify(self, *vars):
    #     """Simplify expression, except subtrees containing specified variables."""
    #     # Simplify operand, skipping conversion
    #     return self.operand.simplify(*vars)


class ConvertSame(Convert):
    """Identity conversion."""

    @classmethod
    def _check_args(cls, operand, space, output_basis, out=None):
        output_space = output_basis.space
        # Dispatch by operand and output basis
        if isinstance(operand, Operand):
            if output_basis in operand.bases:
                return True
        return False

    def __new__(cls, operand, space, output_basis, out=None):
        return operand


class ConvertConstant(Convert):
    """Constant conversion."""

    separable = True
    bands = [0]

    @classmethod
    def _check_args(cls, operand, space, output_basis, out=None):
        if output_basis.const is not None:
            if isinstance(operand, Number):
                return True
            if isinstance(operand, Operand):
                input_basis = operand.get_basis(space)
                if input_basis is None:
                    return True
        return False

    @staticmethod
    def _subspace_matrix(space, input_basis, output_basis):
        dtype = space.domain.dtype
        N = space.coeff_size
        # Reweight by constant-mode amplitude
        M = sparse.lil_matrix((N, 1), dtype=dtype)
        M[0,0] = 1 / output_basis.const
        return M.tocsr()

    def check_conditions(self):
        """Check that arguments are in a proper layout."""
        # No conditions
        return True

    def enforce_conditions(self):
        """Require arguments to be in a proper layout."""
        # No conditions
        pass

    def operate(self, out):
        """Perform operation."""
        operand = self.operand
        axis = self.axis
        output_basis = self.args[2]
        # Set output layout
        out.set_layout(operand.layout)
        # Broadcast constant in grid space
        if operand.layout.grid_space[axis]:
            np.copyto(out.data, operand.data)
        # Set constant mode in coefficient space
        else:
            out.data.fill(0)
            mask = out.local_elements()[axis] == 0
            out.data[axindex(axis, mask)] = operand.data / output_basis.const

