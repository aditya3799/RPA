use pyo3::prelude::*;

/// Move the mouse to absolute coordinates (x, y)
#[pyfunction]
fn move_mouse_to(x: i32, y: i32) -> PyResult<()> {
    use enigo::{Coordinate, Enigo, Mouse, Settings};
    let mut enigo = Enigo::new(&Settings::default())
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to init Enigo: {:?}", e)))?;
    enigo.move_mouse(x, y, Coordinate::Abs)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to move mouse: {:?}", e)))?;
    Ok(())
}

/// Simulate a left mouse click (press and release)
#[pyfunction]
fn click_mouse() -> PyResult<()> {
    use enigo::{Button, Direction, Enigo, Mouse, Settings};
    let mut enigo = Enigo::new(&Settings::default())
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to init Enigo: {:?}", e)))?;
    enigo.button(Button::Left, Direction::Click)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to click: {:?}", e)))?;
    Ok(())
}

/// Capture a frame from the primary display.
/// Returns a tuple of (width, height, BGRA raw pixels vector).
#[pyfunction]
fn capture_screen() -> PyResult<(usize, usize, Vec<u8>)> {
    use scrap::{Capturer, Display};
    use std::io::ErrorKind::WouldBlock;
    use std::thread;
    use std::time::Duration;

    let display = Display::primary()
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to get primary display: {:?}", e)))?;
    let width = display.width();
    let height = display.height();
    let mut capturer = Capturer::new(display)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create capturer: {:?}", e)))?;

    // Attempt to capture a frame (with a retry limit if it blocks)
    for _ in 0..15 {
        match capturer.frame() {
            Ok(frame) => {
                // The frame is BGRA. Convert to a standard Vec<u8> to send to Python.
                return Ok((width, height, frame.to_vec()));
            }
            Err(ref e) if e.kind() == WouldBlock => {
                thread::sleep(Duration::from_millis(30));
                continue;
            }
            Err(e) => {
                return Err(pyo3::exceptions::PyRuntimeError::new_err(format!("Capture failed: {:?}", e)));
            }
        }
    }
    Err(pyo3::exceptions::PyRuntimeError::new_err("Timeout waiting for frame from screen capturer"))
}

/// A Python module implemented in Rust.
#[pymodule]
fn rust_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(move_mouse_to, m)?)?;
    m.add_function(wrap_pyfunction!(click_mouse, m)?)?;
    m.add_function(wrap_pyfunction!(capture_screen, m)?)?;
    Ok(())
}
