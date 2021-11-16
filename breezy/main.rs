use pkg_version::*;
use pyo3::prelude::*;
use pyo3::types::*;

const MAJOR: u32 = pkg_version_major!();
const MINOR: u32 = pkg_version_minor!();
const PATCH: u32 = pkg_version_patch!();

fn check_version(py: Python<'_>) -> PyResult<()> {
    let breezy = PyModule::import(py, "breezy").map_err(|e| {
        eprintln!(
            "brz: ERROR: Couldn't import breezy and dependencies.\n\
             Please check the directory containing breezy is on your PYTHONPATH.\n"
        );
        e
    })?;

    let ver = breezy
        .getattr("version_info")?
        .extract::<(u32, u32, u32, String, u32)>()?;

    if ver.0 != MAJOR || ver.1 != MINOR || ver.2 != PATCH {
        eprintln!(
            "\
            brz: WARNING: breezy version doesn't match the brz program.\n  \
            This may indicate an installation problem.\n  \
            breezy version is {}\n  \
            brz version is {}.{}.{}\n",
            breezy.getattr("_format_version_tuple")?.call1((ver,))?,
            MAJOR,
            MINOR,
            PATCH
        );
    }
    Ok(())
}

fn setup_locale(py: Python<'_>) -> PyResult<()> {
    let locale = PyModule::import(py, "locale")?;
    locale
        .getattr("setlocale")?
        .call1((locale.getattr("LC_ALL")?, ""))?;
    Ok(())
}

// TODO: Does not actually work? Upstream has been messing around again.
fn ensure_sane_fs_enc() -> () {
    let new_enc = std::ffi::CString::new("utf8").unwrap().into_raw();
    unsafe {
        pyo3::ffi::Py_FileSystemDefaultEncoding = new_enc;
        pyo3::ffi::Py_HasFileSystemDefaultEncoding = 1;
    }
}

fn posix_setup(py: Python<'_>) -> PyResult<()> {
    let os = PyModule::import(py, "os")?;

    if os.getattr("name")?.to_string() == "posix" {
        if let Err(e) = setup_locale(py) {
            eprintln!(
                "brz: WARNING: {}\n  \
                Could not set the application locale.\n  \
                Although this should be no problem for bzr itself, it might\n  \
                cause problems with some plugins. To investigate the issue,\n  \
                look at the output of the locale(1p) tool.\n",
                e
            );
        };
    }
    Ok(())
}

fn main() -> PyResult<()> {
    pyo3::prepare_freethreaded_python();
    Python::with_gil(|py| {
        posix_setup(py)?;

        check_version(py)?;

        let args: Vec<String> = std::env::args().collect();

        if args.contains(&String::from("--profile-imports")) {
            let profile_imports = PyModule::import(py, "profile_imports")?;
            profile_imports.getattr("install")?.call1(())?;
        }

        let sys = PyModule::import(py, "sys")?;
        sys.setattr("argv", PyList::new(py, args))?;

        let main = PyModule::import(py, "breezy.__main__")?;
        main.getattr("main")?.call1(())?;
        Ok(())
    })
}