//! Pack existing Python path tuples into the renderer's 28-byte command ABI.
//! No renderer handles, pointer casts, or unsafe buffer access are needed here.
use pyo3::exceptions::{PyOverflowError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyTuple};

const COMMAND_BYTES: usize = 28;

#[pyfunction]
fn pack_path<'py>(py: Python<'py>, commands: &Bound<'py, PyTuple>) -> PyResult<Bound<'py, PyByteArray>> {
    let count = commands.len();
    if count == 0 {
        return Err(PyValueError::new_err("Direct2D path cannot be empty"));
    }
    if count > u32::MAX as usize {
        return Err(PyOverflowError::new_err("too many Direct2D path commands"));
    }
    let size = count.checked_mul(COMMAND_BYTES)
        .ok_or_else(|| PyOverflowError::new_err("Direct2D path size overflow"))?;
    PyByteArray::new_with(py, size, |buffer| {
        for (command, output) in commands.iter().zip(buffer.chunks_exact_mut(COMMAND_BYTES)) {
            let command = command.cast::<PyTuple>()?;
            if command.is_empty() {
                return Err(PyValueError::new_err("invalid Direct2D path command"));
            }
            let name = command.get_item(0)?;
            let (kind, coordinates): (u32, usize) = match name.extract::<&str>()? {
                "move" => (1, 2),
                "line" => (2, 2),
                "cubic" => (3, 6),
                "close" => (4, 0),
                _ => return Err(PyValueError::new_err("invalid Direct2D path command")),
            };
            if command.len() != coordinates + 1 {
                return Err(PyValueError::new_err("invalid Direct2D path command"));
            }
            output[..4].copy_from_slice(&kind.to_le_bytes());
            for index in 0..coordinates {
                // Match Python float(value) followed by ctypes.c_float rounding.
                let number = command.get_item(index + 1)?.extract::<f64>()? as f32;
                let offset = 4 + index * 4;
                output[offset..offset + 4].copy_from_slice(&number.to_le_bytes());
            }
        }
        Ok(())
    })
}

#[pymodule]
fn _path_packer(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("COMMAND_BYTES", COMMAND_BYTES)?;
    module.add_function(wrap_pyfunction!(pack_path, module)?)?;
    Ok(())
}
