from image_registration.fft_tools import correlate2d,fast_ffts,dftups,upsample_image,zoom
import warnings
import numpy as np

__all__ = ['chi2_shift','chi2n_map']

def chi2_shift(im1, im2, err=None, upsample_factor='auto', boundary='wrap',
        nthreads=1, use_numpy_fft=False, zeromean=False, nfitted=2,
        verbose=False, return_error=True, return_chi2array=False,
        max_auto_size=512, return_terms=False, max_nsig=1.1):
    """
    Find the offsets between image 1 and image 2 using the DFT upsampling method
    (http://www.mathworks.com/matlabcentral/fileexchange/18401-efficient-subpixel-image-registration-by-cross-correlation/content/html/efficient_subpixel_registration.html)
    combined with :math:`\chi^2` to measure the errors on the fit

    Equation 1 gives the :math:`\chi^2` value as a function of shift, where Y
    is the model as a function of shift:

    .. math::
            \chi^2(dx,dy) & = & \Sigma_{ij} \\frac{(X_{ij}-Y_{ij}(dx,dy))^2}{\sigma_{ij}^2} \\\\
                          
    ..                         
          & = & \Sigma_{ij} \left[ X_{ij}^2/\sigma_{ij}^2 - 2X_{ij}Y_{ij}(dx,dy)/\sigma_{ij}^2 + Y_{ij}(dx,dy)^2/\sigma_{ij}^2 \\right]  \\\\

    Equation 2-4:

    .. math::
            Term~1: f(dx,dy) & = & \Sigma_{ij} \\frac{X_{ij}^2}{\sigma_{ij}^2}  \\\\
                    f(dx,dy) & = & f(0,0) ,  \\forall dx,dy \\\\
            Term~2: g(dx,dy) & = & -2 \Sigma_{ij} \\frac{X_{ij}Y_{ij}(dx,dy)}{\sigma_{ij}^2} = -2 \Sigma_{ij} \left(\\frac{X_{ij}}{\sigma_{ij}^2}\\right) Y_{ij}(dx,dy) \\\\
            Term~3: h(dx,dy) & = & \Sigma_{ij} \\frac{Y_{ij}(dx,dy)^2}{\sigma_{ij}^2} = \Sigma_{ij} \left(\\frac{1}{\sigma_{ij}^2}\\right) Y^2_{ij}(dx,dy)

    The cross-correlation can be computed with fourier transforms, and is defined

    .. math::
            CC_{m,n}(x,y) = \Sigma_{ij} x^*_{ij} y_{(n+i)(m+j)}

    which can then be applied to our problem, noting that the cross-correlation
    has the same form as term 2 and 3 in :math:`\chi^2` (term 1 is a constant,
    with no dependence on the shift)

    .. math::
            Term~2: & CC(X/\sigma^2,Y)[dx,dy] & = & \Sigma_{ij} \left(\\frac{X_{ij}}{\sigma_{ij}^2}\\right)^* Y_{ij}(dx,dy) \\\\
            Term~3: & CC(\sigma^{-2},Y^2)[dx,dy] & = & \Sigma_{ij} \left(\\frac{1}{\sigma_{ij}^2}\\right)^* Y^2_{ij}(dx,dy) \\\\

    Technically, only terms 2 and 3 has any effect on the resulting image,
    since term 1 is the same for all shifts, and the quantity of interest is
    :math:`\Delta \chi^2` when determining the best-fit shift and error.
    
    
    Parameters
    ----------
    im1 : np.ndarray
    im2 : np.ndarray
        The images to register. 
    err : np.ndarray
        Per-pixel error in image 2
    boundary : 'wrap','constant','reflect','nearest'
        Option to pass to map_coordinates for determining what to do with
        shifts outside of the boundaries.  
    upsample_factor : int or 'auto'
        upsampling factor; governs accuracy of fit (1/usfac is best accuracy)
        (can be "automatically" determined based on chi^2 error)
    return_error : bool
        Returns the "fit error" (1-sigma in x and y) based on the delta-chi2
        values
    return_chi2_array : bool
        Returns the x and y shifts and the chi2 as a function of those shifts
        in addition to other returned parameters.  i.e., the last return from
        this function will be a tuple (x, y, chi2)
    zeromean : bool
        Subtract the mean from the images before cross-correlating?  If no, you
        may get a 0,0 offset because the DC levels are strongly correlated.
    verbose : bool
        Print error message if upsampling factor is inadequate to measure errors
    use_numpy_fft : bool
        Force use numpy's fft over fftw?  (only matters if you have fftw
        installed)
    nthreads : bool
        Number of threads to use for fft (only matters if you have fftw
        installed)
    nfitted : int
        number of degrees of freedom in the fit (used for chi^2 computations).
        Should probably always be 2.
    max_auto_size : int
        Maximum zoom image size to create when using auto-upsampling


    Returns
    -------
    dx,dy : float,float
        Measures the amount im2 is offset from im1 (i.e., shift im2 by -1 *
        these #'s to match im1)
    errx,erry : float,float
        optional, error in x and y directions
    xvals,yvals,chi2n_upsampled : ndarray,ndarray,ndarray,
        not entirely sure what those first two are

        .. todo::
            CHECK THIS 

    Examples
    --------
    >>> # Create a 2d array
    >>> image = np.random.randn(50,55)
    >>> # shift it in both directions
    >>> shifted = np.roll(np.roll(image,12,0),5,1)
    >>> # determine shift
    >>> import image_registration
    >>> dx,dy,edx,edy = image_registration.chi2_shift(image, shifted, upsample_factor='auto')
    >>> # Check that the shift is correct
    >>> print "dx - fitted dx = ",dx-5," error: ",edx
    >>> print "dy - fitted dy = ",dy-12," error: ",edy
    >>> # that example was boring; instead let's do one with a non-int shift
    >>> shifted2 = image_registration.fft_tools.shift(image,3.665,-4.25)
    >>> dx2,dy2,edx2,edy2 = image_registration.chi2_shift(image, shifted2, upsample_factor='auto')
    >>> print "dx - fitted dx = ",dx2-3.665," error: ",edx2
    >>> print "dy - fitted dy = ",dy2-(-4.25)," error: ",edy2
    
    .. todo:: understand numerical error in fft-shifted version

    """
    chi2,term1,term2,term3 = chi2n_map(im1, im2, err, boundary=boundary,
            nthreads=nthreads, zeromean=zeromean, use_numpy_fft=use_numpy_fft,
            return_all=True, reduced=False)
    ymax, xmax = np.unravel_index(chi2.argmin(), chi2.shape)

    # needed for ffts
    im1 = np.nan_to_num(im1)
    im2 = np.nan_to_num(im2)

    ylen,xlen = im1.shape
    xcen = xlen/2-(1-xlen%2) 
    ycen = ylen/2-(1-ylen%2) 

    # original shift calculation
    yshift = ymax-ycen # shift im2 by these numbers to get im1
    xshift = xmax-xcen

    if verbose:
        print "Coarse xmax/ymax = %i,%i, for offset %f,%f" % (xmax,ymax,xshift,yshift)

    # below is sub-pixel zoom-in stuff

    # find delta-chi^2 limiting values for varying DOFs
    try:
        import scipy.stats
        # 1,2,3-sigma delta-chi2 levels
        m1 = scipy.stats.chi2.ppf( 1-scipy.stats.norm.sf(1)*2, nfitted )
        m2 = scipy.stats.chi2.ppf( 1-scipy.stats.norm.sf(2)*2, nfitted )
        m3 = scipy.stats.chi2.ppf( 1-scipy.stats.norm.sf(3)*2, nfitted )
        m_auto = scipy.stats.chi2.ppf( 1-scipy.stats.norm.sf(max_nsig)*2, nfitted )
    except ImportError:
        # assume m=2 (2 degrees of freedom)
        m1 = 2.2957489288986364
        m2 = 6.1800743062441734 
        m3 = 11.829158081900793
        m_auto = 2.6088233328527037 # slightly >1 sigma

    # biggest scale = where chi^2/n ~ 9 or 11.8 for M=2?
    if upsample_factor=='auto':
        # deltachi2 is not reduced deltachi2
        deltachi2_lowres = (chi2 - chi2.min())
        if verbose:
            print "Minimum chi2: %g   Max delta-chi2 (lowres): %g  Min delta-chi2 (lowres): %g" % (chi2.min(),deltachi2_lowres.max(),deltachi2_lowres[deltachi2_lowres>0].min())
        sigmamax_area = deltachi2_lowres<m_auto
        if sigmamax_area.sum() > 1:
            yy,xx = np.indices(sigmamax_area.shape)
            xvals = xx[sigmamax_area]
            yvals = yy[sigmamax_area]
            xvrange = xvals.max()-xvals.min()
            yvrange = yvals.max()-yvals.min()
            size = max(xvrange,yvrange)
        else:
            size = 1
        upsample_factor = max_auto_size/2. / size
        if upsample_factor < 1:
            upsample_factor = 1
        s1 = s2 = max_auto_size
        # zoom factor = s1 / upsample_factor = 2*size
        zoom_factor = 2.*size
        if verbose:
            print "Selected upsample factor %0.1f for image size %i and zoom factor %0.1f (max-sigma range was %i for area %i)" % (upsample_factor, s1, zoom_factor, size, sigmamax_area.sum())
    else:
        s1,s2 = im1.shape

        zoom_factor = s1/upsample_factor
        if zoom_factor <= 1:
            zoom_factor = 2
            s1 = zoom_factor*upsample_factor
            s2 = zoom_factor*upsample_factor

    # import fft's
    fftn,ifftn = fast_ffts.get_ffts(nthreads=nthreads, use_numpy_fft=use_numpy_fft)

    # determine the amount to shift by?
    dftshift = np.trunc(np.ceil(upsample_factor*zoom_factor)/2); #% Center of output array at dftshift+1

    if err is not None and not np.isscalar(err):
        err = np.nan_to_num(err)
        # prevent divide-by-zero errors
        # because err is always squared, negative errors are "ok" in a weird sense
        if verbose:
            print "Found %i points where err==0" % ((err==0).sum())
        im2[err==0] = 0
        im1[err==0] = 0
        err[err==0] = 1
        term3_ups = dftups(fftn(im1**2)*np.conj(fftn(1./err**2)), s1, s2, usfac=upsample_factor,
                roff=dftshift-yshift*upsample_factor,
                coff=dftshift-xshift*upsample_factor) / (im1.size) #*upsample_factor**2)
    else:
        if err is None:
            err = 1.
        # 'upsampled' term3 is same as term3, because it's scalar
        term3_ups = term3

    if verbose > 1:
        print "dftshift: %f  s1: %f  s2: %f  upsample_factor: %f roff: %f  coff: %f xshift: %f yshift: %f" % (dftshift,
                s1,s2,upsample_factor,
                dftshift-yshift*upsample_factor,
                dftshift-xshift*upsample_factor,
                xshift,
                yshift)

    # pilfered from dftregistration (hence the % comments)
    term2_ups = -2 * dftups(fftn(im2/err**2)*np.conj(fftn(im1)), s1, s2, usfac=upsample_factor,
            roff=dftshift-yshift*upsample_factor,
            coff=dftshift-xshift*upsample_factor) / (im1.size) #*upsample_factor**2)
    # why do we have to divide by im1.size?  because the fourier scaling theorem is 1/a * FT(f(t/a))

    # old and wrong chi2n_ups = (ac1peak/err2sum-2*np.abs(xc_ups)/np.abs(err_ups)+ac2peak/err2sum)#*(xc.size-nfitted)
    chi2_ups = term1 + term2_ups + term3_ups

    chi2_ups = dftups(fftn(chi2), s1, s2, usfac=upsample_factor,
            roff=dftshift-yshift*upsample_factor,
            coff=dftshift-xshift*upsample_factor) / (chi2.size) 

    # deltachi2 is not reduced deltachi2
    deltachi2_ups = (chi2_ups - chi2_ups.min())
    if verbose:
        print "Minimum chi2_ups: %g   Max delta-chi2 (highres): %g  Min delta-chi2 (highres): %g" % (chi2_ups.min(),deltachi2_ups.max(),deltachi2_ups[deltachi2_ups>0].min())
        if verbose > 1:
            if hasattr(term3_ups,'len'):
                print "term3_ups has shape ",term3_ups.shape," term2: ",term2_ups.shape," term1=",term1
            else:
                print "term2 shape: ",term2.shape," term1: ",term1," term3: ",term3_ups
    # THE UPSAMPLED BEST-FIT HAS BEEN FOUND

    # BELOW IS TO COMPUTE THE ERROR

    yy,xx = np.indices([s1,s2])
    xshifts_corrections = (xx-dftshift)/upsample_factor
    yshifts_corrections = (yy-dftshift)/upsample_factor

    # need to determine how many pixels are in the 1-sigma region
    sigma1_area = deltachi2_ups<m1
    # optional...?
    #sigma2_area = deltachi2<m2
    #x_sigma2 = xshifts_corrections[sigma2_area]
    #y_sigma2 = yshifts_corrections[sigma2_area]
    #sigma3_area = deltachi2<m3
    #x_sigma3 = xshifts_corrections[sigma3_area]
    #y_sigma3 = yshifts_corrections[sigma3_area]

    # upsampled maximum - correction
    upsymax,upsxmax = np.unravel_index(chi2_ups.argmin(), chi2_ups.shape)

    if sigma1_area.sum() <= 1:
        if verbose and upsample_factor == 'auto':
            print "Cannot estimate errors: need higher upsample factor.  Sigmamax_area=%i" % (sigmamax_area.sum())
        else:
            print "Cannot estimate errors: need higher upsample factor."
        errx_low = erry_low = errx_high = erry_high = 1./upsample_factor
    else: # compute 1-sigma errors
        x_sigma1 = xshifts_corrections[sigma1_area]
        y_sigma1 = yshifts_corrections[sigma1_area]

        errx_low = (upsxmax-dftshift)/upsample_factor - x_sigma1.min()
        errx_high = x_sigma1.max() - (upsxmax-dftshift)/upsample_factor
        erry_low = (upsymax-dftshift)/upsample_factor - y_sigma1.min()
        erry_high = y_sigma1.max() - (upsymax-dftshift)/upsample_factor
        if verbose:
            print "Found %i pixels within the 1-sigma region. xmin,ymin: %f,%f xmax,ymax: %g,%g" % (sigma1_area.sum(),x_sigma1.min(),y_sigma1.min(),x_sigma1.max(),y_sigma1.max())
        #from pylab import *
        #clf(); imshow(deltachi2); colorbar(); contour(sigma1_area,levels=[0.5],colors=['w'])
        #import pdb; pdb.set_trace()

    yshift_corr = yshift+(upsymax-dftshift)/float(upsample_factor)
    xshift_corr = xshift+(upsxmax-dftshift)/float(upsample_factor)
    if verbose > 1:
        #print ymax,xmax
        #print upsymax, upsxmax
        #print upsymax-dftshift, upsxmax-dftshift
        print "Correction: ",(upsymax-dftshift)/float(upsample_factor), (upsxmax-dftshift)/float(upsample_factor)
        if 'x_sigma1'  in locals():
            print "Chi2 1sig bounds:", x_sigma1.min(), x_sigma1.max(), y_sigma1.min(), y_sigma1.max()
            print errx_low,errx_high,erry_low,erry_high
            print "%0.3f +%0.3f -%0.3f   %0.3f +%0.3f -%0.3f" % (yshift_corr, erry_high, erry_low, xshift_corr, errx_high, errx_low)
        #print ymax-ycen+upsymax/float(upsample_factor), xmax-xcen+upsxmax/float(upsample_factor)
        #print (upsymax-s1/2)/upsample_factor, (upsxmax-s2/2)/upsample_factor

    shift_xvals = xshifts_corrections+xshift
    shift_yvals = yshifts_corrections+yshift

    returns = [-xshift_corr,-yshift_corr]
    if return_error:
        returns.append( (errx_low+errx_high)/2. )
        returns.append( (erry_low+erry_high)/2. )
    if return_chi2array:
        returns.append((shift_xvals,shift_yvals,chi2_ups))
    if return_terms:
        returns.append((term1,term2_ups,term3_ups))

    return returns

