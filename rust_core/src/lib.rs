use pyo3::prelude::*;
use pyo3::types::PyBytes;

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
fn click_mouse(x: i32, y: i32) -> PyResult<()> {
    use enigo::{Button, Coordinate, Direction, Enigo, Mouse, Settings};
    use std::thread;
    use std::time::Duration;

    let mut enigo = Enigo::new(&Settings::default())
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to init Enigo: {:?}", e)))?;
    
    // First, move to the correct coordinates using the SAME enigo instance
    enigo.move_mouse(x, y, Coordinate::Abs)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to move mouse: {:?}", e)))?;

    enigo.button(Button::Left, Direction::Press)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to press: {:?}", e)))?;
        
    // Hold the mouse click for 50ms to ensure the OS and UI frameworks register the click
    thread::sleep(Duration::from_millis(50));
    
    enigo.button(Button::Left, Direction::Release)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to release: {:?}", e)))?;
        
    Ok(())
}

// --- Raw CoreGraphics / CoreFoundation FFI for screen capture ---
//
// The `core-graphics` Rust crate (0.23) doesn't expose CGImage's data
// provider or CFData APIs, so we call the C functions directly.

#[repr(C)]
struct CGPoint {
    x: f64,
    y: f64,
}

#[repr(C)]
struct CGSize {
    width: f64,
    height: f64,
}

#[repr(C)]
struct CGRect {
    origin: CGPoint,
    size: CGSize,
}

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGMainDisplayID() -> u32;
    fn CGDisplayBounds(display_id: u32) -> CGRect;
    fn CGDisplayCreateImage(display_id: u32) -> *mut std::ffi::c_void;
    fn CGImageGetWidth(image: *const std::ffi::c_void) -> usize;
    fn CGImageGetHeight(image: *const std::ffi::c_void) -> usize;
    fn CGImageGetBytesPerRow(image: *const std::ffi::c_void) -> usize;
    fn CGImageGetBitsPerPixel(image: *const std::ffi::c_void) -> usize;
    fn CGImageGetDataProvider(image: *const std::ffi::c_void) -> *const std::ffi::c_void;
    fn CGDataProviderCopyData(provider: *const std::ffi::c_void) -> *mut std::ffi::c_void;
    fn CGImageRelease(image: *mut std::ffi::c_void);
}

#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn CFDataGetBytePtr(data: *const std::ffi::c_void) -> *const u8;
    fn CFDataGetLength(data: *const std::ffi::c_void) -> isize;
    fn CFRelease(cf: *mut std::ffi::c_void);
}

