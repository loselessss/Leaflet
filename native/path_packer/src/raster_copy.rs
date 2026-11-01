//! Copy borrowed SDK RGB pixels into Qt-owned storage, without Python bytes.
use pyo3::buffer::PyBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

const LIMIT: usize = 256 * 1024 * 1024;

#[pyfunction]
pub fn copy_rgb_rows(
    source: &Bound<'_, PyAny>,
    target: &Bound<'_, PyAny>,
    width: usize,
    height: usize,
    source_stride: usize,
    target_stride: usize,
) -> PyResult<()> {
    let invalid = || PyValueError::new_err("invalid RGB display buffers");
    let row = width.checked_mul(3).ok_or_else(invalid)?;
    let source_size = source_stride.checked_mul(height).ok_or_else(invalid)?;
    let target_size = target_stride.checked_mul(height).ok_or_else(invalid)?;
    if width == 0 || height == 0 || source_stride < row || target_stride < row
        || source_size > LIMIT || target_size > LIMIT
    {
        return Err(invalid());
    }
    let source = PyBuffer::<u8>::get(source)?;
    let target = PyBuffer::<u8>::get(target)?;
    if source.dimensions() != 1 || target.dimensions() != 1
        || !source.is_c_contiguous() || !target.is_c_contiguous()
        || target.readonly() || source.len_bytes() < source_size
        || target.len_bytes() < target_size
    {
        return Err(invalid());
    }
    let start = source.buf_ptr() as usize;
    let end = start.checked_add(source_size).ok_or_else(invalid)?;
    let output_start = target.buf_ptr() as usize;
    let output_end = output_start.checked_add(target_size).ok_or_else(invalid)?;
    if start < output_end && output_start < end {
        return Err(PyValueError::new_err("RGB display buffers must not overlap"));
    }
    // Hold both buffer exports and the GIL throughout this synchronous copy.
    // The caller retains the SDK pixmap and a detached, writable Qt image;
    // neither object may be mutated concurrently. All ranges are checked above.
    unsafe {
        let input = source.buf_ptr().cast::<u8>();
        let output = target.buf_ptr().cast::<u8>();
        if source_stride == row && target_stride == row {
            std::ptr::copy_nonoverlapping(input, output, source_size);
        } else {
            for y in 0..height {
                let destination = output.add(y * target_stride);
                std::ptr::copy_nonoverlapping(input.add(y * source_stride), destination, row);
                std::ptr::write_bytes(destination.add(row), 0, target_stride - row);
            }
        }
    }
    Ok(())
}
