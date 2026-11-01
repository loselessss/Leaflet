// Pack existing Python path tuples into the renderer's 28-byte command ABI.
// No renderer handles, pointer casts, or unsafe buffer access are needed here.
use pyo3::exceptions::{PyFloatingPointError, PyOverflowError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyTuple};
mod parallel_buffers;


const COMMAND_BYTES: usize = 28;

type Matrix = [f64; 6];

#[pyfunction]
fn pack_pixels<'py>(py: Python<'py>, source: &[u8], count: usize, alpha: bool)
    -> PyResult<Bound<'py, pyo3::types::PyBytes>> {
    let channels=if alpha {4} else {3};
    let input=count.checked_mul(channels).ok_or_else(|| PyOverflowError::new_err("pixel size overflow"))?;
    let size=count.checked_mul(4).ok_or_else(|| PyOverflowError::new_err("pixel size overflow"))?;
    if source.len()<input {return Err(PyValueError::new_err("rasterized image data is incomplete"));}
    pyo3::types::PyBytes::new_with(py,size,|output| {
        for (input,output) in source[..input].chunks_exact(channels).zip(output.chunks_exact_mut(4)) {
            let a=if alpha {input[3]} else {255};
            for (target,source) in [(0,2),(1,1),(2,0)] {
                output[target]=if a==255 {input[source]} else {
                    ((input[source] as u16 * a as u16 + 127)/255) as u8
                };
            }
            output[3]=a;
        }
        Ok(())
    })
}

#[pyfunction]
fn merge_wire_commands<'py>(py: Python<'py>, sources: Vec<(Bound<'py, PyAny>, Option<Matrix>)>)
    -> PyResult<(Bound<'py, pyo3::types::PyBytes>, usize)> {
    let mut output = Vec::new();
    let mut commands_count = 0;
    for (commands, transform) in sources {
        if let Ok(bytes) = commands.cast::<pyo3::types::PyBytes>() {
            commands_count += append_wire(bytes.as_bytes(), transform.as_ref(), &mut output)?;
            continue;
        }
        let commands = commands.cast::<PyTuple>()?;
        for command in commands.iter() {
            let command = command.cast::<PyTuple>()?;
            let name = command.get_item(0)?;
            let (kind, count) = match name.extract::<&str>()? {
                "move" => (1u8, 2), "line" => (2, 2), "cubic" => (3, 6), "close" => (4, 0),
                _ => return Err(PyValueError::new_err("invalid wire path command")),
            };
            if command.len() != count + 1 { return Err(PyValueError::new_err("invalid wire path length")); }
            output.push(kind);
            for index in (1..=count).step_by(2) {
                let x = command.get_item(index)?.extract::<f64>()?;
                let y = command.get_item(index + 1)?.extract::<f64>()?;
                let (x, y) = if let Some(matrix) = &transform { point(x, y, matrix)? } else { (x, y) };
                output.extend_from_slice(&x.to_le_bytes());
                output.extend_from_slice(&y.to_le_bytes());
            }
            commands_count += 1;
        }
    }
    Ok((pyo3::types::PyBytes::new(py, &output), commands_count))
}

fn append_wire(data: &[u8], transform: Option<&Matrix>, output: &mut Vec<u8>) -> PyResult<usize> {
    let mut offset = 0; let mut commands = 0;
    while offset < data.len() {
        let kind = data[offset]; offset += 1;
        let count = match kind {1|2 => 2, 3 => 6, 4 => 0,
            _ => return Err(PyValueError::new_err("invalid wire tag"))};
        if data.len()-offset < count*8 {return Err(PyValueError::new_err("truncated wire path"));}
        output.push(kind);
        for _ in (0..count).step_by(2) {
            let mut a=[0u8;8];let mut b=[0u8;8];
            a.copy_from_slice(&data[offset..offset+8]);b.copy_from_slice(&data[offset+8..offset+16]);offset+=16;
            let (x,y)=(f64::from_le_bytes(a),f64::from_le_bytes(b));
            let (x,y)=if let Some(matrix)=transform {point(x,y,matrix)?} else {(x,y)};
            output.extend_from_slice(&x.to_le_bytes());output.extend_from_slice(&y.to_le_bytes());
        }
        commands+=1;
    }
    Ok(commands)
}

#[pyfunction]
fn transform_wire<'py>(py: Python<'py>, data: &[u8], transform: Matrix)
    -> PyResult<(Bound<'py, pyo3::types::PyBytes>, usize)> {
    let mut output=Vec::with_capacity(data.len());
    let count=append_wire(data,Some(&transform),&mut output)?;
    Ok((pyo3::types::PyBytes::new(py,&output),count))
}