def chi2map_to_errors(chi2map, zoomfactor=1., nsigma=1, nfitted=2):
    """
    Derive errors from a chi^2 map

    Parameters
    ----------
    chi2map : np.ndarray
        A chi^2 map *with a minimum in bounds* and with delta-chi^2 <
        chi2stat(nsigma) in bounds
    zoomfactor : float
        The amount the chi2 map has been zoomed (i.e., the pixel scale, in
        units of small pixels per original pixel)
    nsigma : float
        How many sigma do you want the error bars to be?  Uses scipy.stats to
        invert the chi^2 distribution, or an extrapolated version thereof if
        nsigma>8 (leads to errors in the ppf because of 1-0 floating point
        inaccuracy above that level)
    nfitted : int
        Number of fitted parameters.  In this case, always 2, but you could
        change your chi^2 statistic based on this

    Returns
    -------
    (-ex,+ex,-ey,+ey) where ex/ey are the x and y errors.
    """

    # find delta-chi^2 limiting values for varying DOFs
    try:
        import scipy.stats
        def sigma_to_chi2(x):
            if x < 8:
                return scipy.stats.chi2.ppf( 1-scipy.stats.norm.sf(x)*2, nfitted )
            else: # flop accuracy fails, assume 2 dof
                return 1.59358435 * x**1.80468278
    except ImportError:
        # assume m=2 (2 degrees of freedom)
        sigma_to_chi2 = lambda x: 1.59358435 * x**1.80468278

    yy,xx = (np.indices(chi2map.shape) - np.array(chi2map.shape)[:,np.newaxis,np.newaxis]/2.) / zoomfactor

    xcen = xx.flat[chi2map.argmin()]
    ycen = yy.flat[chi2map.argmin()]

    deltachi2 = chi2map - chi2map.min()
    sigma1_area = deltachi2 < sigma_to_chi2(nsigma)
    x_sigma1 = xx[sigma1_area]
    y_sigma1 = yy[sigma1_area]

    errx_low = xcen - x_sigma1.min()
    errx_high = x_sigma1.max() - xcen
    erry_low = ycen - y_sigma1.min()
    erry_high = y_sigma1.max() - ycen

    return errx_low,errx_high,erry_low,erry_high