/// Capture a frame from the primary display using CGDisplayCreateImage.
///
/// This replaces the old `scrap`-based capturer which had critical bugs:
///   - Stride mismatch: `scrap` reported logical dimensions but the IOSurface
///     frame was at a different resolution/stride, causing diagonal shearing.
///   - Use-after-free: explicit `drop(capturer)` freed the struct while the
///     CGDisplayStream callback still held a raw pointer, causing SIGSEGV.
///   - Blank frames: the stream needed warm-up time after creation.
///
/// `CGDisplayCreateImage` avoids all of these: it's a single-shot snapshot
/// that returns a CGImage with the correct `bytes_per_row` stride.
/// The image is returned at the physical pixel resolution (Retina).
#[pyfunction]
fn capture_screen(py: Python<'_>) -> PyResult<(usize, usize, Py<PyBytes>)> {
    unsafe {
        // 1. Grab a snapshot of the main display
        let display_id = CGMainDisplayID();
        let cg_image = CGDisplayCreateImage(display_id);
        if cg_image.is_null() {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "CGDisplayCreateImage failed. \
                 Grant Screen Recording permission to Terminal / Cursor / Python in \
                 System Settings > Privacy & Security > Screen Recording."
            ));
        }

        // 2. Read image metadata
        let width = CGImageGetWidth(cg_image);
        let height = CGImageGetHeight(cg_image);
        let bytes_per_row = CGImageGetBytesPerRow(cg_image);
        let bits_per_pixel = CGImageGetBitsPerPixel(cg_image);
        let bpp = bits_per_pixel / 8;

        if width < 100 || height < 100 {
            CGImageRelease(cg_image);
            return Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
                "Captured image too small ({}x{}) — Screen Recording \
                 permission is likely denied.",
                width, height
            )));
        }

        if bpp != 4 {
            CGImageRelease(cg_image);
            return Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
                "Unexpected pixel format: {} bits/pixel (expected 32)",
                bits_per_pixel
            )));
        }

        // 3. Copy the raw pixel data out of the CGImage
        let provider = CGImageGetDataProvider(cg_image);
        if provider.is_null() {
            CGImageRelease(cg_image);
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "CGImageGetDataProvider returned NULL"
            ));
        }

        let cf_data = CGDataProviderCopyData(provider);
        if cf_data.is_null() {
            CGImageRelease(cg_image);
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "CGDataProviderCopyData returned NULL"
            ));
        }

        let raw_ptr = CFDataGetBytePtr(cf_data);
        let raw_len = CFDataGetLength(cf_data) as usize;
        let raw_bytes = std::slice::from_raw_parts(raw_ptr, raw_len);

        // 4. Build a tightly-packed BGRA buffer using the CORRECT stride.
        //    On Retina Macs, bytes_per_row often exceeds width*4 due to
        //    GPU memory alignment — this was the root cause of the diagonal
        //    corruption with the old scrap-based capturer.
        let row_pixel_bytes = width * bpp;
        let result = if bytes_per_row == row_pixel_bytes {
            // No row padding — data is already tightly packed.
            let end = row_pixel_bytes * height;
            let end = std::cmp::min(end, raw_len);
            PyBytes::new(py, &raw_bytes[..end]).unbind()
        } else {
            // Strip per-row padding.
            let mut packed = Vec::with_capacity(row_pixel_bytes * height);
            for y in 0..height {
                let start = y * bytes_per_row;
                let end = start + row_pixel_bytes;
                if end > raw_len {
                    break;
                }
                packed.extend_from_slice(&raw_bytes[start..end]);
            }
            PyBytes::new(py, &packed).unbind()
        };

        // 5. Clean up CoreFoundation / CoreGraphics objects
        CFRelease(cf_data);
        CGImageRelease(cg_image);

        Ok((width, height, result))
    }
}

/// Simulate typing a string of text
/// Note: On macOS, direct keyboard event generation can cause Objective-C runtime corruption.
/// In simulation mode or when actual typing is not critical, this safely returns success.
#[pyfunction]
fn type_text(text: String) -> PyResult<()> {
    use enigo::{Enigo, Keyboard, Settings};
    use std::thread;
    use std::time::Duration;
    
    let mut enigo = Enigo::new(&Settings::default())
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to init Enigo: {:?}", e)))?;
        
    enigo.text(&text)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to type text: {:?}", e)))?;
        
    let delay_ms = std::cmp::min(text.len() as u64 * 10, 500);
    thread::sleep(Duration::from_millis(delay_ms));
    Ok(())
}

/// Simulate pressing a special key (e.g., Return, Escape, Tab, Backspace, Space)
#[pyfunction]
fn press_key(key_name: String) -> PyResult<()> {
    use enigo::{Direction::Click, Enigo, Key, Keyboard, Settings};
    let mut enigo = Enigo::new(&Settings::default())
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to init Enigo: {:?}", e)))?;

    let key = match key_name.to_lowercase().as_str() {
        "return" | "enter" => Key::Return,
        "escape" | "esc" => Key::Escape,
        "tab" => Key::Tab,
        "backspace" => Key::Backspace,
        "space" => Key::Space,
        _ => return Err(pyo3::exceptions::PyValueError::new_err(format!("Unsupported key name: {}", key_name))),
    };

    enigo.key(key, Click)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to press key: {:?}", e)))?;
    Ok(())
}

/// Retrieve logical screen size for precise mouse coordinate scaling
#[pyfunction]
fn get_logical_screen_size() -> PyResult<(f64, f64)> {
    unsafe {
        let display_id = CGMainDisplayID();
        let bounds = CGDisplayBounds(display_id);
        Ok((bounds.size.width, bounds.size.height))
    }
}

/// A Python module implemented in Rust.
#[pymodule]
fn rust_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(move_mouse_to, m)?)?;
    m.add_function(wrap_pyfunction!(click_mouse, m)?)?;
    m.add_function(wrap_pyfunction!(capture_screen, m)?)?;
    m.add_function(wrap_pyfunction!(type_text, m)?)?;
    m.add_function(wrap_pyfunction!(press_key, m)?)?;
    m.add_function(wrap_pyfunction!(get_logical_screen_size, m)?)?;
    Ok(())
}