#[pyfunction]
#[pyo3(signature = (data, transform=None))]
fn wire_bbox(data: &[u8], transform: Option<Matrix>) -> PyResult<Option<(f64, f64, f64, f64)>> {
    let mut bounds: Option<(f64, f64, f64, f64)> = None;
    let mut offset = 0;
    while offset < data.len() {
        let count = match data[offset] { 1 | 2 => 2, 3 => 6, 4 => 0,
            _ => return Err(PyValueError::new_err("invalid wire path tag")) };
        offset += 1;
        if data.len() - offset < count*8 { return Err(PyValueError::new_err("truncated wire path")); }
        for _ in (0..count).step_by(2) {
            let mut first = [0u8;8]; let mut second = [0u8;8];
            first.copy_from_slice(&data[offset..offset+8]);
            second.copy_from_slice(&data[offset+8..offset+16]); offset += 16;
            let (x, y) = (f64::from_le_bytes(first), f64::from_le_bytes(second));
            let (x, y) = if let Some(matrix) = &transform { point(x, y, matrix)? } else { (x, y) };
            if !x.is_finite() || !y.is_finite() { return Err(PyFloatingPointError::new_err("non-finite bounds")); }
            if let Some((x0,y0,x1,y1)) = &mut bounds {
                if x < *x0 { *x0=x; } if y < *y0 { *y0=y; }
                if x > *x1 { *x1=x; } if y > *y1 { *y1=y; }
            } else { bounds = Some((x,y,x,y)); }
        }
    }
    Ok(bounds)
}

#[pyfunction]
fn pack_wire_path<'py>(py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyByteArray>> {
    let mut offset = 0;
    let mut count = 0usize;
    while offset < data.len() {
        let coordinates = match data[offset] { 1 | 2 => 2, 3 => 6, 4 => 0,
            _ => return Err(PyValueError::new_err("invalid wire path tag")) };
        offset += 1;
        if data.len()-offset < coordinates*8 { return Err(PyValueError::new_err("truncated wire path")); }
        offset += coordinates*8;
        count += 1;
    }
    if count == 0 || count > u32::MAX as usize { return Err(PyValueError::new_err("invalid wire path count")); }
    PyByteArray::new_with(py, count * COMMAND_BYTES, |output| {
        offset = 0;
        for record in output.chunks_exact_mut(COMMAND_BYTES) {
            let kind = data[offset]; offset += 1;
            record[..4].copy_from_slice(&(kind as u32).to_le_bytes());
            let coordinates = match kind { 1 | 2 => 2, 3 => 6, _ => 0 };
            for index in 0..coordinates {
                let mut bytes = [0u8;8]; bytes.copy_from_slice(&data[offset..offset+8]); offset += 8;
                record[4+index*4..8+index*4].copy_from_slice(&(f64::from_le_bytes(bytes) as f32).to_le_bytes());
            }
        }
        Ok(())
    })
}

fn point(x: f64, y: f64, m: &Matrix) -> PyResult<(f64, f64)> {
    // Keep the same operation order as Python, without fused multiply-add.
    let result = (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]);
    if !result.0.is_finite() || !result.1.is_finite() {
        // NaN payload/sign propagation can differ across compilers. Let the
        // Python caller preserve its original behavior for non-finite math.
        return Err(PyFloatingPointError::new_err("non-finite path transform"));
    }
    Ok(result)
}

#[pyfunction]
#[pyo3(signature = (commands, transform=None))]
fn commands_bbox(commands: &Bound<'_, PyTuple>, transform: Option<Matrix>)
    -> PyResult<Option<(f64, f64, f64, f64)>>
{
    let mut bounds: Option<(f64, f64, f64, f64)> = None;
    for command in commands.iter() {
        let command = command.cast::<PyTuple>()?;
        if command.get_item(0)?.extract::<&str>()? == "close" { continue; }
        for index in (1..command.len()).step_by(2) {
            let x = command.get_item(index)?.extract::<f64>()?;
            let y = command.get_item(index + 1)?.extract::<f64>()?;
            let (x, y) = if let Some(m) = &transform { point(x, y, m)? } else { (x, y) };
            if !x.is_finite() || !y.is_finite() {
                return Err(PyFloatingPointError::new_err("non-finite path bounds"));
            }
            if let Some((x0, y0, x1, y1)) = &mut bounds {
                // Python min/max retain the first value for ties and NaNs.
                if x < *x0 { *x0 = x; }
                if y < *y0 { *y0 = y; }
                if x > *x1 { *x1 = x; }
                if y > *y1 { *y1 = y; }
            } else { bounds = Some((x, y, x, y)); }
        }
    }
    Ok(bounds)
}

fn append_transformed<'py>(py: Python<'py>, commands: &Bound<'py, PyTuple>,
                           transform: &Matrix, output: &mut Vec<Py<PyAny>>) -> PyResult<()> {
    for command in commands.iter() {
        let tuple = command.cast::<PyTuple>()?;
        let kind = tuple.get_item(0)?;
        let count = match kind.extract::<&str>()? {
            "close" => { output.push(command.unbind()); continue; },
            "move" | "line" => 2,
            "cubic" => 6,
            _ => return Err(PyValueError::new_err("unsupported vector path command")),
        };
        let mut values = Vec::with_capacity(count + 1);
        values.push(kind.unbind());
        for index in (1..=count).step_by(2) {
            let x = tuple.get_item(index)?.extract::<f64>()?;
            let y = tuple.get_item(index + 1)?.extract::<f64>()?;
            let (x, y) = point(x, y, transform)?;
            values.push(x.into_pyobject(py)?.into_any().unbind());
            values.push(y.into_pyobject(py)?.into_any().unbind());
        }
        output.push(PyTuple::new(py, values)?.into_any().unbind());
    }
    Ok(())
}

