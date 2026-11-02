//! Independent immutable buffers only; no Python/MuPDF/Qt calls in workers.
use pyo3::prelude::*;
use pyo3::exceptions::{PyValueError, PyRuntimeError};
use pyo3::types::PyBytes;
use std::sync::{Mutex,atomic::{AtomicUsize,Ordering}};

const BLOCK: usize = 1024*1024;
const LIMIT: usize = 64*1024*1024;

#[pyfunction]
#[pyo3(signature = (sources, workers=2))]
pub fn compress_buffers<'py>(py: Python<'py>, sources: Vec<Bound<'py,PyBytes>>, workers: usize)
    -> PyResult<Vec<Option<Bound<'py,PyBytes>>>> {
    if !(1..=4).contains(&workers) {return Err(PyValueError::new_err("workers must be 1..4"));}
    let slices: Vec<&[u8]>=sources.iter().map(|source|source.as_bytes()).collect();
    let total=slices.iter().try_fold(0usize,|sum,bytes|sum.checked_add(bytes.len()))
        .ok_or_else(||PyValueError::new_err("buffer size overflow"))?;
    if total>LIMIT {return Err(PyValueError::new_err("parallel image budget exceeded"));}
    let mut jobs=Vec::new();
    let mut ranges=Vec::new();
    for bytes in &slices {
        let start=jobs.len();
        if bytes.len()>=64*1024 {jobs.extend(bytes.chunks(BLOCK));}
        ranges.push(start..jobs.len());
    }
    let workers=workers.min(std::thread::available_parallelism().map_or(1,|n|n.get())).min(jobs.len().max(1));
    let results=py.detach(|| -> Result<Vec<Vec<u8>>,String> {
        let next=AtomicUsize::new(0);
        let result=Mutex::new(vec![Vec::new();jobs.len()]);
        let execute=|| {
            loop {
                let index=next.fetch_add(1,Ordering::Relaxed);
                if index>=jobs.len() {break;}
                let compressed=lz4_flex::block::compress(jobs[index]);
                result.lock().unwrap()[index]=compressed;
            }
        };
        if workers==1 {execute();} else {
            std::thread::scope(|scope| -> Result<(),String> {
                let mut threads=Vec::new();
                for _ in 1..workers {
                    match std::thread::Builder::new().spawn_scoped(scope,&execute) {
                        Ok(thread)=>threads.push(thread),
                        Err(_)=>break, // Remaining work runs on existing threads.
                    }
                }
                execute();
                for thread in threads {thread.join().map_err(|_|"buffer compression worker failed".to_string())?;}
                Ok(())
            })?;
        }
        result.into_inner().map_err(|_|"buffer compression failed".to_string())
    }).map_err(PyRuntimeError::new_err)?;
    let mut output=Vec::with_capacity(slices.len());
    for (bytes,range) in slices.iter().zip(ranges) {
        let size=12+range.clone().map(|i|8+results[i].len()).sum::<usize>();
        if range.is_empty() || size>bytes.len()*9/10 {output.push(None);continue;}
        let packet=PyBytes::new_with(py,size,|packet| {
            packet[..4].copy_from_slice(b"LFZ1");
            packet[4..12].copy_from_slice(&(bytes.len() as u64).to_le_bytes());
            let mut offset=12;
            for (block,index) in bytes.chunks(BLOCK).zip(range) {
                let compressed=&results[index];
                packet[offset..offset+4].copy_from_slice(&(block.len() as u32).to_le_bytes());
                packet[offset+4..offset+8].copy_from_slice(&(compressed.len() as u32).to_le_bytes());
                offset+=8;packet[offset..offset+compressed.len()].copy_from_slice(compressed);offset+=compressed.len();
            }
            Ok(())
        })?;
        output.push(Some(packet));
    }
    Ok(output)
}

#[pyfunction]
pub fn decompress_buffer<'py>(py: Python<'py>, packet: &[u8]) -> PyResult<Bound<'py,PyBytes>> {
    let invalid=||PyValueError::new_err("invalid compressed image buffer");
    if packet.len()<12 || &packet[..4]!=b"LFZ1" {return Err(invalid());}
    let length=u64::from_le_bytes(packet[4..12].try_into().unwrap());
    if length==0 || length>LIMIT as u64 {return Err(invalid());}
    PyBytes::new_with(py,length as usize,|output| {
        // The immutable input remains pinned by the Python argument. The new
        // output is exclusively owned and unpublished until this constructor
        // returns. Detached work touches only these slices, never Python/Qt/SDK.
        py.detach(|| decompress_into(packet,output)).map_err(|_|invalid())
    })
}

fn decompress_into(packet:&[u8],output:&mut [u8])->Result<(),()> {
        let (mut input,mut target)=(12,0);
        while input<packet.len() {
            if packet.len()-input<8 {return Err(());}
            let raw=u32::from_le_bytes(packet[input..input+4].try_into().unwrap()) as usize;
            let size=u32::from_le_bytes(packet[input+4..input+8].try_into().unwrap()) as usize;
            input+=8;
            if raw==0 || raw>BLOCK || raw>output.len()-target || size>packet.len()-input {return Err(());}
            let written=lz4_flex::block::decompress_into(&packet[input..input+size],&mut output[target..target+raw])
                .map_err(|_|())?;
            if written!=raw {return Err(());}
            input+=size;target+=raw;
        }
        if target!=output.len() {return Err(());}
        Ok(())
}