def chi2_shift_iterzoom(im1, im2, err=None, upsample_factor='auto',
        boundary='wrap', nthreads=1, use_numpy_fft=False, zeromean=False,
        verbose=False, return_error=True, return_chi2array=False,
        zoom_shape=[10,10], rezoom_shape=[100,100], rezoom_factor=5,
        mindiff=1):
    """
    Find the offsets between image 1 and image 2 using the DFT upsampling method
    (http://www.mathworks.com/matlabcentral/fileexchange/18401-efficient-subpixel-image-registration-by-cross-correlation/content/html/efficient_subpixel_registration.html)
    combined with :math:`\chi^2` to measure the errors on the fit

    A simpler version of :func:`chi2_shift` that only computes the
    :math:`\chi^2` array on the largest scales, then uses a fourier upsampling
    technique to zoom in.
    
    
    Parameters
    ----------
    im1 : np.ndarray
    im2 : np.ndarray
        The images to register. 
    err : np.ndarray
        Per-pixel error in image 2
    boundary : 'wrap','constant','reflect','nearest'
        Option to pass to map_coordinates for determining what to do with
        shifts outside of the boundaries.  
    upsample_factor : int or 'auto'
        upsampling factor; governs accuracy of fit (1/usfac is best accuracy)
        (can be "automatically" determined based on chi^2 error)
    zeromean : bool
        Subtract the mean from the images before cross-correlating?  If no, you
        may get a 0,0 offset because the DC levels are strongly correlated.
    verbose : bool
        Print error message if upsampling factor is inadequate to measure errors
    use_numpy_fft : bool
        Force use numpy's fft over fftw?  (only matters if you have fftw
        installed)
    nthreads : bool
        Number of threads to use for fft (only matters if you have fftw
        installed)
    nfitted : int
        number of degrees of freedom in the fit (used for chi^2 computations).
        Should probably always be 2.
    zoom_shape : [int,int]
        Shape of iterative zoom image
    rezoom_shape : [int,int]
        Shape of the output chi^2 map to use for determining the errors
    rezoom_factor : int
        Amount to zoom above the last zoom factor.  Should be <=
        rezoom_shape/zoom_shape

    Other Parameters
    ----------------
    return_error : bool
        Returns the "fit error" (1-sigma in x and y) based on the delta-chi2
        values
    return_chi2_array : bool
        Returns the x and y shifts and the chi2 as a function of those shifts
        in addition to other returned parameters.  i.e., the last return from
        this function will be a tuple (x, y, chi2)

    Returns
    -------
    dx,dy : float,float
        Measures the amount im2 is offset from im1 (i.e., shift im2 by -1 *
        these #'s to match im1)
    errx,erry : float,float
        optional, error in x and y directions
    xvals,yvals,chi2n_upsampled : ndarray,ndarray,ndarray,
        not entirely sure what those first two are

        .. todo::
            CHECK THIS 

    Examples
    --------
    >>> # Create a 2d array
    >>> image = np.random.randn(50,55)
    >>> # shift it in both directions
    >>> shifted = np.roll(np.roll(image,12,0),5,1)
    >>> # determine shift
    >>> import image_registration
    >>> dx,dy,edx,edy = image_registration.chi2_shift(image, shifted, upsample_factor='auto')
    >>> # Check that the shift is correct
    >>> print "dx - fitted dx = ",dx-5," error: ",edx
    >>> print "dy - fitted dy = ",dy-12," error: ",edy
    >>> # that example was boring; instead let's do one with a non-int shift
    >>> shifted2 = image_registration.fft_tools.shift(image,3.665,-4.25)
    >>> dx2,dy2,edx2,edy2 = image_registration.chi2_shift(image, shifted2, upsample_factor='auto')
    >>> print "dx - fitted dx = ",dx2-3.665," error: ",edx2
    >>> print "dy - fitted dy = ",dy2-(-4.25)," error: ",edy2
    
    .. todo:: understand numerical error in fft-shifted version

    """
    chi2,term1,term2,term3 = chi2n_map(im1, im2, err, boundary=boundary,
            nthreads=nthreads, zeromean=zeromean, use_numpy_fft=use_numpy_fft,
            return_all=True, reduced=False)
    # at this point, the chi2 map contains ALL of the information!

    # below is sub-pixel zoom-in stuff

    chi2zoom, zf, offsets = iterative_min_zoom(chi2, mindiff=mindiff,
            zoomshape=zoom_shape, return_zoomed=True, verbose=verbose)

    chi2_rezoom = zoom.zoomnd(chi2, zf*rezoom_factor, offsets=offsets,
            outshape=rezoom_shape)

    # x and y are swapped (or not?)
    returns = [-off for off in offsets]

    if return_error:
        errx_low,errx_high,erry_low,erry_high = chi2map_to_errors(chi2_rezoom, zf*rezoom_factor)
        returns.append( (errx_low+errx_high)/2. )
        returns.append( (erry_low+erry_high)/2. )
    if return_chi2array:
        yy,xx = (np.indices(chi2_rezoom.shape) - np.array(chi2_rezoom.shape)[:,np.newaxis,np.newaxis]/2.) / (zf*rezoom_factor)
        yy += offsets[1] # somehow they got unswapped?!  
        xx += offsets[0] # maybe the cross-correlation did it?!
        xx *= -1
        yy *= -1
        returns.append((xx,yy,chi2_rezoom))

    return returns