#[pyfunction]
fn transform_commands<'py>(py: Python<'py>, commands: &Bound<'py, PyTuple>,
                            transform: Matrix) -> PyResult<Bound<'py, PyTuple>> {
    let mut output = Vec::with_capacity(commands.len());
    append_transformed(py, commands, &transform, &mut output)?;
    PyTuple::new(py, output)
}

#[pyfunction]
fn merge_commands<'py>(py: Python<'py>, sources: Vec<(Bound<'py, PyTuple>, Option<Matrix>)>)
    -> PyResult<Bound<'py, PyTuple>>
{
    let mut output = Vec::new();
    for (commands, transform) in sources {
        if let Some(transform) = transform {
            append_transformed(py, &commands, &transform, &mut output)?;
        } else {
            output.extend(commands.iter().map(|item| item.unbind()));
        }
    }
    PyTuple::new(py, output)
}

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
    module.add_class::<scene_compiler::RustCompiledScene>()?;
    module.add_function(wrap_pyfunction!(scene_compiler::compile_scene, module)?)?;
    module.add_function(wrap_pyfunction!(scene_compiler::native_input::plan_native_scene, module)?)?;
    module.add_function(wrap_pyfunction!(scene_compiler::native_input::compile_native_scene, module)?)?;
    module.add_function(wrap_pyfunction!(parallel_buffers::compress_buffers, module)?)?;
    module.add_function(wrap_pyfunction!(parallel_buffers::decompress_buffer, module)?)?;
    module.add("COMMAND_BYTES", COMMAND_BYTES)?;
    module.add_function(wrap_pyfunction!(pack_path, module)?)?;
    module.add_function(wrap_pyfunction!(pack_pixels, module)?)?;
    module.add_function(wrap_pyfunction!(commands_bbox, module)?)?;
    module.add_function(wrap_pyfunction!(transform_commands, module)?)?;
    module.add_function(wrap_pyfunction!(merge_commands, module)?)?;
    module.add_function(wrap_pyfunction!(merge_wire_commands, module)?)?;
    module.add_function(wrap_pyfunction!(wire_bbox, module)?)?;
    module.add_function(wrap_pyfunction!(transform_wire, module)?)?;
    module.add_function(wrap_pyfunction!(encode_commands, module)?)?;
    module.add_function(wrap_pyfunction!(decode_commands, module)?)?;
    module.add_function(wrap_pyfunction!(pack_wire_path, module)?)?;
    Ok(())
}

#[pyfunction]
fn encode_commands<'py>(py: Python<'py>, commands: &Bound<'py, PyTuple>) -> PyResult<Bound<'py, pyo3::types::PyBytes>> {
    let mut output = Vec::new();
    for command in commands.iter() {
        let command = command.cast::<PyTuple>()?;
        let name = command.get_item(0)?;
        let (kind, count) = match name.extract::<&str>()? {
            "move" => (1u8, 2), "line" => (2, 2), "cubic" => (3, 6), "close" => (4, 0),
            _ => return Err(PyValueError::new_err("invalid wire path command")),
        };
        if command.len() != count + 1 { return Err(PyValueError::new_err("invalid wire path length")); }
        output.push(kind);
        for index in 1..=count {
            output.extend_from_slice(&command.get_item(index)?.extract::<f64>()?.to_le_bytes());
        }
    }
    Ok(pyo3::types::PyBytes::new(py, &output))
}

#[pyfunction]
fn decode_commands<'py>(py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyTuple>> {
    let mut offset = 0;
    let mut commands = Vec::new();
    while offset < data.len() {
        let (name, count) = match data[offset] {
            1 => ("move", 2), 2 => ("line", 2), 3 => ("cubic", 6), 4 => ("close", 0),
            _ => return Err(PyValueError::new_err("invalid wire path tag")),
        };
        offset += 1;
        if data.len() - offset < count * 8 { return Err(PyValueError::new_err("truncated wire path")); }
        let mut values = Vec::with_capacity(count + 1);
        values.push(name.into_pyobject(py)?.into_any().unbind());
        for _ in 0..count {
            let mut bytes = [0u8; 8];
            bytes.copy_from_slice(&data[offset..offset + 8]);
            offset += 8;
            values.push(f64::from_le_bytes(bytes).into_pyobject(py)?.into_any().unbind());
        }
        commands.push(PyTuple::new(py, values)?.into_any().unbind());
    }
    PyTuple::new(py, commands)
}
