"""
Classes for manipulating pencils.

"""

import numpy as np
from scipy import sparse

from ..tools.array import zeros_with_pattern
from ..tools.array import expand_pattern


class PencilSet:
    """
    Pencil system with adjascent memory for efficient computations.

    Attributes
    ----------
    data : ndarray
        Contiguous array for system-wide coefficient data concatenated along
        last axis.
    pencils : list of pencil objects
        Individual pencils

    """

    def __init__(self, domain, n_fields):

        # Extend coefficient data shape for system-wide data set
        shape = np.copy(domain.distributor.coeff_layout.shape)
        self.stride = shape[-1]
        shape[-1] *= n_fields

        # Allocate data
        dtype = domain.distributor.coeff_layout.dtype
        self.data = np.zeros(shape, dtype=dtype)

        # Build pencils
        self.pencils = []
        slice_list, dtrans_list = self._construct_pencil_info(domain)
        for s, d in zip(slice_list, dtrans_list):
            pencil = Pencil(self.data, s, d)
            self.pencils.append(pencil)

    def get_system(self, system):
        """Copy fields into contiguous pencil buffer."""

        for i, field in enumerate(system.fields.values()):
            start = i
            stride = system.n_fields

            field.require_coeff_space()
            np.copyto(self.data[..., start::stride], field.data)

    def set_system(self, system):
        """Extract fields from contiguous pencil buffer."""

        for i, field in enumerate(system.fields.values()):
            start = i
            stride = system.n_fields

            field.layout = field.domain.distributor.coeff_layout
            np.copyto(field.data, self.data[..., start::stride])

    def _construct_pencil_info(self, domain):
        """Construct slice and dtrans lists for each pencil in set."""

        # Get transverse indeces in fastest sequence
        index_list = []
        if domain.dim == 1:
            index_list.append([])
        else:
            trans_shape = self.data.shape[:-1]
            div = np.arange(np.prod(trans_shape))
            for s in reversed(trans_shape):
                div, mod = divmod(div, s)
                index_list.append(mod)
            index_list = list(zip(*reversed(index_list)))

        # Construct corresponding slice and dtrans lists
        slice_list = []
        dtrans_list = []
        start = domain.distributor.coeff_layout.start
        for pencil_index in index_list:
            pencil_slices = []
            pencil_dtrans = []
            for n, b in enumerate(domain.bases[:-1]):
                i = pencil_index[n]
                pencil_slices.append(slice(i, i+1))
                pencil_dtrans.append(b.trans_diff(start[n]+i))
            # Add empty slice for last dimension
            pencil_slices.append(slice(None))
            slice_list.append(pencil_slices)
            dtrans_list.append(pencil_dtrans)

        return slice_list, dtrans_list


class Pencil:
    """
    Pencil holding problem matrices for a given transverse wavevector.

    Parameters
    ----------
    set_data : ndarray
        Array of pencil set data
    slice : list of slice objects
        Slices for retrieving pencil from set data
    d_trans :  list of floats
        Perpendicular differentiation constants

    Attributes
    ----------
    data : ndarray
        View of corresponding data in pencil set

    """

    def __init__(self, set_data, slice, d_trans):

        # Initial attributes
        self.set_data = set_data
        self.slice = slice
        self.d_trans = d_trans
        self.data = set_data[slice].squeeze()

    def build_matrices(self, problem, basis):
        """Construct PDE matrices from problem and basis matrices."""

        # Size
        size = problem.size * basis.coeff_size
        dtype = basis.coeff_dtype
        D = self.d_trans

        # Problem matrices
        ML = problem.ML(self.d_trans)
        MR = problem.MR(self.d_trans)
        MI = problem.MI(self.d_trans)
        LL = problem.LL(self.d_trans)
        LR = problem.LR(self.d_trans)
        LI = problem.LI(self.d_trans)

        # Allocate PDE matrices
        M = sparse.csr_matrix((size, size), dtype=dtype)
        L = sparse.csr_matrix((size, size), dtype=dtype)

        # Add terms to PDE matrices
        for i in range(problem.order):
            Pre_i = basis.Pre * basis.Mult(i)
            Diff_i = basis.Pre * basis.Mult(i) * basis.Diff

            M = M + sparse.kron(Pre_i, problem.M0[i](D), format='csr')
            M = M + sparse.kron(Diff_i, problem.M1[i](D), format='csr')
            L = L + sparse.kron(Pre_i, problem.L0[i](D), format='csr')
            L = L + sparse.kron(Diff_i, problem.L1[i](D), format='csr')

        # Allocate boundary condition matrices
        Mb = sparse.csr_matrix((size, size), dtype=dtype)
        Lb = sparse.csr_matrix((size, size), dtype=dtype)

        # Add terms to boundary condition matrices
        if np.any(ML):
            Mb = Mb + sparse.kron(basis.Left, ML, format='csr')
        if np.any(MR):
            Mb = Mb + sparse.kron(basis.Right, MR, format='csr')
        if np.any(MI):
            Mb = Mb + sparse.kron(basis.Int, MI, format='csr')
        if np.any(LL):
            Lb = Lb + sparse.kron(basis.Left, LL, format='csr')
        if np.any(LR):
            Lb = Lb + sparse.kron(basis.Right, LR, format='csr')
        if np.any(LI):
            Lb = Lb + sparse.kron(basis.Int, LI, format='csr')

        # Get set of boundary condition rows
        Mb_rows = Mb.nonzero()[0]
        Lb_rows = Lb.nonzero()[0]
        rows = set(Mb_rows).union(set(Lb_rows))

        # Clear boundary condition rows in PDE matrices
        clear_bc = sparse.eye(size, dtype=dtype, format='dok')
        for i in rows:
            clear_bc[i, i] = 0.

        clear_bc = clear_bc.tocsr()
        M = M.tocsr()
        L = L.tocsr()

        M = clear_bc * M
        L = clear_bc * L

        # Add boundary condition terms to PDE matrices
        M = M + Mb
        L = L + Lb

        # Store with expanded sparsity for fast combination during integration
        self.LHS = zeros_with_pattern(M, L).tocsr()
        self.M = expand_pattern(M, self.LHS).tocsr()
        self.L = expand_pattern(L, self.LHS).tocsr()

        # Reference nonlinear expressions
        self.F = problem.F
        self.F_eval = sparse.kron(basis.Pre, np.eye(problem.size))
        b = np.kron(basis.bc_vector[:,0], problem.b(D))
        self.bc_f = [b[r] for r in rows]
        self.bc_rows = list(rows)
        self.parameters = problem.parameters

        # UPGRADE: Caste boundary conditions as functionals on operator trees
        # self.BL = problem.BL
        # self.BR = problem.BR
        # self.BI = problem.BI
        # self.BL_eval = sparse.kron(np.eye(problem.size), basis.Left)
        # self.BR_eval = sparse.kron(np.eye(problem.size), basis.Right)
        # self.BI_eval = sparse.kron(np.eye(problem.size), basis.Int)