def chi2n_map(im1, im2, err=None, boundary='wrap', nthreads=1,
        zeromean=False, use_numpy_fft=False, return_all=False, reduced=False):
    """
    Parameters
    ----------
    im1 : np.ndarray
    im2 : np.ndarray
        The images to register. 
    err : np.ndarray
        Per-pixel error in image 2
    boundary : 'wrap','constant','reflect','nearest'
        Option to pass to map_coordinates for determining what to do with
        shifts outside of the boundaries.  
    zeromean : bool
        Subtract the mean from the images before cross-correlating?  If no, you
        may get a 0,0 offset because the DC levels are strongly correlated.
    nthreads : bool
        Number of threads to use for fft (only matters if you have fftw
        installed)
    reduced : bool
        Return the reduced :math:`\chi^2` array, or unreduced?
        (assumes 2 degrees of freedom for the fit)

    Returns
    -------
    chi2n : np.ndarray
        the :math:`\chi^2` array
    term1 : float
        Scalar, term 1 in the :math:`\chi^2` equation
    term2 : np.ndarray
        Term 2 in the equation, -2 * cross-correlation(x/sigma^2,y)
    term3 : np.ndarray | float
        If error is an array, returns an array, otherwise is a scalar float
        corresponding to term 3 in the equation
    """

    if not im1.shape == im2.shape:
        raise ValueError("Images must have same shape.")

    if zeromean:
        im1 = im1 - (im1[im1==im1].mean())
        im2 = im2 - (im2[im2==im2].mean())

    im1 = np.nan_to_num(im1)
    im2 = np.nan_to_num(im2)

    if err is not None and not np.isscalar(err):
        err = np.nan_to_num(err)

        # to avoid divide-by-zero errors
        # err is always squared, so negative errors are "sort of ok"
        im2[err==0] = 0
        im1[err==0] = 0
        err[err==0] = 1 

        # we want im1 first, because it's first down below
        term3 = correlate2d(im1**2, 1./err**2, boundary=boundary,
                nthreads=nthreads, use_numpy_fft=use_numpy_fft)

    else: # scalar error is OK
        if err is None:
            err = 1. 
        term3 = ((im1**2/err**2)).sum()

    # term 1 and 2 don't rely on err being an array
    term1 = ((im2**2/err**2)).sum()

    # ORDER MATTERS! cross-correlate im1,im2 not im2,im1
    term2 = -2 * correlate2d(im1,im2/err**2, boundary=boundary,
            nthreads=nthreads, use_numpy_fft=use_numpy_fft)

    chi2 = term1 + term2 + term3

    if reduced:
        # 2 degrees of freedom
        chi2 /= im2.size-2.

    if return_all:
        return chi2,term1,term2,term3
    else:
        return chi2

