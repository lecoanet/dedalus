
cimport cython

@cython.boundscheck(False)
@cython.wraparound(False)
def product(double [:,::1] data0, double [:,::1] data1, double [:,::1] out):

    cdef int size1 = data0.shape[1]
    cdef int i
    
    for i in range(size1):
        out[0,i] = data0[2,i]*data1[1,i] - data0[1,i]*data1[2,i]
        out[1,i] = data0[0,i]*data1[2,i] - data0[2,i]*data1[0,i]
        out[2,i] = data0[1,i]*data1[0,i] - data0[0,i]*data1[1,i]

