# ARPES Converter

A lightweight, browser-based tool for ARPES data format conversion.

This project was developed as a personal practice project for web interface design and scientific data handling.

If any content is found to infringe intellectual property rights, please contact me and it will be removed promptly.

---

## Web


Live Demo: [https://chordc.github.io/arpes-converter-web/](https://chordc.github.io/arpes-converter-web/converter.html)

![ARPES Converter UI](./docs/converter_web_demo.gif)


---

## Features

* `.ibw` → `.npz`
* `.itx` → `.npz`
* `.pxt` → `.npz`
* `.zip` → `.npz`
* `.npz` → `.nc` (xarray)

---

## NPZ Data Structure

In this project, `.npz` is used as a lightweight format for datasets.

```python
{
    "data": np.ndarray,
    "axis_0": np.ndarray,
    "axis_1": np.ndarray,
    "axis_2": np.ndarray,   # optional
    "meta_json": {
        "format_version": "1.0",
        "source_format": str,
        "data_shape": list[int],
        "data_dtype": str,
        "ndim": int,
        "axis_labels": list[str],
        "axis_units": list[str],
        "experiment": {
            "date": str,
            "location": str,
            "hv": float | str,
            "slit": str,
            "sample_name": str,
            "operator": str,
            "temperature_K": float | str,
            "photon_energy_eV": float | str,
            "polarization": str,
            "notes": str
        },
        "custom_metadata": dict
    }
}
```

---

## Xarray / NetCDF Data Structure

In this project, `.nc` is generated as an xarray-compatible `DataArray` for datasets.

```python
{
    "name": "data",
    "dims": [dim_0, dim_1, dim_2],   # e.g. axis_0, axis_1, axis_2
    "coords": {
        dim_0: np.ndarray,
        dim_1: np.ndarray,
        dim_2: np.ndarray   # optional
    },
    "attrs": {
        "source_format": str,
        "format_version": "1.0",
        "data_shape": list[int],
        "data_dtype": str,
        "ndim": int,
        "metadata_mode": str,
        "experiment": dict,
        "custom_metadata": dict
    },
    "values": np.ndarray
}
```

---

## Notes

* Recommended file size: ≤ 100 MB
* Hard limit: ≤ 1 GB
* Large files may be slower due to browser memory limits

---

## Third-Party Libraries

* Pyodide — https://pyodide.org/
* NumPy — https://numpy.org/
* xarray — https://docs.xarray.dev/

---

## License

MIT License