def iterative_min_zoom(image, mindiff=1., zoomshape=[10,10],
        return_zoomed=False, zoomstep=2, verbose=False):
    """
    Iteratively zoom in on the *minimum* position in an image until the
    delta-peak value is below `mindiff`

    Parameters
    ----------
    image : np.ndarray
        Two-dimensional image with a *minimum* to zoom in on
    mindiff : float
        Minimum difference that must be present in image before zooming is done
    zoomshape : [int,int]
        Shape of the "mini" image to create.  Smaller is faster, but a bit less
        accurate.  [10,10] seems to work well in preliminary tests (though unit
        tests have not been written)
    return_zoomed : bool
        Return the zoomed image in addition to the measured offset?
    zoomstep : int
        Amount to increase the zoom factor by on each iteration.  Probably best to
        stick with small integers (2-5ish).
    verbose : bool
        Print out information about zoom factor, offset at each iteration

    Returns
    -------
    The y,x offsets (following numpy convention) of the center position of the
    original image.  If `return_zoomed`, returns (zoomed_image, zoom_factor,
    offsets) because you can't interpret the zoomed image without the zoom
    factor.
    """

    image_zoom = image

    zf = 1. # "zoom factor" initialized to 1 for the base shift measurement
    offset = np.array([0,0],dtype='float') # center offset
    delta_image = (image_zoom - image_zoom.min())

    # check to make sure the smallest *nonzero* difference > mindiff
    while delta_image[delta_image>0].min() > mindiff:
        minpos = np.unravel_index(image_zoom.argmin(), image_zoom.shape)
        center_shift = (np.array(minpos) - (np.array(image_zoom.shape)-1)/2.) / zf
        offset += center_shift

        zf *= zoomstep

        image_zoom = zoom.zoomnd(image,zf,offsets=offset,outshape=zoomshape)
        delta_image = image_zoom-image_zoom.min()

        # base case: in case you can't do any better...
        # (at this point, you're all the way zoomed)
        if np.all(delta_image == 0):
            if verbose:
                print "Can't zoom any further.  zf=%i" % zf
            break

        if verbose:
            print ("Zoom factor %6i, center_shift = %15g,%15g, offset=%15g,%15g" %
                    (zf, center_shift[0], center_shift[1], offset[0],
                        offset[1]))

    if return_zoomed:
        return image_zoom,zf,offset
    else:
        return offset

