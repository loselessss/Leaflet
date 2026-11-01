"""Keep MuPDF RGB samples alive until a display consumer copies them once."""


class RasterBuffer:
    """A synchronous borrow with a strong owner; never persist the raw view alone.

    Pixmap.samples_mv does not own its pixels. Keeping the pixmap here makes the
    view valid even if the source document/display-list cache is closed first.
    """

    __slots__ = ('_pixmap',)

    def __init__(self, pixmap):
        if pixmap.n != 3 or pixmap.alpha:
            raise ValueError('display buffer must contain opaque RGB pixels')
        self._pixmap = pixmap

    @property
    def geometry(self):
        pix = self._pixmap
        return pix.width, pix.height, pix.stride

    @property
    def view(self):
        return self._pixmap.samples_mv
