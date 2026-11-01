//! Shared compiler core and optional CPython bindings.
pub mod scene_compiler;
#[cfg(feature="python")]
include!("python_extension.rs");