def chi2_shift_leastsq(im1, im2, err=None, mode='wrap', maxoff=None, return_error=True,
        guessx=0, guessy=0, use_fft=False, ignore_outside=True, **kwargs):
    """
    Determine the best fit offset using `scipy.ndimage.map_coordinates` to
    shift the offset image.
    *OBSOLETE* It kind of works, but is sensitive to input guess and doesn't reliably
    output errors

    Parameters
    ----------
        im1 : np.ndarray
            First image
        im2 : np.ndarray
            Second image (offset image)
        err : np.ndarray OR float
            Per-pixel error in image 2
        mode : 'wrap','constant','reflect','nearest'
            Option to pass to map_coordinates for determining what to do with
            shifts outside of the boundaries.  
        maxoff : None or int
            If set, crop the data after shifting before determining chi2
            (this is a good thing to use; not using it can result in weirdness
            involving the boundaries)

    """
    #xc = correlate2d(im1,im2, boundary=boundary)
    #ac1peak = (im1**2).sum()
    #ac2peak = (im2**2).sum()
    #chi2 = ac1peak - 2*xc + ac2peak


    if not im1.shape == im2.shape:
        raise ValueError("Images must have same shape.")

    if np.any(np.isnan(im1)):
        im1 = im1.copy()
        im1[im1!=im1] = 0
    if np.any(np.isnan(im2)):
        im2 = im2.copy()
        if hasattr(err,'shape'):
            err[im2!=im2] = np.inf
        im2[im2!=im2] = 0

    im1 = im1-im1.mean()
    im2 = im2-im2.mean()
    if not use_fft:
        yy,xx = np.indices(im1.shape)
    ylen,xlen = im1.shape
    xcen = xlen/2-(1-xlen%2) 
    ycen = ylen/2-(1-ylen%2) 
    import scipy.ndimage,scipy.optimize

    def residuals(p, **kwargs):
        xsh,ysh = p
        if use_fft:
            shifted_img = shift(im2, -ysh, -xsh)
        else:
            shifted_img = scipy.ndimage.map_coordinates(im2, [yy+ysh,xx+xsh], mode=mode, **kwargs)
        if maxoff is not None:
            xslice = slice(xcen-maxoff,xcen+maxoff,None)
            yslice = slice(ycen-maxoff,ycen+maxoff,None)
            # divide by sqrt(number of samples) = sqrt(maxoff**2)
            residuals = np.abs(np.ravel((im1[yslice,xslice]-shifted_img[yslice,xslice])) / maxoff)
        else:
            if ignore_outside:
                outsidex = min([(xlen-2*xsh)/2,xcen])
                outsidey = min([(ylen-2*ysh)/2,xcen])
                xslice = slice(xcen-outsidex,xcen+outsidex,None)
                yslice = slice(ycen-outsidey,ycen+outsidey,None)
                residuals = ( np.abs( np.ravel(
                    (im1[yslice,xslice]-shifted_img[yslice,xslice]))) /
                    (2*outsidex*2*outsidey)**0.5 )
            else:
                xslice = slice(None)
                yslice = slice(None)
                residuals = np.abs(np.ravel((im1-shifted_img))) / im1.size**0.5
        if err is None:
            return residuals
        elif hasattr(err,'shape'):
            if use_fft:
                shifted_err = shift(err, -ysh, -xsh)
            else:
                shifted_err = scipy.ndimage.map_coordinates(err, [yy+ysh,xx+xsh], mode=mode, **kwargs)
            return residuals / shifted_err[yslice,xslice].flat
        else:
            return residuals / err

    bestfit,cov,info,msg,ier = scipy.optimize.leastsq(residuals, [guessx,guessy], full_output=1)
    #bestfit,cov = scipy.optimize.curve_fit(shift, im2, im1, p0=[guessx,guessy], sigma=err)

    chi2n = (residuals(bestfit)**2).sum() / (im1.size-2)

    if bestfit is None or cov is None:
        print bestfit-np.array([guessx,guessy])
        print bestfit
        print cov
        print info
        print msg
        print ier
        if cov is None:
            from numpy.dual import inv
            from numpy.linalg import LinAlgError
            n = 2 # number of free pars
            perm = np.take(np.eye(n),info['ipvt']-1,0)
            r = np.triu(np.transpose(info['fjac'])[:n,:])
            R = np.dot(r, perm)
            try:
                cov = inv(np.dot(np.transpose(R),R))
            except LinAlgError:
                print "Could not compute cov because of linalgerr"
                pass
                
        
    if return_error:
        if cov is None:
            return bestfit[0],bestfit[1],0,0
        else: # based on scipy.optimize.curve_fit, the "correct" covariance is this cov * chi^2/n
            return bestfit[0],bestfit[1],(cov[0,0]*chi2n)**0.5,(cov[1,1]*chi2n)**0.5
    else:
        return bestfit[0],bestfit[1]


