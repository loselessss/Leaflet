//! Look up packed viewport scenes without scanning metadata from other pages.
use pyo3::prelude::*;
use std::collections::HashMap;

type Viewport = (f64, f64, f64, f64);

struct Entry {
    scale: f64,
    density: f64,
    density_sensitive: bool,
    viewport: Option<Viewport>,
}

#[pyclass]
#[derive(Default)]
pub struct PackedSceneIndex {
    entries: HashMap<(usize, bool), Vec<Entry>>,
}

#[pymethods]
impl PackedSceneIndex {
    #[new]
    fn new() -> Self {
        Self::default()
    }

    #[pyo3(signature = (page, scale, variant, density, density_sensitive, viewport=None))]
    fn insert(
        &mut self,
        page: usize,
        scale: f64,
        variant: bool,
        density: f64,
        density_sensitive: bool,
        viewport: Option<Viewport>,
    ) {
        self.remove(page, scale, variant, viewport);
        self.entries.entry((page, variant)).or_default().push(Entry {
            scale,
            density,
            density_sensitive,
            viewport,
        });
    }

    #[pyo3(signature = (page, scale, variant, viewport=None))]
    fn remove(&mut self, page: usize, scale: f64, variant: bool, viewport: Option<Viewport>) {
        let key = (page, variant);
        if let Some(items) = self.entries.get_mut(&key) {
            items.retain(|item| item.scale != scale || item.viewport != viewport);
            if items.is_empty() {
                self.entries.remove(&key);
            }
        }
    }

    fn clear(&mut self) {
        self.entries.clear();
    }

    #[pyo3(signature = (page, scale, variant, viewport=None))]
    fn find(
        &self,
        page: usize,
        scale: f64,
        variant: bool,
        viewport: Option<Viewport>,
    ) -> Option<(f64, Option<Viewport>)> {
        let items = self.entries.get(&(page, variant))?;
        items
            .iter()
            .rev()
            .find(|entry| {
                (!entry.density_sensitive || entry.density >= scale)
                    && covers(entry.viewport, viewport)
            })
            .map(|entry| (entry.scale, entry.viewport))
    }
}

fn covers(existing: Option<Viewport>, requested: Option<Viewport>) -> bool {
    match (existing, requested) {
        (None, None) => true,
        (Some((x0, y0, x1, y1)), Some((a0, b0, a1, b1))) => {
            x0 <= a0 + 1e-6 && y0 <= b0 + 1e-6 && x1 >= a1 - 1e-6 && y1 >= b1 - 1e-6
        }
        _ => false,
    }
}
