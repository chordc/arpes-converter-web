# ARPES Converter

A lightweight, browser-based tool for ARPES data format conversion.

This project was developed as a practice in web-based scientific tool design, with the goal of connecting experimental ARPES data to modern Python workflows. As deep learning becomes more important in scientific research, data stored in binary or text-based formats needs to be converted into structured, Python-friendly representations that can be directly used in neural network pipelines for further analysis and model development 🚀📊

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

## Input Data Formats

This tool supports several commonly used ARPES data formats:

* **`.ibw` (Igor Binary Wave)**
  Binary data format used by Igor Pro for storing multidimensional scientific data.
  https://www.wavemetrics.com/

* **`.itx` (Igor Text Format)**
  Text-based export format from Igor Pro, often used for data sharing and inspection.
  https://www.wavemetrics.com/

* **`.pxt` (Packed Igor Text/Binary)**
  Igor Pro packed experiment format, which may contain multiple waves and metadata.
  https://www.wavemetrics.com/

* **DA30 `.zip` (Scienta Omicron Analyzer Output)**
  Zipped data exported from DA30 analyzers, typically containing multidimensional ARPES datasets and metadata files.
  https://scientaomicron.com/

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
